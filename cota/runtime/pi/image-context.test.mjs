import test from 'node:test';
import assert from 'node:assert/strict';
import {projectImageContext} from './image-context.mjs';

const image = value => ({type: 'image', mimeType: 'image/png', data: Buffer.from(value).toString('base64')});
const user = (id, content = 'continue') => ({role: 'user', content, cotaEventId: id, timestamp: 1});
const batch = (id, paths, values) => [
  {role: 'assistant', cotaEventId: `a-${id}`, content: paths.map((path, i) =>
    ({type: 'toolCall', id: `${id}-${i}`, name: 'read', arguments: {path}})), reasoningSignature: 'keep'},
  ...values.map((value, i) => ({role: 'toolResult', toolName: 'read', toolCallId: `${id}-${i}`,
    cotaEventId: `r-${id}-${i}`, cotaRunId: id, details: {original: true}, content: [image(value)]})),
];
const pixels = messages => messages.flatMap(m => Array.isArray(m.content) ? m.content.filter(b => b.type === 'image') : []);

test('older repeated pixels become explicit references while an intentional re-read stays visible', () => {
  const raw = [user('u'), ...batch('old', ['/book/page.png'], ['same']),
    {role: 'assistant', content: [{type: 'text', text: 'The red title is clipped.'}]},
    ...batch('now', ['/book/page.png'], ['same'])];
  const before = structuredClone(raw), projected = projectImageContext(raw);
  assert.equal(pixels(projected).length, 1);
  const reference = projected[2].content[0].text;
  assert.match(reference, /r-old-0/); assert.match(reference, /\/book\/page.png/); assert.match(reference, /sha256:/);
  assert.match(reference, /re-read/i); assert.match(reference, /not.*review|does not.*review/i);
  assert(projected.some(m => JSON.stringify(m.content).includes('The red title is clipped.')));
  assert.deepEqual(raw, before);
  assert.deepEqual(projected[2].details, raw[2].details);
  assert.equal(projected[1].reasoningSignature, 'keep');
  assert.equal(projected[2].toolCallId, 'old-0');
});

test('different versions at the same resource have different hashes and a current two-image batch survives', () => {
  const projected = projectImageContext([user('u'), ...batch('old', ['/book/page.png'], ['old']),
    ...batch('now', ['/book/page.png', '/book/other.png'], ['new', 'other'])]);
  assert.equal(pixels(projected).length, 2);
  const oldHash = projected[2].content[0].text.match(/sha256:[a-f0-9]+/)[0];
  const newHash = projected[4].content[0].text.match(/sha256:[a-f0-9]+/)[0];
  assert.notEqual(oldHash, newHash);
});

test('duplicate bytes within a current batch appear once with provenance on the duplicate', () => {
  const projected = projectImageContext([user('u'), ...batch('now', ['/a.png', '/b.png'], ['same', 'same'])]);
  assert.equal(pixels(projected).length, 1);
  assert.match(projected[3].content[0].text, /\/b.png/);
  assert.match(projected[3].content[0].text, /duplicate/i);
});

test('new user images remain visible and old user images are references after restart', () => {
  const raw = [user('old', [image('old')]), {role: 'assistant', content: [{type: 'text', text: 'Saw a blue bird.'}]},
    user('new', [image('new')])];
  const projected = projectImageContext(JSON.parse(JSON.stringify(raw)));
  assert.equal(pixels(projected).length, 1);
  assert.equal(pixels(projected)[0].data, image('new').data);
  assert.match(projected[0].content[0].text, /old/);
  assert.deepEqual(projected[1], raw[1]);
});

test('an answered tool batch is not sent again to a subsequent textual user request', () => {
  const projected = projectImageContext([user('u'), ...batch('old', ['/a.png'], ['old']),
    {role: 'assistant', content: [{type: 'text', text: 'The image has a blue border.'}]}, user('new')]);
  assert.equal(pixels(projected).length, 0);
  assert.match(projected[2].content[0].text, /\/a.png/);
});
