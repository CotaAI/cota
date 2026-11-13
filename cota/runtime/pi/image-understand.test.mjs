import assert from 'node:assert/strict';
import {test} from 'node:test';
import {writeFile, mkdir} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {validateToolArguments} from '@earendil-works/pi-ai';
import {createImageUnderstandTool} from './image-understand.mjs';

const PNG_1x1 = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64');

function config(overrides = {}) {
  return {apiKey: 'test-key', baseUrl: 'https://api.test', model: 'test-vision', ...overrides};
}

function chatResponse(text = 'A small red square on a white background.') {
  return {choices: [{message: {content: text}}]};
}

async function tempDir(t) {
  const dir = join(tmpdir(), `cota-vis-test-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  await mkdir(dir, {recursive: true});
  t.after(async () => { try { const {rm} = await import('node:fs/promises'); await rm(dir, {recursive: true}); } catch {} });
  return dir;
}

test('exposes native Pi schema validation', () => {
  const tool = createImageUnderstandTool(config());
  assert.equal(tool.name, 'image_understand');
  assert.equal(typeof tool.label, 'string');
  assert.deepEqual(validateToolArguments(tool, {type: 'toolCall', id: 'x', name: tool.name,
    arguments: {image_path: '/tmp/photo.png'}}),
  {image_path: '/tmp/photo.png'});
  assert.deepEqual(validateToolArguments(tool, {type: 'toolCall', id: 'x', name: tool.name,
    arguments: {image_path: '/tmp/photo.jpg', prompt: 'What color is this?'}}),
  {image_path: '/tmp/photo.jpg', prompt: 'What color is this?'});
  assert.throws(() => validateToolArguments(tool, {type: 'toolCall', id: 'x', name: tool.name, arguments: {}}));
});

test('sends image as base64 data URI in chat completions format', async t => {
  const dir = await tempDir(t);
  const imgPath = join(dir, 'test.png');
  await writeFile(imgPath, PNG_1x1);
  let requestPath, requestBody;
  const tool = createImageUnderstandTool(config({
    request: (path, body) => { requestPath = path; requestBody = body; return chatResponse(); },
  }));
  const result = await tool.execute('vis-1', {image_path: imgPath});
  assert.equal(result.isError, false);
  assert.equal(requestPath, '/chat/completions');
  assert.equal(requestBody.model, 'test-vision');
  const msg = requestBody.messages[0];
  assert.equal(msg.role, 'user');
  assert.equal(msg.content.length, 2);
  assert.equal(msg.content[0].type, 'text');
  assert.equal(msg.content[0].text, 'Describe this image in detail.');
  assert.equal(msg.content[1].type, 'image_url');
  assert.ok(msg.content[1].image_url.url.startsWith('data:image/png;base64,'));
  assert.equal(result.content[0].text, 'A small red square on a white background.');
});

test('uses custom prompt when provided', async t => {
  const dir = await tempDir(t);
  const imgPath = join(dir, 'custom.png');
  await writeFile(imgPath, PNG_1x1);
  let requestBody;
  const tool = createImageUnderstandTool(config({
    request: (path, body) => { requestBody = body; return chatResponse('It is blue.'); },
  }));
  const result = await tool.execute('vis-2', {image_path: imgPath, prompt: 'What color is this?'});
  assert.equal(result.isError, false);
  assert.equal(requestBody.messages[0].content[0].text, 'What color is this?');
  assert.equal(result.content[0].text, 'It is blue.');
});

test('detects MIME type from file extension', async t => {
  const dir = await tempDir(t);
  for (const [ext, mime] of [['jpg', 'image/jpeg'], ['jpeg', 'image/jpeg'], ['webp', 'image/webp'], ['gif', 'image/gif']]) {
    const imgPath = join(dir, `test.${ext}`);
    await writeFile(imgPath, PNG_1x1);
    let requestBody;
    const tool = createImageUnderstandTool(config({
      request: (path, body) => { requestBody = body; return chatResponse(); },
    }));
    await tool.execute(`vis-mime-${ext}`, {image_path: imgPath});
    assert.ok(requestBody.messages[0].content[1].image_url.url.startsWith(`data:${mime};base64,`), `Expected ${mime} for .${ext}`);
  }
});

test('returns error for unsupported image format', async t => {
  const dir = await tempDir(t);
  const imgPath = join(dir, 'test.tiff');
  await writeFile(imgPath, PNG_1x1);
  const tool = createImageUnderstandTool(config({request: () => assert.fail('should not call API')}));
  const result = await tool.execute('vis-3', {image_path: imgPath});
  assert.equal(result.isError, true);
  const parsed = JSON.parse(result.content[0].text);
  assert.ok(parsed.error.includes('.tiff'));
});

test('returns error when image file does not exist', async t => {
  const tool = createImageUnderstandTool(config({request: () => assert.fail('should not call API')}));
  const result = await tool.execute('vis-4', {image_path: '/nonexistent/path/img.png'});
  assert.equal(result.isError, true);
});

test('returns error when API request fails', async t => {
  const dir = await tempDir(t);
  const imgPath = join(dir, 'err.png');
  await writeFile(imgPath, PNG_1x1);
  const tool = createImageUnderstandTool(config({
    request: () => { throw new Error('API error (HTTP 503)'); },
  }));
  const result = await tool.execute('vis-5', {image_path: imgPath});
  assert.equal(result.isError, true);
  assert.ok(JSON.parse(result.content[0].text).error.includes('503'));
});

test('returns error when vision model returns empty content', async t => {
  const dir = await tempDir(t);
  const imgPath = join(dir, 'empty.png');
  await writeFile(imgPath, PNG_1x1);
  const tool = createImageUnderstandTool(config({
    request: () => ({choices: [{message: {content: ''}}]}),
  }));
  const result = await tool.execute('vis-6', {image_path: imgPath});
  assert.equal(result.isError, true);
  assert.ok(JSON.parse(result.content[0].text).error.includes('did not return'));
});

test('returns error when response has no choices', async t => {
  const dir = await tempDir(t);
  const imgPath = join(dir, 'noc.png');
  await writeFile(imgPath, PNG_1x1);
  const tool = createImageUnderstandTool(config({
    request: () => ({choices: []}),
  }));
  const result = await tool.execute('vis-7', {image_path: imgPath});
  assert.equal(result.isError, true);
});

test('includes model and image_path in details on success', async t => {
  const dir = await tempDir(t);
  const imgPath = join(dir, 'det.png');
  await writeFile(imgPath, PNG_1x1);
  const tool = createImageUnderstandTool(config({request: () => chatResponse('hello')}));
  const result = await tool.execute('vis-8', {image_path: imgPath});
  assert.equal(result.isError, false);
  assert.equal(result.details.model, 'test-vision');
  assert.equal(result.details.image_path, imgPath);
});

test('re-throws AbortError on pre-aborted signal', async () => {
  const tool = createImageUnderstandTool(config({request: () => assert.fail('should not call')}));
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    tool.execute('vis-9', {image_path: '/tmp/x.png'}, controller.signal),
    {name: 'AbortError'});
});

test('records the hash of actual sent bytes even if source changes during analysis', async t => {
  const {createHash} = await import('node:crypto');
  const dir = await tempDir(t);
  const imgPath = join(dir, 'version.png');
  await writeFile(imgPath, PNG_1x1);
  const tool = createImageUnderstandTool(config({request: async (_path, body) => {
    assert.ok(body.messages[0].content[1].image_url.url.endsWith(PNG_1x1.toString('base64')));
    await writeFile(imgPath, 'a later revision');
    return chatResponse('Specific visible observation.');
  }}));
  const result = await tool.execute('vision-source-id', {image_path: imgPath, prompt: 'Check the target.'});
  assert.equal(result.details.image_sha256, createHash('sha256').update(PNG_1x1).digest('hex'));
  const source = JSON.parse(result.content[1].text);
  assert.equal(source.tool_call_id, 'vision-source-id');
  assert.equal(source.image_sha256, result.details.image_sha256);
  assert.equal(result.content[0].text, 'Specific visible observation.');
});
