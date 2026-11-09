import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source = await readFile(new URL('../../cota/debug/static/app.js', import.meta.url), 'utf8');
const {hasModelDiagnostics} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
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
