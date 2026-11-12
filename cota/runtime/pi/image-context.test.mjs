import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {projectImageContext, createImageResources, hydrateImageRefs} from './image-context.mjs';

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

const descriptor = (value, id) => {
  const bytes = Buffer.from(value), hash = `sha256:${createHash('sha256').update(bytes).digest('hex')}`;
  return {id: id ?? hash, path: `/bot/.cota/context-images/session/${(id ?? hash).replace(':', '-')}.png`, mimeType: 'image/png', size: bytes.length};
};

const referenced = (id, resource, role = 'user') => ({role, cotaEventId: id, timestamp: 1,
  content: [{type: 'text', text: `Image resource ${JSON.stringify(resource)}. Pixels omitted; use read to inspect exact version. Not review/approval.`}],
  cotaImageRefs: [{index: 0, ...resource}]});
const limits = {maxImages: 2, maxImageBytes: 1000, maxRequestBytes: 10000};

test('resource references hydrate only current input and reuse exact validated bytes', async () => {
  const old = descriptor('old'), current = descriptor('current'), calls = [];
  const resources = createImageResources([old, current], async (method, payload) => {
    calls.push({method, payload}); return image('current');
  });
  const messages = [referenced('old-user', old), {role: 'assistant', content: [{type: 'text', text: 'Blue border recorded.'}]}, referenced('new-user', current)];
  const before = structuredClone(messages);
  const hydrated = await hydrateImageRefs(messages, resources, limits);
  assert.equal(pixels(hydrated).length, 1);
  assert.equal(hydrated[2].content[0].data, image('current').data);
  assert.equal(JSON.stringify(hydrated[2].content).includes('Pixels omitted'), false);
  assert.equal(hydrated[0].content[0].text, messages[0].content[0].text);
  await hydrateImageRefs(messages, resources, limits);
  assert.deepEqual(calls, [{method: 'image_resource', payload: {id: current.id}}]);
  assert.deepEqual(messages, before);
});

test('pending referenced comparison batch survives with protocol metadata and deduplicates fetches', async () => {
  const a = descriptor('A'), b = descriptor('B'), calls = [];
  const resources = createImageResources([a, b], async (_method, {id}) => {calls.push(id); return image(id === a.id ? 'A' : 'B');});
  const messages = [user('u'), {role: 'assistant', content: [{type: 'toolCall', id: 'a', name: 'read', arguments: {path: a.path}},
    {type: 'toolCall', id: 'b', name: 'read', arguments: {path: b.path}}], thinkingSignature: 'preserve'},
    {...referenced('ra', a, 'toolResult'), toolCallId: 'a', details: {keep: true}},
    {...referenced('rb', b, 'toolResult'), toolCallId: 'b'}, {...referenced('rc', a, 'toolResult'), toolCallId: 'a'}];
  const result = projectImageContext(await hydrateImageRefs(messages, resources, limits));
  assert.equal(pixels(result).length, 2); assert.equal(calls.length, 2);
  assert.equal(result[1].thinkingSignature, 'preserve'); assert.deepEqual(result[2].details, {keep: true});
  assert.equal(result[3].toolCallId, 'b');
});

test('known active resource sizes fail before any image fetch and auto=false remains a reference', async () => {
  const a = descriptor('too large'), calls = [];
  const resources = createImageResources([a], async () => {calls.push('fetch'); return image('too large');});
  await assert.rejects(hydrateImageRefs([referenced('u', a)], resources, {...limits, maxImageBytes: 1}), /image.*budget/i);
  assert.equal(calls.length, 0);
  const disabled = referenced('u', a); disabled.cotaImageRefs[0].auto = false;
  assert.equal(pixels(await hydrateImageRefs([disabled], resources, limits)).length, 0);
  assert.equal(calls.length, 0);
});

test('resource loader rejects changed size, MIME, hash and unregistered IDs', async () => {
  const a = descriptor('original');
  for (const block of [image('different'), {...image('original'), mimeType: 'image/jpeg'}, {...image('changed!')}]) {
    const resources = createImageResources([a], async () => block);
    await assert.rejects(resources.load(a.id), /size|mime|hash/i);
  }
  const resources = createImageResources([a], async () => {throw new Error('must not fetch');});
  await assert.rejects(resources.load('unknown'), /unknown|registered/i);
});

test('unavailable automatic image is truthful text while explicit read still fails', async () => {
  const resource = descriptor('gone', 'f_missing');
  const resources = createImageResources([resource], async () => ({error: 'Image resource unavailable; contents not reviewed'}));
  const result = await hydrateImageRefs([referenced('u', resource)], resources, limits);
  assert.equal(pixels(result).length, 0);
  assert.match(JSON.stringify(result[0].content), /unavailable; contents not reviewed/);
  await assert.rejects(resources.load(resource.id), /unavailable; contents not reviewed/);
});

test('decoded resource cache retains only eight recently used versions', async () => {
  const catalog = Array.from({length: 10}, (_, i) => descriptor(String(i))), calls = [];
  const resources = createImageResources(catalog, async (_method, {id}) => {
    calls.push(id); return image(String(catalog.findIndex(resource => resource.id === id)));
  });
  for (const resource of catalog) await resources.load(resource.id);
  await resources.load(catalog.at(-1).id);
  assert.equal(calls.length, 10);
  await resources.load(catalog[0].id);
  assert.equal(calls.length, 11);
});

test('known attachment content deduplicates a current intentional read before preflight limits', async () => {
  const resource = descriptor('same', 'f_same');
  const resources = createImageResources([resource], async () => image('same'));
  await resources.load(resource.id);
  const messages = [referenced('u', resource), ...batch('read', [resource.path], ['same'])];
  const hydrated = await hydrateImageRefs(messages, resources, {...limits, maxImages: 1, maxImageBytes: 4});
  assert.equal(pixels(projectImageContext(hydrated)).length, 1);
});

test('registered resource paths must be normalized virtual files', () => {
  const resource = descriptor('image');
  for (const path of ['/etc/passwd', '/bot/.cota/context-images/session/../../host.png', '/bot/.cota/context-images/session/..'])
    assert.throws(() => createImageResources([{...resource, path}], async () => image('image')), /descriptor/i);
});

test('older local tool images prefer registered immutable version paths over overwritten workspace paths', () => {
  const resource = descriptor('old');
  const resources = createImageResources([resource], async () => image('old'));
  const messages = [user('u'), ...batch('old', ['/book/page.png'], ['old']), ...batch('new', ['/book/page.png'], ['new'])];
  const reference = projectImageContext(messages, resources)[2].content[0].text;
  assert(reference.includes(resource.path));
  assert.equal(reference.includes('/book/page.png'), false);
  assert(reference.includes('r-old-0'));
});

test('text-only wrap-up keeps image provenance without pixels or fabricated review', () => {
  const resource = descriptor('current');
  const resources = createImageResources([resource], async () => {throw new Error('Wrap-up must not fetch pixels');});
  const raw = [user('u', [image('user image')]), ...batch('now', ['/book/page.png'], ['current']),
    referenced('referenced-current', resource, 'toolResult')];
  const before = structuredClone(raw);
  const projected = projectImageContext(raw, resources, {textOnly: true});
  assert.equal(pixels(projected).length, 0);
  assert.match(JSON.stringify(projected), /no new visual review|not reviewed/i);
  assert.match(JSON.stringify(projected), /\/book\/page.png|context-images/);
  assert(projected.filter((_message, index) => index !== 1).every(message => message.cotaImagePixelsOmitted));
  assert.deepEqual(raw, before);
});
