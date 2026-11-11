import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {createNativeTools} from './tools.mjs';

const original = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aH1sAAAAASUVORK5CYII=', 'base64');
const id = `sha256:${createHash('sha256').update(original).digest('hex')}`;
const resource = {id, path: `/bot/.cota/context-images/session/${id.slice(7)}.png`, mimeType: 'image/png', size: original.length};

test('service without Skills reads only registered immutable image paths through the official reader', async () => {
  const calls = [];
  const native = await createNativeTools({imageResources: [resource]}, {skills: []}, async (method, payload) => {
    calls.push({method, payload});
    if (method === 'image_resource') return {type: 'image', mimeType: 'image/png', data: original.toString('base64')};
    if (method === 'tool_result') return {};
    throw new Error('unexpected RPC');
  });
  const reader = native.tools.find(tool => tool.name === 'read');
  assert(reader, 'initial image catalog enables service read without Skills');
  assert.deepEqual(reader.parameters.properties.path, (await import('@earendil-works/pi-coding-agent')).createReadToolDefinition(process.cwd()).parameters.properties.path);
  const result = await reader.execute('old-version', {path: resource.path});
  assert.equal(result.content.find(block => block.type === 'image').data, original.toString('base64'));
  assert.equal(result.isError, false);
  assert.deepEqual(calls.filter(call => call.method === 'image_resource'), [{method: 'image_resource', payload: {id}}]);
  const denied = await reader.execute('unknown-version', {path: '/bot/.cota/context-images/session/unknown.png'});
  assert.equal(denied.isError, true); assert.match(JSON.stringify(denied.content), /unknown.*resource/i);
  assert.equal(calls.filter(call => call.method === 'image_resource').length, 1);
  const filesystem = await reader.execute('no-host-grant', {path: '/etc/passwd'});
  assert.equal(filesystem.isError, true);
});

test('immutable resource reread ignores overwritten workspace files and catalog updates remain scoped', async t => {
  const {mkdtemp, writeFile, rm} = await import('node:fs/promises');
  const {tmpdir} = await import('node:os'); const {join} = await import('node:path');
  const cwd = await mkdtemp(join(tmpdir(), 'cota-resource-read-')); t.after(() => rm(cwd, {recursive: true, force: true}));
  await writeFile(join(cwd, 'page.png'), original);
  const native = await createNativeTools({cwd, imageResources: [resource]}, {skills: []}, async method =>
    method === 'image_resource' ? {type: 'image', mimeType: 'image/png', data: original.toString('base64')} : {});
  await writeFile(join(cwd, 'page.png'), 'overwritten new version');
  const result = await native.tools.find(tool => tool.name === 'read').execute('reread', {path: resource.path});
  assert.equal(result.content.find(block => block.type === 'image').data, original.toString('base64'));
  assert.throws(() => native.imageResources.register([{...resource, size: resource.size + 1}]), /immutable/i);
});

for (const native of [true, false]) test(`lean referenced history reaches ${native ? 'native provider' : 'fallback bridge'} with only current pixels`, async t => {
  const {runAgent} = await import('./engine.mjs');
  const {createServer} = await import('node:http');
  const wire = [], rpcCalls = [];
  const server = createServer(async (req, res) => {
    let body = ''; for await (const part of req) body += part; wire.push(JSON.parse(body));
    res.writeHead(200, {'content-type': 'text/event-stream'});
    res.end(`data: ${JSON.stringify({id: 'test', object: 'chat.completion.chunk', model: 'test', choices: [{index: 0, delta: {content: 'done'}, finish_reason: 'stop'}]})}\n\ndata: [DONE]\n\n`);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => {server.closeAllConnections(); server.close();});
  const catalog = [], messages = [{role: 'user', content: 'old task', cotaEventId: 'old-user'}];
  for (let i = 0; i < 20; i++) {
    const old = {id: `sha256:${i.toString(16).padStart(64, '0')}`, path: `/bot/.cota/context-images/session/old-${i}.png`, mimeType: 'image/png', size: 10 * 1024 * 1024};
    catalog.push(old);
    messages.push({role: 'assistant', cotaEventId: `call-${i}`, content: [{type: 'toolCall', id: `old-${i}`, name: 'read', arguments: {path: old.path}}]},
      {role: 'toolResult', cotaEventId: `result-${i}`, toolCallId: `old-${i}`, toolName: 'read', content: [{type: 'text', text: `Image resource ${JSON.stringify(old)}. Pixels omitted; use read to inspect exact version. Not review/approval.`}], cotaImageRefs: [{index: 0, ...old}]});
  }
  messages.push({role: 'user', cotaEventId: 'new-user', content: 'Review the current image.'},
    {role: 'assistant', cotaEventId: 'current-call', content: [{type: 'toolCall', id: 'current', name: 'read', arguments: {path: resource.path}}], reasoningSignature: 'preserve'},
    {role: 'toolResult', cotaEventId: 'current-result', toolCallId: 'current', toolName: 'read', details: {preserve: true},
      content: [{type: 'text', text: 'Current image pixels omitted; read exact resource.'}], cotaImageRefs: [{index: 0, ...resource}]});
  const before = structuredClone(messages);
  const options = {messages, imageResources: catalog, maxIterations: 2,
    ...(native ? {provider: {model: 'test', apiKey: 'test', baseUrl: `http://127.0.0.1:${server.address().port}/v1`, timeoutSeconds: 2, maxRetries: 0, vision: true}} : {})};
  const result = await runAgent(options, async (method, payload) => {
    rpcCalls.push({method, payload});
    if (method === 'skills_loaded' || method === 'event' || method === 'model_complete' || method === 'model_observation') return {};
    if (method === 'prepare') {
      assert.equal(payload.messages, undefined, 'canonical Cota history never crosses prepare');
      return {systemPrompt: 'policy', messages, tools: payload.nativeTools, imageResources: [resource]};
    }
    if (method === 'image_resource') {assert.equal(payload.id, id); return {type: 'image', mimeType: 'image/png', data: original.toString('base64')};}
    if (method === 'model_begin') return {request_id: 'test', debug: false};
    if (method === 'model') {wire.push(payload); return {content: 'done'};}
    throw new Error(`unexpected ${method}`);
  });
  assert.equal(rpcCalls.filter(call => call.method === 'image_resource').length, 1);
  const request = wire[0];
  const images = request.messages.flatMap(message => Array.isArray(message.content) ? message.content.filter(block => block.type === (native ? 'image_url' : 'image')) : []);
  assert.equal(images.length, 1);
  assert(JSON.stringify(request).length < 30000);
  assert(JSON.stringify(request).includes('old-0.png'));
  assert.deepEqual(messages, before);
  assert(result.messages.some(message => message.cotaEventId === 'current-result' && message.cotaImageRefs));
});

test('compaction keeps lean references, registers its catalog and permits a lazy exact-version read', async () => {
  const {runAgent} = await import('./engine.mjs');
  const later = {...resource, id: 'f_historical', path: '/bot/.cota/context-images/session/historical.png'};
  const old = {...resource, id: 'f_summary_old', path: '/bot/.cota/context-images/session/old.png'};
  const pending = {role: 'toolResult', cotaEventId: 'current-result', toolCallId: 'current', toolName: 'read',
    content: [{type: 'text', text: `Image resource ${JSON.stringify(resource)}; pixels omitted; use read for exact version.`}],
    cotaImageRefs: [{index: 0, ...resource}]};
  const call = {role: 'assistant', cotaEventId: 'current-call', content: [{type: 'toolCall', id: 'current', name: 'read', arguments: {path: resource.path}}]};
  let history = [{role: 'user', content: 'task', cotaEventId: 'user'},
    {role: 'assistant', cotaEventId: 'long-call', content: [{type: 'toolCall', id: 'long', name: 'act', arguments: {}}]},
    {role: 'toolResult', toolCallId: 'long', toolName: 'act', cotaEventId: 'long-result', content: [
      {type: 'text', text: 'details '.repeat(6000)}, {type: 'text', text: `Image resource ${JSON.stringify(old)}; pixels omitted; use read for exact version.`}],
      cotaImageRefs: [{index: 1, ...old}]},
    call, pending];
  const methods = [], modelRequests = [], fetched = [];
  const result = await runAgent({messages: history, imageResources: [resource, old], maxIterations: 3,
    model: {contextWindow: 8000, maxTokens: 500}, compaction: {reserve_tokens: 1000, keep_recent_tokens: 100}}, async (method, payload) => {
    methods.push(method);
    if (method === 'prepare') {assert.equal(payload.messages, undefined); return {messages: history, tools: payload.nativeTools};}
    if (method === 'skills_loaded' || method === 'tool_result') return {};
    if (method === 'image_resource') {fetched.push(payload.id); return {type: 'image', mimeType: 'image/png', data: original.toString('base64')};}
    if (method === 'summarize') {
      assert(!JSON.stringify(payload).includes(original.toString('base64')));
      assert(JSON.stringify(payload).includes(old.path)); assert(JSON.stringify(payload).includes(old.id));
      return {content: 'summary retains image paths'};
    }
    if (method === 'compact') {
      history = [{role: 'user', cotaEventId: 'summary', cotaCompaction: true, content: payload.summary}, call, pending];
      assert(!JSON.stringify(history).includes(original.toString('base64')));
      return {messages: history, imageResources: [later]};
    }
    if (method === 'authorize_tool') return {allowed: true};
    if (method === 'event') {
      if (payload.event.type === 'message_end' && payload.event.message.role !== 'system') history.push(payload.event.message);
      return {};
    }
    if (method === 'model') {
      modelRequests.push(payload);
      return modelRequests.length === 1 ? {tool_calls: [{id: 'lazy', type: 'function', function: {name: 'read', arguments: JSON.stringify({path: later.path})}}]} : {content: 'done'};
    }
    throw new Error(`unexpected ${method}`);
  });
  assert.equal(result.status, 'completed');
  assert.equal(methods.filter(method => method === 'compact').length, 1);
  assert.deepEqual(fetched, [resource.id, later.id]);
  assert.equal(modelRequests.length, 2);
  assert(modelRequests[1].messages.some(message => message.toolCallId === 'lazy' && message.content.some(block => block.type === 'image')));
});
