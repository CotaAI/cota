import test from 'node:test';
import assert from 'node:assert/strict';
import {estimateRequest, compactContext, resolveContextModel, compactionSettings} from './context.mjs';
import {createAssistantMessageEventStream} from '@earendil-works/pi-ai';

const msg = (role, content, id) => ({role, content, cotaEventId: id, timestamp: 1});
const model = {id: 'test', api: 'openai-completions', provider: 'cota', contextWindow: 8000, maxTokens: 500};
const settings = {enabled: true, reserveTokens: 1000, keepRecentTokens: 1000};
function history() {
  return [msg('system', 'current rules', 'system'), msg('user', 'Make a book; preserve its name and constraints.', 'u'),
    msg('assistant', [{type: 'toolCall', id: 'a', name: 'read', arguments: {path: '/book/guide'}}], 'a'),
    {...msg('toolResult', [{type: 'text', text: 'guide '.repeat(6000)}], 'ar'), toolCallId: 'a', toolName: 'read'},
    msg('assistant', [{type: 'toolCall', id: 'b', name: 'read', arguments: {path: '/book/character.png'}}], 'b'),
    {...msg('toolResult', [{type: 'text', text: 'image read'},
      {type: 'image', mimeType: 'image/png', data: 'x'.repeat(2200000)}], 'br'), toolCallId: 'b', toolName: 'read'}];
}
function summaryStream(calls, response = 'Goal: Make a book. Progress: guide read. Keep /book/character.png.') {
  return async (_model, context) => {
    calls.push(context);
    const stream = createAssistantMessageEventStream();
    const message = {role: 'assistant', content: [{type: 'text', text: response}], stopReason: 'stop',
      usage: {input: 200, output: 30, cacheRead: 0, cacheWrite: 0, totalTokens: 230}, timestamp: 2};
    stream.push({type: 'done', reason: 'stop', message});
    return stream;
  };
}
test('image budget uses Pi image estimates rather than base64 length', () => {
  const messages = history().slice(-2);
  const budget = estimateRequest(messages, []);
  assert(budget.estimated_tokens < 2000);
  assert.equal(budget.images, 1);
  assert.equal(budget.image_bytes, 1650000);
});
test('Pi compacts a single user turn and keeps the latest tool call with its image result', async () => {
  const calls = [], messages = history();
  const value = await compactContext(messages, model, settings, summaryStream(calls));
  assert.deepEqual(value.replaced_message_ids, ['u', 'a', 'ar']);
  assert.equal(value.first_kept_id, 'b');
  assert(value.summary.includes('Make a book'));
  assert.equal(calls.length, 1);
  assert(!JSON.stringify(calls).includes('x'.repeat(1000)));
  assert.equal(messages.at(-1).content[1].data.length, 2200000);
});
test('empty and truncated Pi summaries fail without a compaction result', async () => {
  await assert.rejects(compactContext(history(), model, settings, summaryStream([], '')), /empty|summary|summarization/i);
  const streamFn = async () => {
    const stream = createAssistantMessageEventStream();
    const message = {role: 'assistant', content: [{type: 'text', text: 'partial'}], stopReason: 'length', timestamp: 2};
    stream.push({type: 'done', reason: 'length', message});
    return stream;
  };
  await assert.rejects(compactContext(history(), model, settings, streamFn), /truncat|limit|token cap/i);
});
test('a single unsplittable request fails explicitly instead of dropping a tool result', async () => {
  await assert.rejects(compactContext([msg('user', 'x'.repeat(40000), 'u')], model, settings,
    summaryStream([])), /cannot|boundary|split/i);
});
test('explicit capacity wins and unknown capacity is labelled as a fallback', () => {
  assert.equal(resolveContextModel({id: 'private-model', contextWindow: 32000, maxTokens: 2000}).contextWindow, 32000);
  assert.equal(resolveContextModel({id: 'private-model', maxTokens: 2000}).capacitySource, 'fallback');
});

test('oversized imported summary input is rejected before calling a provider', async () => {
  const calls = [];
  const messages = [msg('user', 'a'.repeat(40000), 'u1'), msg('user', 'b'.repeat(40000), 'u2'),
    msg('user', 'c'.repeat(8000), 'current')];
  await assert.rejects(compactContext(messages, model, settings, summaryStream(calls)), /summary.*budget/i);
  assert.equal(calls.length, 0);
});

test('Pi cancellation never produces a replacement summary', async () => {
  const controller = new AbortController();
  const stream = summaryStream([]);
  await assert.rejects(compactContext(history(), model, settings, async (...args) => {
    controller.abort();
    return stream(...args);
  }, controller.signal), /abort/i);
});

test('retained usage from before a compaction boundary cannot retrigger compaction', () => {
  const messages = [
    {...msg('user', 'summary', 'summary'), cotaCompaction: true, timestamp: 100},
    {...msg('assistant', [{type: 'text', text: 'old but retained'}], 'old'),
      usage: {input: 100000, output: 1000, cacheRead: 0, cacheWrite: 0, totalTokens: 101000}},
  ];
  assert(estimateRequest(messages).budget_tokens < 1000);
  assert.equal(estimateRequest(messages).usage_based_tokens, null);
});

test('usage-based budgets reserve room for current system and tool changes', () => {
  const messages = [msg('system', 's'.repeat(6000), 'system'), msg('user', 'u'.repeat(6000), 'u'),
    {...msg('assistant', [{type: 'text', text: 'done'}], 'a'),
      usage: {input: 3400, output: 100, cacheRead: 0, cacheWrite: 0, totalTokens: 3500}}];
  const budget = estimateRequest(messages);
  assert(budget.budget_tokens >= 5000);
});

function imageHistory() {
  const messages = [msg('user', 'Make a book and preserve its constraints.', 'u')];
  for (let i = 0; i < 6; i++) {
    messages.push(msg('assistant', [{type: 'toolCall', id: `image${i}`, name: 'read',
      arguments: {path: `/book/page${i}.png`}}], `a${i}`));
    messages.push({...msg('toolResult', [{type: 'image', mimeType: 'image/png', data: 'x'.repeat(1024 * 1024)}], `r${i}`),
      toolCallId: `image${i}`, toolName: 'read'});
  }
  return messages;
}

test('serialized-byte accounting includes image encoding without counting it as tokens', () => {
  const messages = imageHistory();
  const budget = estimateRequest(messages);
  assert(budget.serialized_bytes >= 6 * 1024 * 1024);
  assert(budget.estimated_tokens < 10000);
});

test('Pi shrinks its retained token target when image bytes exceed the request budget', async () => {
  const messages = imageHistory(), calls = [];
  const largeModel = {...model, contextWindow: 1000000};
  const limits = compactionSettings(largeModel, {keep_recent_tokens: 20000, max_request_bytes: 3 * 1024 * 1024});
  const result = await compactContext(messages, largeModel, limits, summaryStream(calls));
  assert(result.replaced_message_ids.length > 0);
  const kept = messages.slice(result.replaced_message_ids.length);
  assert(estimateRequest(kept).serialized_bytes < limits.maxRequestBytes);
  assert.equal(kept[0].role, 'assistant');
  assert.equal(kept.at(-1).toolCallId, 'image5');
  assert.equal(calls.length, 1);
  assert(!JSON.stringify(calls).includes('x'.repeat(1000)));
  assert.equal(messages.at(-1).content[0].data.length, 1024 * 1024);
});

test('an indivisible latest image fails explicitly without dropping it or requesting a summary', async () => {
  const messages = imageHistory().slice(0, 3), calls = [];
  const limits = compactionSettings({...model, contextWindow: 1000000}, {max_request_bytes: 128 * 1024});
  await assert.rejects(compactContext(messages, {...model, contextWindow: 1000000}, limits, summaryStream(calls)),
    /latest.*(batch|message).*byte|smaller image/i);
  assert.equal(calls.length, 0);
  assert.equal(messages.at(-1).content[0].data.length, 1024 * 1024);
});

test('attachment bytes follow the actual model hydration MIME and size policy', () => {
  const files = Array.from({length: 8}, (_, i) => ({id: `file${i}`, mime_type: 'image/png', size: 2 * 1024 * 1024}));
  const messages = [{...msg('user', 'Inspect these files with the appropriate tool.', 'u'), cotaAttachments: files}];
  const textModel = resolveContextModel({attachmentImages: {mimeTypes: [], maxBytes: 2 * 1024 * 1024}});
  assert(estimateRequest(messages, [], textModel).serialized_bytes < 4096);
  const visionModel = resolveContextModel({attachmentImages: {mimeTypes: ['image/png'], maxBytes: 2 * 1024 * 1024}});
  assert(estimateRequest(messages, [], visionModel).serialized_bytes > 20 * 1024 * 1024);
  const svg = [{...messages[0], cotaAttachments: [{id: 'svg', mime_type: 'image/svg+xml', size: 2 * 1024 * 1024}]}];
  assert(estimateRequest(svg, [], visionModel).serialized_bytes < 4096);
});

test('image retention has count and byte budgets independent of model capacity', () => {
  const limits = compactionSettings({...model, contextWindow: 1000000});
  assert.equal(limits.maxImages, 8);
  assert.equal(limits.maxImageBytes, 16 * 1024 * 1024);
  for (const options of [{max_images: 0}, {max_images: true}, {max_image_bytes: -1}])
    assert.throws(() => compactionSettings(model, options), /image/i);
});

test('Pi reduces retained images under image-only pressure and keeps the latest complete batch', async () => {
  const messages = imageHistory(), before = JSON.stringify(messages), calls = [];
  const largeModel = {...model, contextWindow: 1000000};
  const limits = compactionSettings(largeModel, {max_images: 2, max_image_bytes: 2 * 1024 * 1024});
  const result = await compactContext(messages, largeModel, limits, summaryStream(calls));
  const kept = messages.slice(result.replaced_message_ids.length);
  const budget = estimateRequest(kept);
  assert(budget.images <= 2 && budget.image_bytes <= limits.maxImageBytes);
  assert.equal(kept[0].role, 'assistant');
  assert.equal(kept.at(-1).toolCallId, 'image5');
  assert.equal(calls.length, 1);
  assert.equal(JSON.stringify(messages), before);
});

test('an oversized current multi-image batch is not silently split or summarized away', async () => {
  const messages = [msg('user', 'Compare all three images.', 'u'),
    msg('assistant', [0, 1, 2].map(i => ({type: 'toolCall', id: `c${i}`, name: 'read', arguments: {path: `${i}.png`}})), 'a'),
    ...[0, 1, 2].map(i => ({...msg('toolResult', [{type: 'image', mimeType: 'image/png', data: 'a'.repeat(100)}], `r${i}`),
      toolCallId: `c${i}`, toolName: 'read'}))];
  const calls = [];
  await assert.rejects(compactContext(messages, model, compactionSettings(model, {max_images: 2}), summaryStream(calls)),
    /latest.*(batch|message).*image|image.*budget/i);
  assert.equal(calls.length, 0);
  assert.equal(messages.filter(m => m.role === 'toolResult').length, 3);
});

test('usage from a request with omitted old pixels cannot force compaction of the smaller projection', async () => {
  const {projectImageContext} = await import('./image-context.mjs');
  const messages = [msg('user', 'inspect', 'u'),
    msg('assistant', [{type: 'toolCall', id: 'old', name: 'read', arguments: {path: '/old.png'}}], 'call'),
    {...msg('toolResult', [{type: 'image', mimeType: 'image/png', data: 'eA=='}], 'image'), toolCallId: 'old'},
    {...msg('assistant', [{type: 'text', text: 'The border is blue.'}], 'answer'),
      usage: {input: 100000, output: 1000, cacheRead: 0, cacheWrite: 0, totalTokens: 101000}},
    msg('user', 'continue', 'new')];
  const budget = estimateRequest(projectImageContext(messages));
  assert(budget.budget_tokens < 2000);
  assert.equal(budget.usage_based_tokens, null);
});
