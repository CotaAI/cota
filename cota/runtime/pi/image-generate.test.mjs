import assert from 'node:assert/strict';
import {test} from 'node:test';
import {writeFile, mkdir, readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {validateToolArguments} from '@earendil-works/pi-ai';
import {createImageGenerateTool} from './image-generate.mjs';

const PNG_1x1 = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64');

function config(overrides = {}) {
  return {apiKey: 'test-key', baseUrl: 'https://api.test', model: 'test-model', type: 'openai', ...overrides};
}

function b64Response(data = PNG_1x1) {
  return {data: [{b64_json: data.toString('base64')}]};
}

async function tempDir(t) {
  const dir = join(tmpdir(), `cota-img-test-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  await mkdir(dir, {recursive: true});
  t.after(async () => { try { const {rm} = await import('node:fs/promises'); await rm(dir, {recursive: true}); } catch {} });
  return dir;
}

test('exposes native Pi schema validation', () => {
  const tool = createImageGenerateTool(config());
  assert.equal(tool.name, 'image_generate');
  assert.equal(typeof tool.label, 'string');
  assert.deepEqual(validateToolArguments(tool, {type: 'toolCall', id: 'x', name: tool.name,
    arguments: {prompt: 'a cat', output_path: '/tmp/cat.png'}}),
  {prompt: 'a cat', output_path: '/tmp/cat.png'});
  for (const args of [{}, {prompt: 'a cat'}, {output_path: '/tmp/cat.png'}]) {
    assert.throws(() => validateToolArguments(tool, {type: 'toolCall', id: 'x', name: tool.name, arguments: args}));
  }
});

test('generates image via openai text-to-image and saves file', async t => {
  const dir = await tempDir(t);
  const outputPath = join(dir, 'out.png');
  let requestPath, requestBody;
  const tool = createImageGenerateTool(config({
    request: (path, body) => { requestPath = path; requestBody = body; return b64Response(); },
  }));
  const result = await tool.execute('gen-1', {prompt: 'a sunset', output_path: outputPath});
  assert.equal(result.isError, false);
  assert.equal(requestPath, '/images/generations');
  assert.equal(requestBody.model, 'test-model');
  assert.equal(requestBody.prompt, 'a sunset');
  const details = JSON.parse(result.content[0].text);
  assert.equal(details.path, outputPath);
  assert.equal(details.size_bytes, PNG_1x1.length);
  const saved = await readFile(outputPath);
  assert.deepEqual(saved, PNG_1x1);
});

test('uses multipart /images/edits for openai with reference images', async t => {
  const dir = await tempDir(t);
  const refPath = join(dir, 'ref.png');
  await writeFile(refPath, PNG_1x1);
  const outputPath = join(dir, 'edited.png');
  let multipartPath, multipartFields;
  const tool = createImageGenerateTool(config({
    multipartRequest: (path, fields, files) => {
      multipartPath = path; multipartFields = fields;
      assert.equal(files.length, 1);
      assert.equal(files[0].field, 'image[]');
      return b64Response();
    },
  }));
  const result = await tool.execute('gen-2', {prompt: 'add stars', output_path: outputPath, reference_images: [refPath]});
  assert.equal(result.isError, false);
  assert.equal(multipartPath, '/images/edits');
  assert.equal(multipartFields.prompt, 'add stars');
});

test('uses JSON with image field for qwen type', async t => {
  const dir = await tempDir(t);
  const refPath = join(dir, 'ref.png');
  await writeFile(refPath, PNG_1x1);
  const outputPath = join(dir, 'qwen-out.png');
  let requestBody;
  const tool = createImageGenerateTool(config({
    type: 'qwen',
    request: (path, body) => { requestBody = body; return b64Response(); },
  }));
  const result = await tool.execute('gen-3', {prompt: 'style transfer', output_path: outputPath, reference_images: [refPath]});
  assert.equal(result.isError, false);
  assert.ok(typeof requestBody.image === 'string');
  assert.ok(requestBody.image.startsWith('data:image/png;base64,'));
});

test('qwen sends array for multiple reference images', async t => {
  const dir = await tempDir(t);
  const ref1 = join(dir, 'r1.png');
  const ref2 = join(dir, 'r2.png');
  await writeFile(ref1, PNG_1x1);
  await writeFile(ref2, PNG_1x1);
  const outputPath = join(dir, 'multi.png');
  let requestBody;
  const tool = createImageGenerateTool(config({
    type: 'qwen',
    request: (path, body) => { requestBody = body; return b64Response(); },
  }));
  await tool.execute('gen-4', {prompt: 'merge', output_path: outputPath, reference_images: [ref1, ref2]});
  assert.ok(Array.isArray(requestBody.image));
  assert.equal(requestBody.image.length, 2);
});

test('passes size override from args', async t => {
  const dir = await tempDir(t);
  const outputPath = join(dir, 'sized.png');
  let requestBody;
  const tool = createImageGenerateTool(config({
    request: (path, body) => { requestBody = body; return b64Response(); },
  }));
  await tool.execute('gen-5', {prompt: 'a lake', output_path: outputPath, size: '512x512'});
  assert.equal(requestBody.size, '512x512');
});

test('uses config size when args size is absent', async t => {
  const dir = await tempDir(t);
  const outputPath = join(dir, 'default-sized.png');
  let requestBody;
  const tool = createImageGenerateTool(config({
    size: '768x768',
    request: (path, body) => { requestBody = body; return b64Response(); },
  }));
  await tool.execute('gen-6', {prompt: 'a tree', output_path: outputPath});
  assert.equal(requestBody.size, '768x768');
});

test('returns error for unsupported output extension', async t => {
  const tool = createImageGenerateTool(config({request: () => assert.fail('should not call API')}));
  const result = await tool.execute('gen-7', {prompt: 'test', output_path: '/tmp/out.bmp'});
  assert.equal(result.isError, true);
  const parsed = JSON.parse(result.content[0].text);
  assert.ok(parsed.error.includes('output_path'));
});

test('returns error when API fails', async t => {
  const dir = await tempDir(t);
  const tool = createImageGenerateTool(config({
    request: () => { throw new Error('API error (HTTP 500)'); },
  }));
  const result = await tool.execute('gen-8', {prompt: 'test', output_path: join(dir, 'fail.png')});
  assert.equal(result.isError, true);
  const parsed = JSON.parse(result.content[0].text);
  assert.ok(parsed.error.includes('500'));
});

test('returns error when response has no image data', async t => {
  const dir = await tempDir(t);
  const tool = createImageGenerateTool(config({
    request: () => ({data: []}),
  }));
  const result = await tool.execute('gen-9', {prompt: 'test', output_path: join(dir, 'empty.png')});
  assert.equal(result.isError, true);
  assert.ok(JSON.parse(result.content[0].text).error.includes('No image data'));
});

test('creates intermediate directories for output path', async t => {
  const dir = await tempDir(t);
  const outputPath = join(dir, 'sub', 'deep', 'out.png');
  const tool = createImageGenerateTool(config({request: () => b64Response()}));
  const result = await tool.execute('gen-10', {prompt: 'test', output_path: outputPath});
  assert.equal(result.isError, false);
  await readFile(outputPath);
});

test('re-throws AbortError on pre-aborted signal', async () => {
  const tool = createImageGenerateTool(config({request: () => assert.fail('should not call')}));
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    tool.execute('gen-11', {prompt: 'test', output_path: '/tmp/x.png'}, controller.signal),
    {name: 'AbortError'});
});

test('passes quality and response_format for openai', async t => {
  const dir = await tempDir(t);
  let requestBody;
  const tool = createImageGenerateTool(config({
    quality: 'hd', response_format: 'b64_json',
    request: (path, body) => { requestBody = body; return b64Response(); },
  }));
  await tool.execute('gen-12', {prompt: 'test', output_path: join(dir, 'q.png')});
  assert.equal(requestBody.quality, 'hd');
  assert.equal(requestBody.response_format, 'b64_json');
});

test('returns error when output_path is missing', async () => {
  const tool = createImageGenerateTool(config({request: () => assert.fail('should not call')}));
  const result = await tool.execute('gen-13', {prompt: 'test', output_path: ''});
  assert.equal(result.isError, true);
});

test('supportsReferences defaults to true — schema includes reference_images', () => {
  const tool = createImageGenerateTool(config());
  assert.ok(tool.description.includes('reference'));
  const props = tool.parameters.properties;
  assert.ok('reference_images' in props);
});

test('supportsReferences false — schema omits reference_images and description omits references', () => {
  const tool = createImageGenerateTool(config({supportsReferences: false}));
  assert.ok(!tool.description.includes('reference'));
  const props = tool.parameters.properties;
  assert.ok(!('reference_images' in props));
  assert.ok('prompt' in props);
  assert.ok('output_path' in props);
  assert.ok('size' in props);
});

test('supportsReferences false — rejects reference_images in validation', () => {
  const tool = createImageGenerateTool(config({supportsReferences: false}));
  assert.throws(() => validateToolArguments(tool, {type: 'toolCall', id: 'x', name: tool.name,
    arguments: {prompt: 'a cat', output_path: '/tmp/cat.png', reference_images: ['/tmp/ref.png']}}));
});

test('supportsReferences false — text-to-image still works', async t => {
  const dir = await tempDir(t);
  const outputPath = join(dir, 'norefs.png');
  const tool = createImageGenerateTool(config({
    supportsReferences: false,
    request: (path, body) => b64Response(),
  }));
  const result = await tool.execute('gen-norefs', {prompt: 'a sunset', output_path: outputPath});
  assert.equal(result.isError, false);
});
