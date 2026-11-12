/** Analyze images using a vision-capable model via standard chat completions.
 * All major providers (OpenAI, Qwen, ByteDance) support the same image_url
 * content block format in their chat/completions endpoints.
 */
import https from 'node:https';
import http from 'node:http';
import {readFile} from 'node:fs/promises';
import {extname} from 'node:path';
import {Type} from '@earendil-works/pi-ai';

const MAX_IMAGE_BYTES = 32 * 1024 * 1024;
const MAX_RESPONSE_BYTES = 4 * 1024 * 1024;
const TIMEOUT_MS = 120_000;
const MIME_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
  '.webp': 'image/webp', '.gif': 'image/gif', '.bmp': 'image/bmp'};

const parameters = Type.Object({
  image_path: Type.String({description: 'Absolute path of the image to analyze'}),
  prompt: Type.Optional(Type.String({description: 'Analysis instruction; defaults to describing the image'})),
}, {additionalProperties: false});

function fail(message) {
  return {content: [{type: 'text', text: JSON.stringify({error: message})}],
    details: {error: message}, isError: true};
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
      const chunks = [];
      let bytes = 0;
      response.on('data', chunk => {
        bytes += chunk.length;
        if (bytes > MAX_RESPONSE_BYTES) { reject(new Error('Response exceeds size limit')); response.destroy(); }
        else chunks.push(chunk);
      });
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

/**
 * @param {{apiKey: string, baseUrl: string, model: string, request?: Function}} config
 */
export function createImageUnderstandTool(config) {
  const post = config.request
    ? (path, body, signal) => config.request(path, body, signal)
    : (path, body, signal) => jsonPost(config.baseUrl, path, config.apiKey, body, signal);

  return {
    name: 'image_understand', label: 'Image understand',
    description: 'Analyze an image using a vision model. Reads the image file and returns a text description or analysis based on the given prompt.',
    parameters,
    async execute(toolCallId, args, signal) {
      if (signal?.aborted) throw new DOMException('Image understand cancelled', 'AbortError');
      const controller = new AbortController();
      const requestSignal = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
      const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
      try {
        const {image_path, prompt = 'Describe this image in detail.'} = args;

        const data = await readFile(image_path);
        if (data.length > MAX_IMAGE_BYTES) return fail('Image exceeds 32 MiB');
        const ext = extname(image_path).toLowerCase();
        const mime = MIME_TYPES[ext];
        if (!mime) return fail(`Unsupported image format (${ext}); use PNG, JPEG, WebP, GIF or BMP`);

        const body = {
          model: config.model,
          messages: [{role: 'user', content: [
            {type: 'text', text: prompt},
            {type: 'image_url', image_url: {url: `data:${mime};base64,${data.toString('base64')}`}},
          ]}],
        };

        const result = await post('/chat/completions', body, requestSignal);
        const text = result?.choices?.[0]?.message?.content;
        if (typeof text !== 'string' || !text.trim()) return fail('Vision model did not return analysis text');

        return {content: [{type: 'text', text}],
          details: {model: config.model, image_path}, isError: false};
      } catch (error) {
        if (signal?.aborted) throw new DOMException('Image understand cancelled', 'AbortError');
        return fail(error.message || 'Image understanding failed');
      } finally { clearTimeout(timer); }
    },
  };
}
