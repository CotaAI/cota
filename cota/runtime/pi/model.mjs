/** Official Pi provider stream; Cota retains observations and durable acknowledgments. */
import {readFile} from 'node:fs/promises';
import {stream as streamCompletions} from '@earendil-works/pi-ai/api/openai-completions';
import {createAssistantMessageEventStream} from '@earendil-works/pi-ai';

const IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/gif', 'image/webp']);
const IMAGE_LIMIT = 2 * 1024 * 1024;

export function nativeModel(model, provider) {
  return {...model, id: provider.model || model.id, name: provider.model || model.id,
    baseUrl: provider.baseUrl || 'https://api.openai.com/v1',
    input: provider.vision ? ['text', 'image'] : ['text'],
    attachmentImages: provider.vision ? {mimeTypes: [...IMAGE_TYPES], maxBytes: IMAGE_LIMIT} : {},
    reasoning: provider.thinking === true || provider.thinking === 'enabled'};
}

async function hydrate(messages, attachments, provider) {
  const result = structuredClone(messages);
  const entries = new Map((attachments ?? []).map(entry => [entry.message_id, entry.files]));
  for (const message of result) {
    if (message.role !== 'user') continue;
    const files = entries.get(message.cotaEventId) ?? [];
    if (!files.length) continue;
    const blocks = typeof message.content === 'string' ? [{type: 'text', text: message.content}] : message.content;
    for (const file of files) {
      let note = file.note;
      const supported = IMAGE_TYPES.has(file.mimeType) && Number.isSafeInteger(file.size)
        && file.size >= 0 && file.size <= IMAGE_LIMIT;
      if (!note && provider.vision && supported && file.path) {
        try {
          const data = await readFile(file.path);
          if (data.length > IMAGE_LIMIT || data.length !== file.size) note = 'Attachment changed after authorization; contents not reviewed';
          else {blocks.push({type: 'image', data: data.toString('base64'), mimeType: file.mimeType}); continue;}
        } catch {note = 'Attachment unavailable';}
      }
      note ??= file.mimeType?.startsWith('image/')
        ? file.size > IMAGE_LIMIT
          ? 'Image exceeds automatic model-input limit of 2 MiB; process it with appropriate image tools before interpretation.'
          : 'Selected model is not configured for this image input; use an appropriate vision tool before interpretation.'
        : 'File contents have not been parsed; use appropriate tools before claiming to understand this file.';
      blocks.push({type: 'text', text: JSON.stringify({attachment_id: file.id, name: file.name, note,
        ...(file.local_copy ? {local_copy: file.local_copy} : {})})});
    }
    message.content = blocks.some(block => block.type === 'image') ? blocks : blocks.map(block => block.text ?? '').join('\n');
  }
  return result;
}

// Provider errors can quote arbitrary response bodies. Never include credentials,
// URLs, or the rest of a provider error body in ordinary IPC observations.
function safeError(error, provider) {
  let message = String(error?.message ?? error ?? 'Model request failed');
  if (provider.apiKey) message = message.split(provider.apiKey).join('[redacted]');
  message = message.replace(/Bearer\s+\S+/gi, 'Bearer [redacted]');
  return message.split('\n')[0].slice(0, 500);
}

export async function nativeStream({model, provider, context, attachments, purpose = 'dialogue',
  contextBudget, maxTokens = model.maxTokens, rpc, signal, notify = async () => {}, onComplete = () => {}}) {
  const {request_id, debug} = await rpc('model_begin', {purpose, model: model.id,
    ...(contextBudget ? {contextBudget} : {})});
  const output = createAssistantMessageEventStream();
  const began = performance.now();
  const transport = {attempts: [], first_text_ms: null, timeout_seconds: provider.timeoutSeconds ?? 180, max_retries: provider.maxRetries ?? 0};
  const controller = new AbortController();
  let timedOut = false;
  const abort = () => controller.abort(signal?.reason);
  if (signal?.aborted) abort();
  else signal?.addEventListener('abort', abort, {once: true});
  const timeoutMs = (provider.timeoutSeconds ?? 180) * 1000;
  const timer = setTimeout(() => {timedOut = true; controller.abort(new Error('Model request timed out'));}, timeoutMs);
  // AbortSignal alone stops HTTP, but cannot interrupt an awaited Python hook
  // or stdout write. Those waits consume the same total request deadline.
  const bounded = promise => new Promise((resolve, reject) => {
    const interrupted = () => reject(controller.signal.reason ?? new Error('Aborted'));
    if (controller.signal.aborted) {interrupted(); Promise.resolve(promise).catch(() => {}); return;}
    controller.signal.addEventListener('abort', interrupted, {once: true});
    Promise.resolve(promise).then(resolve, reject).finally(() =>
      controller.signal.removeEventListener('abort', interrupted));
  });
  const visible = purpose === 'dialogue';
  const notification = phase => visible ? notify('stream', {request_id, phase}) : Promise.resolve();
  void (async () => {
    let partial;
    try {
      await bounded(notification('start'));
      controller.signal.throwIfAborted();
      const messages = await bounded(hydrate(context.messages, attachments, provider));
      controller.signal.throwIfAborted();
      const stream = streamCompletions(model, {messages, tools: context.tools}, {
        apiKey: provider.apiKey, signal: controller.signal, timeoutMs, maxRetries: provider.maxRetries ?? 0,
        maxTokens,
        fetch: async (url, init) => {
          const previous = transport.attempts.at(-1);
          if (previous) previous.status = 'retried';
          const attempt = {number: transport.attempts.length + 1, started_ms: Math.round(performance.now() - began), status: 'running'};
          transport.attempts.push(attempt);
          await bounded(rpc('model_observation', {request_id, kind: 'transport', transport: structuredClone(transport)}));
          try {
            const response = await fetch(url, init);
            attempt.status_code = response.status;
            attempt.status = response.status >= 400 ? 'http_error' : 'receiving';
            attempt.headers_ms = Math.round(performance.now() - began);
            await bounded(rpc('model_observation', {request_id, kind: 'transport', transport: structuredClone(transport)}));
            return response;
          } catch (error) {
            attempt.error_type = error?.name || 'Error';
            throw error;
          }
        },
        onPayload: async payload => {
          // Pi assembles all OpenAI parameters; this endpoint-specific extension
          // carries Cota's existing explicit thinking preference.
          if (provider.thinking !== undefined && provider.thinking !== null)
            payload.thinking = typeof provider.thinking === 'object' ? provider.thinking :
              {type: typeof provider.thinking === 'string' ? provider.thinking : provider.thinking ? 'enabled' : 'disabled'};
          if (debug) await bounded(rpc('model_observation', {request_id, kind: 'request', request: payload}));
        },
      });
      const iterator = stream[Symbol.asyncIterator]();
      for (;;) {
        const next = await bounded(iterator.next());
        if (next.done) break;
        const event = next.value;
        partial = event.partial ?? partial;
        if (event.type === 'text_delta') {
          transport.first_text_ms ??= Math.round(performance.now() - began);
          if (visible) await bounded(notify('stream', {request_id, phase: 'delta', text: event.delta}));
        }
        if (event.type === 'error') throw new Error(event.error.errorMessage || 'Model request failed');
        if (event.type === 'done') {
          controller.signal.throwIfAborted();
          const message = event.message;
          transport.response_ready_ms = Math.round(performance.now() - began);
          if (transport.attempts.length) transport.attempts.at(-1).status = 'completed';
          await bounded(rpc('model_complete', {request_id, message, duration_ms: Math.round(performance.now() - began), transport}));
          onComplete(message);
          await bounded(notification('end'));
          output.push(event);
        } else output.push(event);
      }
    } catch (error) {
      const error_type = timedOut ? 'TimeoutError' : controller.signal.aborted ? 'AbortError' : error?.name || 'Error';
      const message = timedOut ? 'Model request timed out' : safeError(error, provider);
      const attempt = transport.attempts.at(-1);
      if (attempt && !['http_error', 'completed'].includes(attempt.status))
        Object.assign(attempt, {status: controller.signal.aborted ? 'interrupted' : 'failed', error_type});
      const failure = rpc('model_failed', {request_id, error_type, error: message,
        duration_ms: Math.round(performance.now() - began), transport});
      try {await bounded(failure);} catch { /* Cota also finalizes outstanding observations when the run ends. */ }
      try {await bounded(notification('error'));} catch { /* The bridge may already be disconnected. */ }
      output.push({type: 'error', reason: controller.signal.aborted ? 'aborted' : 'error', error: {
        ...partial, role: 'assistant', content: [], cotaModelError: !signal?.aborted, api: model.api, provider: model.provider, model: model.id,
        stopReason: controller.signal.aborted ? 'aborted' : 'error',
        errorMessage: timedOut ? 'Model request timed out' : `Native model request failed (request=${request_id}, type=${error_type})`, timestamp: Date.now(),
      }});
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
    }
  })();
  return output;
}
