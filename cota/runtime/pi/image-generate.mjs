/** Generate images via OpenAI or Qwen-compatible image APIs.
 * Supports text-to-image and reference-image editing. Saves output as a local file.
 * OpenAI: /images/generations (JSON) + /images/edits (multipart for references).
 * Qwen/ByteDance: /images/generations (JSON) with `image` field for references.
 */
import https from 'node:https';
import http from 'node:http';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {dirname, extname} from 'node:path';
import {Type} from '@earendil-works/pi-ai';

const MAX_RESPONSE_BYTES = 64 * 1024 * 1024;
const MAX_IMAGE_INPUT_BYTES = 32 * 1024 * 1024;
const TIMEOUT_MS = 240_000;
const IMAGE_EXTENSIONS = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'};

const parameters = Type.Object({
  prompt: Type.String({description: 'Text description of the image to generate'}),
  output_path: Type.String({description: 'Absolute path to save the generated image (PNG/JPEG/WebP)'}),
  reference_images: Type.Optional(Type.Array(
    Type.String({description: 'Absolute path of a reference image'}),
    {maxItems: 8, description: 'Reference images for guided generation or editing'})),
  size: Type.Optional(Type.String({description: 'Override default dimensions, e.g. "1024x1024"'})),
}, {additionalProperties: false});

function fail(message) {
  return {content: [{type: 'text', text: JSON.stringify({error: message})}],
    details: {error: message}, isError: true};
}

// ---------------------------------------------------------------------------
// HTTP transport
// ---------------------------------------------------------------------------

function collectResponse(response, reject) {
  const chunks = [];
  let bytes = 0;
  response.on('data', chunk => {
    bytes += chunk.length;
    if (bytes > MAX_RESPONSE_BYTES) {
      reject(new Error('Response exceeds 64 MiB'));
      response.destroy();
    } else chunks.push(chunk);
  });
  return chunks;
}

function jsonPost(baseUrl, path, apiKey, body, signal) {
  return new Promise((resolve, reject) => {
    const url = new URL(baseUrl.replace(/\/+$/, '') + path);
    const transport = url.protocol === 'https:' ? https : http;
    const payload = JSON.stringify(body);
    const req = transport.request(url, {method: 'POST', signal, agent: false, headers: {
      'Content-Type': 'application/json', 'Authorization': `Bearer ${apiKey}`,
      'Content-Length': String(Buffer.byteLength(payload)),
    }}, response => {
      const chunks = collectResponse(response, reject);
      response.on('error', reject);
      response.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf8');
        if (response.statusCode !== 200) return reject(new Error(`API error (HTTP ${response.statusCode})`));
        try { resolve(JSON.parse(text)); } catch { reject(new Error('Invalid JSON response')); }
      });
    });
    req.on('error', reject);
    req.end(payload);
  });
}

function multipartPost(baseUrl, path, apiKey, fields, files, signal) {
  return new Promise((resolve, reject) => {
    const boundary = '----CotaImage' + Date.now().toString(36) + Math.random().toString(36).slice(2);
    const parts = [];
    for (const [name, value] of Object.entries(fields)) {
      parts.push(Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="${name}"\r\n\r\n${value}\r\n`));
    }
    for (const file of files) {
      parts.push(Buffer.from(
        `--${boundary}\r\nContent-Disposition: form-data; name="${file.field}"; filename="${file.name}"\r\n`
        + `Content-Type: ${file.type}\r\n\r\n`));
      parts.push(file.data);
      parts.push(Buffer.from('\r\n'));
    }
    parts.push(Buffer.from(`--${boundary}--\r\n`));
    const body = Buffer.concat(parts);
    const url = new URL(baseUrl.replace(/\/+$/, '') + path);
    const transport = url.protocol === 'https:' ? https : http;
    const req = transport.request(url, {method: 'POST', signal, agent: false, headers: {
      'Content-Type': `multipart/form-data; boundary=${boundary}`,
      'Authorization': `Bearer ${apiKey}`, 'Content-Length': String(body.length),
    }}, response => {
      const chunks = collectResponse(response, reject);
      response.on('error', reject);
      response.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf8');
        if (response.statusCode !== 200) return reject(new Error(`API error (HTTP ${response.statusCode})`));
        try { resolve(JSON.parse(text)); } catch { reject(new Error('Invalid JSON response')); }
      });
    });
    req.on('error', reject);
    req.end(body);
  });
}

function downloadImage(imageUrl, signal) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(imageUrl);
    if (parsed.protocol !== 'https:') return reject(new Error('Image URL must use HTTPS'));
    const req = https.request(parsed, {method: 'GET', signal, agent: false}, response => {
      if (response.statusCode !== 200) return reject(new Error(`Image download failed (HTTP ${response.statusCode})`));
      const chunks = [];
      let bytes = 0;
      response.on('data', chunk => {
        bytes += chunk.length;
        if (bytes > MAX_IMAGE_INPUT_BYTES) { reject(new Error('Downloaded image exceeds 32 MiB')); response.destroy(); }
        else chunks.push(chunk);
      });
      response.on('error', reject);
      response.on('end', () => resolve(Buffer.concat(chunks)));
    });
    req.on('error', reject);
    req.end();
  });
}

// ---------------------------------------------------------------------------
// Image I/O helpers
// ---------------------------------------------------------------------------

async function readImage(path) {
  const data = await readFile(path);
  if (data.length > MAX_IMAGE_INPUT_BYTES) throw new Error(`Reference image exceeds 32 MiB: ${path}`);
  const ext = extname(path).toLowerCase();
  const mime = IMAGE_EXTENSIONS[ext];
  if (!mime) throw new Error(`Unsupported image format (${ext}); use PNG, JPEG or WebP`);
  return {data, mime, filename: path.split('/').pop()};
}

async function extractImageData(result, signal) {
  const item = result?.data?.[0];
  if (!item) throw new Error('No image data in API response');
  if (typeof item.b64_json === 'string') return Buffer.from(item.b64_json, 'base64');
  if (typeof item.url === 'string') return downloadImage(item.url, signal);
  throw new Error('Response contains neither b64_json nor a downloadable URL');
}

// ---------------------------------------------------------------------------
// Tool
// ---------------------------------------------------------------------------

/**
 * @param {{apiKey: string, baseUrl: string, model: string, type?: string,
 *          size?: string, quality?: string, response_format?: string,
 *          request?: Function}} config
 */
export function createImageGenerateTool(config) {
  const apiType = config.type || 'openai';
  const post = config.request
    ? (path, body, signal) => config.request(path, body, signal)
    : (path, body, signal) => jsonPost(config.baseUrl, path, config.apiKey, body, signal);
  const multipart = config.multipartRequest
    ? (path, fields, files, signal) => config.multipartRequest(path, fields, files, signal)
    : (path, fields, files, signal) => multipartPost(config.baseUrl, path, config.apiKey, fields, files, signal);

  return {
    name: 'image_generate', label: 'Image generate',
    description: 'Generate an image from a text description. Optionally accepts reference images for guided generation or editing. Saves the result to the specified path.',
    parameters,
    async execute(toolCallId, args, signal) {
      if (signal?.aborted) throw new DOMException('Image generate cancelled', 'AbortError');
      const controller = new AbortController();
      const requestSignal = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
      const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
      try {
        const {prompt, output_path, reference_images, size} = args;
        if (!output_path) return fail('output_path is required');
        const outExt = extname(output_path).toLowerCase();
        if (!IMAGE_EXTENSIONS[outExt]) return fail('output_path must end in .png, .jpg, .jpeg or .webp');

        const refs = [];
        if (reference_images?.length) {
          for (const refPath of reference_images) refs.push(await readImage(refPath));
        }

        const imageSize = size || config.size;
        let result;

        if (apiType === 'qwen') {
          const body = {model: config.model, prompt, n: 1};
          if (imageSize) body.size = imageSize;
          if (refs.length) {
            const uris = refs.map(r => `data:${r.mime};base64,${r.data.toString('base64')}`);
            body.image = uris.length === 1 ? uris[0] : uris;
          }
          result = await post('/images/generations', body, requestSignal);
        } else {
          if (refs.length) {
            const fields = {model: config.model, prompt, n: '1'};
            if (imageSize) fields.size = imageSize;
            if (config.quality) fields.quality = config.quality;
            if (config.response_format) fields.response_format = config.response_format;
            const files = refs.map(r => ({field: 'image[]', name: r.filename, data: r.data, type: r.mime}));
            result = await multipart('/images/edits', fields, files, requestSignal);
          } else {
            const body = {model: config.model, prompt, n: 1};
            if (imageSize) body.size = imageSize;
            if (config.quality) body.quality = config.quality;
            if (config.response_format) body.response_format = config.response_format;
            result = await post('/images/generations', body, requestSignal);
          }
        }

        const imageData = await extractImageData(result, requestSignal);
        await mkdir(dirname(output_path), {recursive: true});
        await writeFile(output_path, imageData);

        const details = {path: output_path, size_bytes: imageData.length, model: config.model};
        return {content: [{type: 'text', text: JSON.stringify(details)}], details, isError: false};
      } catch (error) {
        if (signal?.aborted) throw new DOMException('Image generate cancelled', 'AbortError');
        return fail(error.message || 'Image generation failed');
      } finally { clearTimeout(timer); }
    },
  };
}
