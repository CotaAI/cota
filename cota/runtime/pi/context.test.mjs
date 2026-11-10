import test from 'node:test';
import assert from 'node:assert/strict';
import {estimateRequest, compactContext, resolveContextModel} from './context.mjs';
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
