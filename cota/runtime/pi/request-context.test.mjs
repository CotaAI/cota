import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {runAgent} from './engine.mjs';

for (const native of [false, true]) test(`runtime guidance is request-local with stable system/tools (${native ? 'native' : 'adapter'})`, async t => {
  const initial = {role: 'user', content: 'Original task', timestamp: 1, cotaEventId: 'u'};
  const history = [structuredClone(initial)], requests = [], events = [], preparations = [];
  const schema = {type: 'function', function: {name: 'act', description: 'act', parameters: {type: 'object', properties: {}}}};
  const response = n => n === 1 ? {tool_calls: [{id: 'call', type: 'function', function: {name: 'act', arguments: '{}'}}]} : {content: 'done'};
  const server = createServer(async (req, res) => {
    let data = ''; for await (const b of req) data += b;
    requests.push(JSON.parse(data));
    const r = response(requests.length);
    const delta = {role: 'assistant', content: r.content ?? '', ...(r.tool_calls ? {tool_calls: r.tool_calls.map((c, i) => ({index: i, ...c}))} : {})};
    res.writeHead(200, {'content-type': 'text/event-stream'});
    res.end('data: ' + JSON.stringify({choices: [{index: 0, delta, finish_reason: r.tool_calls ? 'tool_calls' : 'stop'}]}) + '\n\ndata: [DONE]\n\n');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => {server.closeAllConnections(); server.close();});
  const options = {messages: [initial], maxIterations: 3,
    ...(native ? {provider: {model: 'test', apiKey: 'local', baseUrl: `http://127.0.0.1:${server.address().port}/v1`, timeoutSeconds: 5, maxRetries: 0}} : {})};
  const result = await runAgent(options, async (method, p) => {
    if (method === 'prepare') {preparations.push(p); return {messages: history, systemPrompt: 'Stable base', runtimeContext: `CURRENT_GUIDANCE_${preparations.length}`, tools: [schema]};}
    if (method === 'skills_loaded' || method === 'model_observation' || method === 'model_complete') return {};
    if (method === 'model_begin') return {request_id: `r-${requests.length}`, debug: false};
    if (method === 'event') {events.push(structuredClone(p.event)); if (p.event.type === 'message_end') history.push(p.event.message); return {};}
    if (method === 'model') {requests.push(p); return response(requests.length);}
    if (method === 'tool') return {content: [{type: 'text', text: 'actual result'}]};
    throw new Error(`Unexpected ${method}`);
  });
  assert.equal(result.status, 'completed');
  assert.equal(requests.length, 2);
  for (let i = 0; i < 2; i++) {
    const messages = requests[i].messages;
    assert.equal(messages[0].content, 'Stable base');
    assert.equal(messages.at(-1).role, 'user');
    assert.match(JSON.stringify(messages.at(-1).content), new RegExp(`CURRENT_GUIDANCE_${i + 1}`));
    assert.equal(messages.filter(m => JSON.stringify(m.content).includes('CURRENT_GUIDANCE_')).length, 1);
  }
  assert.deepEqual(requests[0].tools, requests[1].tools);
  assert(!JSON.stringify(requests[1].messages).includes('CURRENT_GUIDANCE_1'));
  assert(!JSON.stringify(result.messages).includes('CURRENT_GUIDANCE_'));
  assert(!JSON.stringify(events).includes('CURRENT_GUIDANCE_'));
  assert.deepEqual(initial, {role: 'user', content: 'Original task', timestamp: 1, cotaEventId: 'u'});
});

test('request-only guidance is budgeted before any model call or compaction', async () => {
  const methods = [];
  await assert.rejects(runAgent({messages: [{role: 'user', content: 'task', cotaEventId: 'u'}],
    maxIterations: 1, model: {contextWindow: 8000, maxTokens: 500},
    compaction: {reserve_tokens: 1000, keep_recent_tokens: 1000}}, async (method, payload) => {
    methods.push(method);
    if (method === 'skills_loaded') return {};
    if (method === 'prepare') return {messages: [{role: 'user', content: 'task', cotaEventId: 'u'}],
      systemPrompt: 'stable', runtimeContext: 'context '.repeat(10000), tools: []};
    throw new Error(`No provider or summary should be called: ${method}`);
  }), /exceed.*budget/);
  assert.deepEqual(methods, ['skills_loaded', 'prepare']);
});

test('Pi compacts durable facts without summarizing or persisting ephemeral guidance', async () => {
  const call = id => ({role: 'assistant', cotaEventId: id, timestamp: 1,
    content: [{type: 'toolCall', id, name: 'act', arguments: {}}]});
  const result = (id, text) => ({role: 'toolResult', cotaEventId: id + '-result', timestamp: 1,
    toolName: 'act', toolCallId: id, content: [{type: 'text', text}]});
  let history = [{role: 'user', cotaEventId: 'u', content: 'task', timestamp: 1},
    call('old'), result('old', 'long fact '.repeat(6000)), call('recent'), result('recent', 'latest evidence')];
  let summarized = 0, committed = 0;
  const outcome = await runAgent({messages: structuredClone(history), maxIterations: 1,
    model: {contextWindow: 8000, maxTokens: 500},
    compaction: {reserve_tokens: 1000, keep_recent_tokens: 1000}}, async (method, payload) => {
    if (method === 'skills_loaded' || method === 'event') return {};
    if (method === 'prepare') return {messages: history, systemPrompt: 'stable', runtimeContext: 'EPHEMERAL_RULE', tools: []};
    if (method === 'summarize') {
      summarized++;
      assert(!JSON.stringify(payload).includes('EPHEMERAL_RULE'));
      return {content: 'task and older facts'};
    }
    if (method === 'compact') {
      committed++;
      assert.deepEqual(payload.replaced_message_ids, ['u', 'old', 'old-result']);
      assert(!JSON.stringify(payload).includes('EPHEMERAL_RULE'));
      history = [{role: 'user', cotaEventId: 'summary', cotaCompaction: true, content: payload.summary, timestamp: 2},
        ...history.slice(-2)];
      return {messages: history};
    }
    if (method === 'model') {
      assert.match(JSON.stringify(payload.messages.at(-1)), /EPHEMERAL_RULE/);
      return {content: 'done'};
    }
    throw new Error(`Unexpected ${method}`);
  });
  assert.equal(summarized, 1); assert.equal(committed, 1);
  assert.equal(outcome.status, 'completed');
  assert(!JSON.stringify(outcome.messages).includes('EPHEMERAL_RULE'));
});

test('a large model compacts at its working threshold before sending the next request', async () => {
  const old = {role: 'user', content: 'older '.repeat(3000), cotaEventId: 'old', timestamp: 1};
  const latest = {role: 'user', content: 'continue', cotaEventId: 'latest', timestamp: 2};
  let history = [old, {role: 'assistant', content: [{type:'text',text:'saved'}], cotaEventId:'old-a',timestamp:1}, latest], compactions = 0;
  await runAgent({messages: history, maxIterations: 1, model: {contextWindow: 1000000, maxTokens: 500},
    compaction: {trigger_tokens: 3000, keep_recent_tokens: 500}}, async (method, p) => {
    if (method === 'skills_loaded' || method === 'event') return {};
    if (method === 'prepare') return {messages: history, systemPrompt: 'fixed', tools: []};
    if (method === 'summarize') return {content: 'older facts'};
    if (method === 'compact') {
      compactions++;
      assert.equal(p.reason, 'threshold');
      history = [{role: 'user', content: p.summary, cotaEventId: 'summary', cotaCompaction: true, timestamp: 3}, latest];
      return {messages: history};
    }
    if (method === 'model') {
      assert.equal(compactions, 1);
      assert.equal(p.contextBudget.context_window, 1000000);
      assert.equal(p.contextBudget.trigger_tokens, 3000);
      assert(p.contextBudget.budget_tokens < 3000);
      assert(!JSON.stringify(p.messages).includes(old.content));
      return {content: 'done'};
    }
    throw new Error(`Unexpected ${method}`);
  });
  assert.equal(compactions, 1);
});
