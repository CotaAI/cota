import assert from 'node:assert/strict';
import {test} from 'node:test';
import http from 'node:http';
import {EventEmitter, once} from 'node:events';
import {validateToolArguments} from '@earendil-works/pi-ai';
import {createHttpTool} from './http.mjs';

async function fixture(t, handler) {
  const server = http.createServer(handler);
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  t.after(() => { server.closeAllConnections(); server.close(); });
  // Explicit test-only transport: keep the real ClientRequest/response behavior,
  // but connect to this fixture instead of the validated public destination.
  const tool = createHttpTool({request: (url, options, callback) => http.request({
    ...options, hostname: '127.0.0.1', port: server.address().port,
    path: url.pathname + url.search,
  }, callback)});
  return tool;
}
const call = (tool, args, signal) => tool.execute('http-test', {url: 'http://93.184.216.34/', ...args}, signal);

test('exposes native Pi schema validation', () => {
  const tool = createHttpTool();
  assert.equal(tool.name, 'http_request');
  assert.equal(typeof tool.label, 'string');
  assert.deepEqual(validateToolArguments(tool, {type: 'toolCall', id: 'x', name: tool.name,
    arguments: {url: 'https://example.com', headers: {Authorization: 'Bearer token'}}}),
  {url: 'https://example.com', headers: {Authorization: 'Bearer token'}});
  for (const args of [{}, {url: 'x', method: 'TRACE'}, {url: 'x', timeout_seconds: 0},
    {url: 'x', timeout_seconds: 61}, {url: 'x', headers: {x: {}}}]) {
    assert.throws(() => validateToolArguments(tool, {type: 'toolCall', id: 'x', name: tool.name, arguments: args}));
  }
});

test('performs an async request and returns Pi content, details and HTTP result', async t => {
  const tool = await fixture(t, async (req, res) => {
    let body = ''; for await (const chunk of req) body += chunk;
    res.end(JSON.stringify({method: req.method, type: req.headers['content-type'], body}));
  });
  const result = await call(tool, {method: 'POST', body: '{"hello":true}'});
  assert.equal(result.isError, false);
  assert.equal(result.details.status_code, 200);
  assert.deepEqual(JSON.parse(JSON.parse(result.content[0].text).body), {method: 'POST', type: 'application/json', body: '{"hello":true}'});
  assert.equal(result.content[0].type, 'text');
  assert.equal(result.details.body, undefined);
  assert.equal(result.structuredContent, undefined);
  const explicit = await call(tool, {body: '{}', headers: {'content-type': 'text/plain'}});
  assert.equal(JSON.parse(JSON.parse(explicit.content[0].text).body).type, 'text/plain');
});

test('returns non-success and redirect statuses without following redirects', async t => {
  let count = 0;
  const tool = await fixture(t, (req, res) => { count++; res.writeHead(req.url === '/bad' ? 503 : 302, {location: '/target'}); res.end('failed'); });
  for (const [path, status] of [['/bad', 503], ['/', 302]]) {
    const result = await call(tool, {url: `http://93.184.216.34${path}`});
    assert.equal(result.isError, true);
    assert.equal(result.details.status_code, status);
    assert.equal(JSON.parse(result.content[0].text).body, 'failed');
  }
  assert.equal(count, 2);
});

test('rejects private/reserved URL literals, legacy IPv4, credentials and localhost', async () => {
  let requests = 0;
  const tool = createHttpTool({request: () => { requests++; throw new Error('must not connect'); }});
  for (const url of ['ftp://example.com', 'http://user:secret@example.com', 'http://@example.com', 'http://localhost.',
    'http://a.localhost', 'http://127.1', 'http://2130706433', 'http://0x7f000001',
    'http://10.0.0.1', 'http://100.64.0.1', 'http://169.254.169.254', 'http://172.31.0.1',
    'http://192.168.0.1', 'http://192.0.2.1', 'http://198.18.0.1', 'http://224.0.0.1',
    'http://240.0.0.1', 'http://[::1]', 'http://[::ffff:127.0.0.1]', 'http://[::ffff:8.8.8.8]',
    'http://[fc00::1]', 'http://[fe80::1]', 'http://[ff02::1]', 'http://[2001:db8::1]',
    'http://[2002:7f00:1::]', 'http://[3fff::1]']) {
    const result = await call(tool, {url});
    assert.equal(result.isError, true, url);
    assert.ok(!JSON.stringify(result).includes('secret'));
  }
  assert.equal(requests, 0);
});

test('checks all actual DNS results and fails closed on private or empty answers', async () => {
  for (const answers of [[{address: '127.0.0.1', family: 4}],
    [{address: '8.8.8.8', family: 4}, {address: '::1', family: 6}], []]) {
    let lookups = 0;
    const tool = createHttpTool({lookup: (host, options, callback) => {
      lookups++; assert.equal(host, 'api.example'); assert.equal(options.all, true);
      callback(null, answers);
    }});
    const result = await call(tool, {url: 'http://api.example'});
    assert.equal(result.isError, true);
    assert.equal(lookups, 1);
    assert.match(result.content[0].text, /Blocked|DNS/);
  }
});

test('pins a checked DNS answer in the native request lookup callback', async t => {
  let lookups = 0;
  const tool = createHttpTool({lookup: (host, options, callback) => {
    lookups++; callback(null, [{address: '8.8.8.8', family: 4}, {address: '2606:4700:4700::1111', family: 6}]);
  }, request: (url, options) => {
    options.lookup(url.hostname, {all: true}, (err, answers) => {
      assert.ifError(err); assert.deepEqual(answers, [{address: '8.8.8.8', family: 4}, {address: '2606:4700:4700::1111', family: 6}]);
    });
    throw new Error('intentional transport end');
  }});
  await call(tool, {url: 'https://api.example'});
  assert.equal(lookups, 1);
});

test('times out a stalled request and cancels a running request', async t => {
  const tool = await fixture(t, () => {});
  const result = await call(tool, {timeout_seconds: 1});
  assert.equal(result.isError, true);
  assert.match(result.content[0].text, /timed out/i);
  const controller = new AbortController();
  const pending = call(tool, {}, controller.signal);
  setTimeout(() => controller.abort(), 20);
  await assert.rejects(pending, {name: 'AbortError'});
  await assert.rejects(call(tool, {}, controller.signal), {name: 'AbortError'});
});

test('bounds streamed response bytes and destroys oversized response', async t => {
  const tool = await fixture(t, (req, res) => res.end('x'.repeat(256 * 1024 + 1)));
  const result = await call(tool, {});
  assert.equal(result.isError, true);
  assert.match(result.content[0].text, /response.*limit/i);
  assert.ok(JSON.stringify(result).length < 1000);
});

test('sanitizes network errors instead of reflecting request credentials', async () => {
  const tool = createHttpTool({request: () => { throw new Error('Authorization: Bearer secret-query-token'); }});
  const result = await call(tool, {url: 'https://example.com/?key=secret-query-token', headers: {Authorization: 'Bearer secret-query-token'}});
  assert.equal(result.isError, true);
  assert.ok(!JSON.stringify(result).includes('secret-query-token'));
});

test('uses a 30 second default and caps direct execution at 60 seconds', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const tool = createHttpTool({request: (url, {signal}) => {
    const req = new EventEmitter();
    req.end = () => {};
    signal.addEventListener('abort', () => req.emit('error', new Error('aborted')), {once: true});
    return req;
  }});
  for (const [args, milliseconds] of [[{}, 30000], [{timeout_seconds: 600}, 60000]]) {
    let completed = false;
    const pending = call(tool, args).then(value => { completed = true; return value; });
    t.mock.timers.tick(milliseconds - 1);
    await Promise.resolve();
    assert.equal(completed, false);
    t.mock.timers.tick(1);
    assert.match((await pending).content[0].text, /timed out/);
  }
});

test('accepts ordinary public IPv4 and IPv6 literals without a DNS lookup', async () => {
  const destinations = [];
  const tool = createHttpTool({lookup: () => assert.fail('literal must bypass DNS'), request: url => {
    destinations.push(url.hostname); throw new Error('test transport end');
  }});
  for (const url of ['http://192.0.5.1', 'https://[2606:4700:4700::1111]']) await call(tool, {url});
  assert.deepEqual(destinations, ['192.0.5.1', '[2606:4700:4700::1111]']);
});


test('returns only useful response headers without automatically retrying a write', async t => {
  let calls = 0;
  const tool = await fixture(t, (req, res) => {
    calls++;
    res.writeHead(429, {'Content-Type': 'application/json', 'Retry-After': '60',
      'Set-Cookie': 'session=private', 'X-Internal-Token': 'private'});
    res.end('{"error":"limited"}');
  });
  const result = await call(tool, {method: 'POST', body: '{}'});
  const expected = {'content-type': 'application/json', 'retry-after': '60'};
  assert.deepEqual(result.details.headers, expected);
  assert.deepEqual(JSON.parse(result.content[0].text).headers, expected);
  assert.equal(result.isError, true);
  assert.equal(calls, 1);
  assert.ok(!JSON.stringify(result).includes('private'));
});
