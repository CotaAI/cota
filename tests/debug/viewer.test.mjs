import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {runInNewContext} from 'node:vm';
const source = await readFile(new URL('../../cota/debug/static/app.js', import.meta.url), 'utf8');
const markup = await readFile(new URL('../../cota/debug/static/index.html', import.meta.url), 'utf8');
const elementIds = new Set([...markup.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]));
const {hasModelDiagnostics, debugRequestURL, modelRequestSummary} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
test('model request summaries distinguish waiting time from actual provider token usage', () => {
  assert.match(modelRequestSummary({status: 'running', started_at: 10}, 95), /waiting for model.*85.0s/);
  const text = modelRequestSummary({status: 'completed', duration_ms: 3000,
    usage: {prompt_tokens: 40000, cached_tokens: 39000, completion_tokens: 100, reasoning_tokens: 80}});
  assert.match(text, /3.0s.*input 40000.*cache 39000.*output 100.*reasoning 80/);
  assert.match(modelRequestSummary({status: 'running', started_at: 10,
    transport: {attempts: [{number: 1}, {number: 2}]}}, 15), /HTTP attempt 2/);
});
test('service debug scopes reads without changing query pagination or session discovery', () => {
  const base = 'http://127.0.0.1:1234/token/';
  assert.equal(typeof debugRequestURL, 'function');
  const request = debugRequestURL('events?after=4&limit=100', base, 'partner:app/a?b');
  assert.equal(request.pathname, '/token/api/events');
  assert.equal(request.searchParams.get('after'), '4');
  assert.equal(request.searchParams.get('session_id'), 'partner:app/a?b');
  assert.equal(debugRequestURL('sessions?after=a', base, 'selected').searchParams.has('session_id'), false);
  assert.equal(debugRequestURL('info', base).searchParams.has('session_id'), false);
});
test('diagnostic availability notices apply to model carriers and tool output', () => {
  const event = (type, payload) => ({type, payload});
  assert.equal(hasModelDiagnostics(event('bot_utter', {llm:{request_id:'q'}})), true);
  assert.equal(hasModelDiagnostics(event('tool_started', {llm:{request_id:'q'}})), true);
  assert.equal(hasModelDiagnostics(event('tool_started', {llm_event_id:'owner'})), true);
  assert.equal(hasModelDiagnostics(event('bot_utter', {tool_event_id:'tool'})), true);
  assert.equal(hasModelDiagnostics(event('run_finished', {status:'failed'})), false);
  assert.equal(hasModelDiagnostics(event('bot_utter', {text:'manual'})), false);
  assert.equal(hasModelDiagnostics(event('bot_utter', {request_id:'unrelated'})), false);
  assert.equal(hasModelDiagnostics(event('user_utter', {llm:{request_id:'q'}})), false);
  assert.equal(hasModelDiagnostics(event('tool_started', {tool_call_id:'c'})), false);
});

// Exercise the real event handlers and request serialization without a browser.
// Only the initial boot calls are replaced so tests can control each poll.
function viewerHarness(script = source) {
  const nodes = new Map(), requests = [];
  const node = () => ({
    value: '', textContent: '', handlers: {}, children: [],
    classList: {add() {}, remove() {}, toggle() {}, contains() { return false; }},
    addEventListener(kind, handler) { this.handlers[kind] = handler; },
    setAttribute() {},
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
  });
  const document = {
    getElementById(id) {
      if (!elementIds.has(id)) return null;
      if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id);
    },
    querySelector: node, createElement: node, addEventListener() {},
  };
  const context = {
    document, URL, AbortController, location: {href: 'http://127.0.0.1/token/'},
    setTimeout() { return 1; }, clearTimeout() {},
    fetch(url) {
      return new Promise(resolve => requests.push({url, reply(data) {
        resolve({ok: true, json: async () => data});
      }}));
    },
  };
  const instrumented = script.replaceAll('export function ', 'function ').replace(
    "selectTab('events'); renderEvents(); poll();",
    'globalThis.viewer = {poll, initialize(id) { sessionsLoaded = true; resetSession(id); }, ' +
    'state() { return {selectedSession, cursor, ids: headers.map(row => row.event_id)}; }};',
  );
  runInNewContext(instrumented, context);
  context.viewer.initialize('A');
  const select = document.getElementById('session-select'); select.value = 'A';
  return {viewer: context.viewer, requests, changeSession(id) {
    select.value = id; select.handlers.change();
  }, click(id) { document.getElementById(id).handlers.click(); },
  text(id) { return document.getElementById(id).textContent; }, select};
}

const settle = () => new Promise(resolve => setImmediate(resolve));
const info = {bot: 'test', session_id: 'A', multi_session: true, metadata: {last_sequence: 1}};

test('poll renders against the current HTML without referencing removed sidebar fields', async () => {
  async function check(script) {
    const ui = viewerHarness(script);
    const poll = ui.viewer.poll();
    ui.requests[0].reply(info);
    await settle();
    ui.requests[1].reply({events: [], after_sequence: 0});
    await poll; await settle();
    assert.match(ui.text('connection'), /已连接/);
  }
  await check(source);
  const oldSidebar = source.replace("        $('cursor').textContent", "        $('store').textContent = 'removed';\n        $('cursor').textContent");
  assert.notEqual(oldSidebar, source);
  await assert.rejects(check(oldSidebar), {name: 'AssertionError'});
});

async function checkSessionSwitch(script) {
  const ui = viewerHarness(script);
  const poll = ui.viewer.poll();
  ui.changeSession('B');
  ui.click('tab-requests');
  ui.requests[0].reply(info);
  await settle();
  // An old poll may issue its events read before the queued detail request.
  if (ui.requests[1]?.url.pathname.endsWith('/events')) {
    ui.requests[1].reply({events: [], after_sequence: 0});
    await settle();
  }
  const request = ui.requests.find(row => row.url.pathname.endsWith('/model-debug'));
  assert.ok(request, 'the queued Model Requests action runs');
  request.reply({records: []});
  await poll; await settle();
  assert.equal(ui.viewer.state().selectedSession, 'B');
  assert.equal(ui.select.value, 'B');
  assert.equal(request.url.searchParams.get('session_id'), 'B');
}

async function checkStaleEvents(script) {
  const ui = viewerHarness(script);
  const poll = ui.viewer.poll();
  ui.requests[0].reply(info);
  await settle();
  assert.equal(ui.requests[1].url.searchParams.get('session_id'), 'A');
  ui.changeSession('B');
  ui.requests[1].reply({events: [{event_id: 'A-event', sequence: 17,
    type: 'user_utter', summary: {text: 'old session'}, timestamp: 0}], after_sequence: 17});
  await poll; await settle();
  assert.equal(ui.viewer.state().selectedSession, 'B');
  assert.equal(ui.viewer.state().cursor, 0);
  assert.equal(ui.viewer.state().ids.length, 0);
}

test('switching sessions during a blocked poll survives a subsequent detail action', async () => {
  await checkSessionSwitch(source);
});

test('an in-flight old-session event response cannot populate the new session', async () => {
  await checkStaleEvents(source);
});

test('session interaction regressions detect the previous queued-switch and unguarded-poll behavior', async () => {
  const queuedSwitch = source.replace('    resetSession(id);\n  });',
    '    exclusive(async () => resetSession(id));\n  });');
  assert.notEqual(queuedSwitch, source);
  await assert.rejects(checkSessionSwitch(queuedSwitch), {name: 'AssertionError'});
  const unguardedPoll = source.replaceAll('        if (version !== sessionVersion) return;\n', '');
  assert.notEqual(unguardedPoll, source);
  await assert.rejects(checkStaleEvents(unguardedPoll), {name: 'AssertionError'});
});
