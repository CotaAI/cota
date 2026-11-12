import assert from 'node:assert/strict';
import {test} from 'node:test';
import http from 'node:http';
import {EventEmitter, once} from 'node:events';
import {validateToolArguments} from '@earendil-works/pi-ai';
import {createWebFetchTool} from './web-fetch.mjs';

async function fixture(t, handler) {
  const server = http.createServer(handler);
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  t.after(() => { server.closeAllConnections(); server.close(); });
  const tool = createWebFetchTool({request: (url, options, callback) => http.request({
    ...options, hostname: '127.0.0.1', port: server.address().port,
    path: url.pathname + url.search,
  }, callback)});
  return tool;
}
const call = (tool, args, signal) => tool.execute('wf-test', {url: 'http://93.184.216.34/', ...args}, signal);

test('exposes native Pi schema validation', () => {
  const tool = createWebFetchTool();
  assert.equal(tool.name, 'web_fetch');
  assert.equal(typeof tool.label, 'string');
  assert.deepEqual(validateToolArguments(tool, {type: 'toolCall', id: 'x', name: tool.name,
    arguments: {url: 'https://example.com', headers: {Authorization: 'Bearer token'}}}),
  {url: 'https://example.com', headers: {Authorization: 'Bearer token'}});
  for (const args of [{}, {url: 'x', method: 'TRACE'}, {url: 'x', timeout_seconds: 0},
    {url: 'x', timeout_seconds: 61}, {url: 'x', headers: {x: {}}}]) {
    assert.throws(() => validateToolArguments(tool, {type: 'toolCall', id: 'x', name: tool.name, arguments: args}));
  }
});

test('fetches JSON and returns pretty-printed output', async t => {
  const tool = await fixture(t, async (req, res) => {
    let body = ''; for await (const chunk of req) body += chunk;
    res.writeHead(200, {'Content-Type': 'application/json'});
    res.end(JSON.stringify({method: req.method, body}));
  });
  const result = await call(tool, {method: 'POST', body: '{"hello":true}'});
  assert.equal(result.isError, false);
  assert.equal(result.details.status_code, 200);
  const parsed = JSON.parse(result.content[0].text);
  assert.equal(parsed.method, 'POST');
  assert.equal(parsed.body, '{"hello":true}');
});

test('extracts HTML into readable Markdown', async t => {
  const html = `<!DOCTYPE html><html><head><title>Test Page</title></head><body>
    <article><h1>Hello World</h1><p>This is a test paragraph with <strong>bold</strong> text.</p></article>
  </body></html>`;
  const tool = await fixture(t, (req, res) => {
    res.writeHead(200, {'Content-Type': 'text/html; charset=utf-8'});
    res.end(html);
  });
  const result = await call(tool, {});
  assert.equal(result.isError, false);
  assert.ok(result.content[0].text.includes('Hello World'));
  assert.ok(result.content[0].text.includes('**bold**'));
  assert.ok(!result.content[0].text.includes('<p>'));
});

test('passes through plain text responses', async t => {
  const tool = await fixture(t, (req, res) => {
    res.writeHead(200, {'Content-Type': 'text/plain'});
    res.end('Plain text content here');
  });
  const result = await call(tool, {});
  assert.equal(result.isError, false);
  assert.equal(result.content[0].text, 'Plain text content here');
});

test('returns non-success statuses as JSON errors', async t => {
  const tool = await fixture(t, (req, res) => { res.writeHead(503); res.end('Service Unavailable'); });
  const result = await call(tool, {});
  assert.equal(result.isError, true);
  assert.equal(result.details.status_code, 503);
  const error = JSON.parse(result.content[0].text);
  assert.equal(error.error, 'HTTP 503');
  assert.equal(error.body, 'Service Unavailable');
});

test('follows GET redirects up to 5 hops', async t => {
  let count = 0;
  const tool = await fixture(t, (req, res) => {
    count++;
    if (req.url === '/final') { res.writeHead(200, {'Content-Type': 'text/plain'}); res.end('arrived'); return; }
    res.writeHead(302, {location: count < 3 ? `/hop${count}` : '/final'});
    res.end();
  });
  const result = await call(tool, {url: 'http://93.184.216.34/start'});
  assert.equal(result.isError, false);
  assert.equal(result.content[0].text, 'arrived');
  assert.ok(result.details.url.endsWith('/final'));
});

test('returns redirect status for non-GET methods', async t => {
  const tool = await fixture(t, (req, res) => {
    res.writeHead(302, {location: '/target'});
    res.end('redirect body');
  });
  const result = await call(tool, {method: 'POST', body: '{}'});
  assert.equal(result.isError, true);
  assert.equal(result.details.status_code, 302);
});

test('rejects redirect to private IP', async t => {
  const tool = await fixture(t, (req, res) => {
    res.writeHead(302, {location: 'http://127.0.0.1/secret'});
    res.end();
  });
  const result = await call(tool, {});
  assert.equal(result.isError, true);
  assert.match(result.content[0].text, /Blocked|private/i);
});

test('fails on too many redirects', async t => {
  const tool = await fixture(t, (req, res) => {
    res.writeHead(302, {location: '/loop'});
    res.end();
  });
  const result = await call(tool, {});
  assert.equal(result.isError, true);
  assert.match(result.content[0].text, /redirect/i);
});

test('rejects private/reserved URL literals, credentials and localhost', async () => {
  let requests = 0;
  const tool = createWebFetchTool({request: () => { requests++; throw new Error('must not connect'); }});
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
    const tool = createWebFetchTool({lookup: (host, options, callback) => {
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
  const tool = createWebFetchTool({lookup: (host, options, callback) => {
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
  const tool = await fixture(t, (req, res) => res.end('x'.repeat(1024 * 1024 + 1)));
  const result = await call(tool, {});
  assert.equal(result.isError, true);
  assert.match(result.content[0].text, /size limit/i);
});

test('sanitizes network errors instead of reflecting request credentials', async () => {
  const tool = createWebFetchTool({request: () => { throw new Error('Authorization: Bearer secret-query-token'); }});
  const result = await call(tool, {url: 'https://example.com/?key=secret-query-token', headers: {Authorization: 'Bearer secret-query-token'}});
  assert.equal(result.isError, true);
  assert.ok(!JSON.stringify(result).includes('secret-query-token'));
});

test('uses a 30 second default and caps direct execution at 60 seconds', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const tool = createWebFetchTool({request: (url, {signal}) => {
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
  const tool = createWebFetchTool({lookup: () => assert.fail('literal must bypass DNS'), request: url => {
    destinations.push(url.hostname); throw new Error('test transport end');
  }});
  for (const url of ['http://192.0.5.1', 'https://[2606:4700:4700::1111]']) await call(tool, {url});
  assert.deepEqual(destinations, ['192.0.5.1', '[2606:4700:4700::1111]']);
});

test('auto-detects Content-Type for body when not provided', async t => {
  const tool = await fixture(t, async (req, res) => {
    res.writeHead(200, {'Content-Type': 'application/json'});
    res.end(JSON.stringify({ct: req.headers['content-type']}));
  });
  const result = await call(tool, {method: 'POST', body: '{"x":1}'});
  const parsed = JSON.parse(result.content[0].text);
  assert.equal(parsed.ct, 'application/json');
  const plain = await call(tool, {method: 'POST', body: 'not json'});
  const p2 = JSON.parse(plain.content[0].text);
  assert.equal(p2.ct, undefined);
});

test('truncates output exceeding the character limit', async t => {
  const tool = await fixture(t, (req, res) => {
    res.writeHead(200, {'Content-Type': 'text/plain'});
    res.end('x'.repeat(250_000));
  });
  const result = await call(tool, {});
  assert.equal(result.isError, false);
  assert.ok(result.content[0].text.length <= 200_001 + 20);
  assert.ok(result.content[0].text.endsWith('[Content truncated]'));
});

test('falls back to tag-stripped text when Readability extracts nothing', async t => {
  const html = '<html><body><div>Simple <b>content</b></div></body></html>';
  const tool = await fixture(t, (req, res) => {
    res.writeHead(200, {'Content-Type': 'text/html'});
    res.end(html);
  });
  const result = await call(tool, {});
  assert.equal(result.isError, false);
  assert.ok(result.content[0].text.includes('Simple'));
  assert.ok(result.content[0].text.includes('content'));
  assert.ok(!result.content[0].text.includes('<b>'));
});
