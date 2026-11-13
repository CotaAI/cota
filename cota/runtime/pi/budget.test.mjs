import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {runAgent} from './engine.mjs';

const user = {role: 'user', content: 'Finish the existing work.', timestamp: 1, cotaEventId: 'user'};
const schema = {type: 'function', function: {name: 'act', description: 'A side effect',
  parameters: {type: 'object', properties: {n: {type: 'number'}}, required: ['n']}}};
const toolCall = n => ({id: `call-${n}`, type: 'function', function: {name: 'act', arguments: JSON.stringify({n})}});

function harness(respond) {
  const history = [structuredClone(user)], preparations = [], requests = [], calls = [], events = [];
  return {history, preparations, requests, calls, events, rpc: async (method, payload) => {
    if (method === 'skills_loaded') return {};
    if (method === 'prepare') {
      preparations.push(structuredClone(payload));
      return {messages: history, systemPrompt: 'Business guidance.', tools: [schema]};
    }
    if (method === 'model') {requests.push(payload); return respond(payload, requests.length);}
    if (method === 'reject_output') return {};
    if (method === 'tool') {calls.push(payload); return {content: [{type: 'text', text: `saved ${payload.args.n}`}], details: {}};}
    if (method === 'event') {
      events.push(payload.event);
      if (payload.event.type === 'message_end' && payload.event.message.role !== 'system') history.push(payload.event.message);
      return {};
    }
    throw new Error(`Unexpected RPC ${method}`);
  }};
}

const options = extra => ({messages: [structuredClone(user)], maxIterations: 10, ...extra});
const finalText = 'Eight steps saved. Delivery is blocked; no files were sent.';
const dsml = '<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name="act">\n</｜｜DSML｜｜ invoke>\n</｜｜DSML｜｜ calls>';

test('DSML is not a final reply; Pi retries text-only once within the original budget', async () => {
  const h = harness((_request, n) => n <= 8 ? {tool_calls: [toolCall(n)]}
    : {content: n === 9 ? dsml : finalText});
  const result = await runAgent(options(), h.rpc);
  assert.equal(h.requests.length, 10);
  assert.equal(h.calls.length, 8);
  assert.equal(result.hasFinalReply, true);
  assert.equal(result.status, 'limited');
  assert.equal(h.requests.at(-1).toolChoice, 'none');
  assert(!JSON.stringify(h.requests.at(-1).messages).includes('DSML'));
  assert.match(JSON.stringify(h.requests.at(-1).messages.at(-1)), /previous.*invalid|protocol.*text/i);
  assert(!h.events.some(e => e.message?.role === 'assistant' && JSON.stringify(e.message).includes('DSML')));
});

test('repeated malformed wrap-up replies stop without side effects or false success', async () => {
  const h = harness((_request, n) => n <= 8 ? {tool_calls: [toolCall(n)]} : {content: dsml});
  const result = await runAgent(options(), h.rpc);
  assert.equal(h.requests.length, 10);
  assert.equal(h.calls.length, 8);
  assert.equal(result.hasFinalReply, false);
  assert.equal(result.outputError, 'invalid_model_output');
});

test('the original budget reserves a committed final reply and warns before wrap-up', async () => {
  const h = harness((request, n) => {
    if (n <= 8) return {tool_calls: [toolCall(n)]};
    assert.deepEqual(request.tools, [schema]);
    assert.equal(request.toolChoice, 'none');
    assert.match(JSON.stringify(request.messages.at(-1)), /No tool calls|No tools/i);
    return {content: finalText};
  });
  const input = options(), original = structuredClone(input);
  const result = await runAgent(input, h.rpc);
  assert.equal(result.status, 'limited');
  assert.equal(result.hasFinalReply, true);
  assert.equal(h.requests.length, 9);
  assert.equal(h.calls.length, 8);
  assert.deepEqual(h.preparations.map(p => p.executionBudget.used), [0,1,2,3,4,5,6,7,8]);
  assert(h.preparations.some(p => p.executionBudget.phase === 'warning'));
  assert.equal(h.preparations.at(-1).executionBudget.phase, 'wrap_up');
  assert.deepEqual(h.requests.at(-1).contextBudget.execution, h.preparations.at(-1).executionBudget);
  assert(h.events.some(e => e.type === 'message_end' && e.message.role === 'assistant'
    && e.message.content.some(block => block.text === finalText)));
  assert.deepEqual(input, original);
});

test('hallucinated wrap-up tool calls never execute and cannot exceed the original limit', async () => {
  const h = harness((_request, n) => ({tool_calls: [toolCall(n)]}));
  const result = await runAgent(options(), h.rpc);
  assert.equal(h.requests.length, 10);
  assert.equal(h.calls.length, 8);
  assert.equal(result.status, 'limited');
  assert.equal(result.hasFinalReply, false);
  const blocked = h.history.filter(m => m.role === 'toolResult' && m.isError);
  assert.equal(blocked.length, 2);
});

test('a hallucinated first wrap-up call can still be followed by a truthful final answer', async () => {
  const h = harness((_request, n) => n === 10 ? {content: finalText} : {tool_calls: [toolCall(n)]});
  const result = await runAgent(options(), h.rpc);
  assert.equal(h.calls.length, 8);
  assert.equal(h.requests.length, 10);
  assert.equal(result.hasFinalReply, true);
  assert.equal(result.status, 'limited');
});

test('empty or truncated wrap-up text is not claimed as a committed final reply', async () => {
  for (const response of [{content: ''}, {content: 'partial', finish_reason: 'length'}]) {
    const h = harness((_request, n) => n <= 8 ? {tool_calls: [toolCall(n)]} : response);
    const result = await runAgent(options(), h.rpc);
    assert.equal(result.status, 'limited');
    assert.equal(result.hasFinalReply, false);
    assert.equal(h.calls.length, 8);
  }
});

test('early completion and default tiny budgets retain their original completion semantics', async () => {
  const early = harness(() => ({content: 'Already done.'}));
  assert.equal((await runAgent(options(), early.rpc)).status, 'completed');
  const tiny = harness((_request, n) => n === 3 ? {content: 'Done.'} : {tool_calls: [toolCall(n)]});
  const result = await runAgent(options({maxIterations: 3}), tiny.rpc);
  assert.equal(result.status, 'completed');
  assert.equal(tiny.calls.length, 2);
  assert(tiny.preparations.every(p => p.executionBudget.reserved === 0));
  assert(tiny.requests.every(p => p.systemPrompt === 'Business guidance.'));
});

test('explicit reserve supports small budgets and can be disabled without adding calls', async () => {
  const tiny = harness((_request, n) => n === 3 ? {content: finalText} : {tool_calls: [toolCall(n)]});
  const result = await runAgent(options({maxIterations: 3, wrapUpIterations: 1}), tiny.rpc);
  assert.equal(tiny.calls.length, 2);
  assert.equal(result.status, 'limited');
  assert.equal(result.hasFinalReply, true);
  const disabled = harness((_request, n) => ({tool_calls: [toolCall(n)]}));
  assert.equal((await runAgent(options({wrapUpIterations: 0}), disabled.rpc)).status, 'limited');
  assert.equal(disabled.calls.length, 10);
});

test('invalid reserves fail before discovery or any side effect', async () => {
  for (const value of [-1, 1.5, 10, true, null, '2']) {
    let called = false;
    await assert.rejects(runAgent(options({wrapUpIterations: value}), async () => {called = true;}), /wrapUpIterations/);
    assert.equal(called, false);
  }
});

test('a failed final durable acknowledgment cannot be reported as a delivered summary', async () => {
  const h = harness((_request, n) => n <= 8 ? {tool_calls: [toolCall(n)]} : {content: finalText});
  const rpc = async (method, payload) => {
    if (method === 'event' && payload.event.type === 'message_end' && payload.event.message.role === 'assistant'
        && payload.event.message.content.some(block => block.text === finalText)) throw new Error('final checkpoint failed');
    return h.rpc(method, payload);
  };
  await assert.rejects(runAgent(options(), rpc), /final checkpoint failed/);
  assert.equal(h.calls.length, 8);
});

function frame(delta, finish_reason = null) {
  return `data: ${JSON.stringify({id: 'test', object: 'chat.completion.chunk', model: 'test',
    choices: [{index: 0, delta, finish_reason}]})}\n\n`;
}

async function nativeFixture(t, handler) {
  const bodies = [], calls = [], preparations = [], events = [];
  const server = createServer(async (req, res) => {
    let data = ''; for await (const part of req) data += part;
    bodies.push(JSON.parse(data)); await handler(res, bodies.length);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => {server.closeAllConnections(); server.close();});
  return {bodies, calls, preparations, options: options({provider: {model: 'test', apiKey: 'local-only',
    baseUrl: `http://127.0.0.1:${server.address().port}/v1`, timeoutSeconds: 2, maxRetries: 0}}),
    rpc: async (method, payload) => {
      if (method === 'skills_loaded' || method === 'model_complete' || method === 'model_failed' || method === 'model_observation' || method === 'reject_output') return {};
      if (method === 'model_begin') return {request_id: `r-${bodies.length}`, debug: false};
      if (method === 'prepare') {preparations.push(payload); return {systemPrompt: 'Business guidance.', tools: [schema]};}
      if (method === 'tool') {calls.push(payload); return {content: [{type: 'text', text: 'saved'}]};}
      if (method === 'event') {events.push(payload.event); return {};}
      throw new Error(`Unexpected RPC ${method}`);
    }};
}

test('native provider receives no callable tools during wrap-up while retaining execution evidence', async t => {
  const f = await nativeFixture(t, async (res, n) => {
    res.writeHead(200, {'content-type': 'text/event-stream'});
    if (n <= 8) {res.write(frame({tool_calls: [{index: 0, ...toolCall(n)}]}));res.write(frame({}, 'tool_calls'));}
    else {res.write(frame({content: finalText}));res.write(frame({}, 'stop'));}
    res.end('data: [DONE]\n\n');
  });
  const result = await runAgent(f.options, f.rpc);
  assert.equal(result.status, 'limited'); assert.equal(result.hasFinalReply, true);
  assert.equal(f.bodies.length, 9);assert.equal(f.calls.length, 8);
  assert(f.bodies.slice(0, 8).every(body => body.tools?.some(tool => tool.function.name === 'act')));
  assert.deepEqual(f.bodies.at(-1).tools, f.bodies[0].tools);
  assert.equal(f.bodies.at(-1).tool_choice, 'none');
  assert.match(JSON.stringify(f.bodies.at(-1).messages.at(-1)), /wrap_up/);
  assert(f.bodies.every(body => body.messages[0].content === 'Business guidance.'));
  assert(!JSON.stringify(f.bodies[0].messages).includes('<execution_budget '));
  assert.equal((JSON.stringify(f.bodies.at(-1).messages).match(/<execution_budget /g) ?? []).length, 1);
  assert.equal(f.bodies.at(-1).messages.filter(m => m.role === 'tool').length, 8);
});

test('native provider repairs leaked protocol using Pi without replaying it or invoking tools', async t => {
  const f = await nativeFixture(t, async (res, n) => {
    res.writeHead(200, {'content-type': 'text/event-stream'});
    if (n <= 8) {res.write(frame({tool_calls: [{index: 0, ...toolCall(n)}]}));res.write(frame({}, 'tool_calls'));}
    else {res.write(frame({content: n === 9 ? dsml : finalText}));res.write(frame({}, 'stop'));}
    res.end('data: [DONE]\n\n');
  });
  const result = await runAgent(f.options, f.rpc);
  assert.equal(result.status, 'limited');
  assert.equal(result.hasFinalReply, true);
  assert.equal(f.bodies.length, 10);
  assert.equal(f.calls.length, 8);
  assert(f.bodies.slice(8).every(body => body.tool_choice === 'none' && JSON.stringify(body.tools) === JSON.stringify(f.bodies[0].tools)));
  assert(!JSON.stringify(f.bodies[9].messages).includes('DSML'));
});

test('a malformed reply with structured calls rejects the entire batch before side effects', async () => {
  const h = harness(() => ({content: dsml, tool_calls: [toolCall(1)]}));
  const result = await runAgent(options(), h.rpc);
  assert.equal(result.status, 'failed');
  assert.equal(result.outputError, 'invalid_model_output');
  assert.equal(h.calls.length, 0);
  assert.equal(h.requests.length, 1);
  assert(!h.events.some(e => e.type === 'tool_execution_start'));
});

test('cancellation interrupts a reserved native final response without another tool side effect', async t => {
  const controller = new AbortController();
  const f = await nativeFixture(t, async (res, n) => {
    res.writeHead(200, {'content-type': 'text/event-stream'});
    if (n <= 8) {res.write(frame({tool_calls: [{index: 0, ...toolCall(n)}]}));res.write(frame({}, 'tool_calls'));res.end('data: [DONE]\n\n');}
    else {setTimeout(() => controller.abort(), 20);res.write(': waiting\n\n');}
  });
  await assert.rejects(runAgent(f.options, f.rpc, controller.signal), /abort|interrupt/i);
  assert.equal(f.calls.length, 8);assert.equal(f.bodies.length, 9);
});

test('an oversized pending image reference cannot prevent a text-only reserved final reply', async () => {
  const resource = {id: 'f_pending', path: '/bot/.cota/context-images/session/pending.png', mimeType: 'image/png', size: 200 * 1024 * 1024};
  const h = harness((request, n) => n <= 8 ? {tool_calls: [toolCall(n)]} : {content: finalText});
  let imageFetches = 0;
  const rpc = async (method, payload) => {
    if (method === 'image_resource') {imageFetches++;throw new Error('No image fetch during wrap-up');}
    const result = await h.rpc(method, payload);
    if (method !== 'prepare' || payload.executionBudget?.phase !== 'wrap_up') return result;
    return {...result, imageResources: [resource], messages: result.messages.map(message => message.toolCallId === 'call-8'
      ? {...message, content: [{type: 'text', text: `Pending image resource ${resource.path}; contents not reviewed.`}],
        cotaImageRefs: [{index: 0, ...resource}]} : message)};
  };
  const result = await runAgent(options(), rpc);
  assert.equal(result.status, 'limited');assert.equal(result.hasFinalReply, true);
  assert.equal(imageFetches, 0);assert.equal(h.requests.length, 9);
  assert.equal(h.requests.at(-1).contextBudget.images, 0);
  assert.equal(h.requests.at(-1).contextBudget.usage_based_tokens, null);
  assert.match(JSON.stringify(h.requests.at(-1).messages), /contents not reviewed|no new visual review/i);
});
