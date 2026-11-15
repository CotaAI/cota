/** One invocation per Cota turn. No Pi session files; tools use the bound environment. */
import { createInterface } from 'node:readline';
import { runAgent } from './engine.mjs';
import { createSkillResources } from './skills.mjs';

async function execute(options, rpc, signal, notify) {
  if (options.operation === 'discover_skills') {
    const resources = await createSkillResources(options);
    return resources.skills.filter(skill => !skill.disableModelInvocation)
      .map(({name, description}) => ({name, description}));
  }
  const result = await runAgent(options, rpc, signal, notify);
  return {status: result.status, ...(result.hasFinalReply ? {hasFinalReply: true} : {}),
    ...(result.outputError ? {outputError: result.outputError} : {})};
}

const pending = new Map();
let nextId = 0, started = false;
const controller = new AbortController();
let writing = Promise.resolve();
// Every producer awaits the callback: a slow bridge applies backpressure to
// streamed notifications rather than growing an unbounded stdout write buffer.
const send = value => {
  const line = JSON.stringify(value) + '\n';
  writing = writing.then(() => new Promise((resolve, reject) => {
    process.stdout.write(line, error => error ? reject(error) : resolve());
  }));
  return writing;
};
const notify = (method, payload) => send({type: 'notification', method, payload});
const reportError = (error, protocol = false) => send({type: 'error',
  error: protocol ? 'Invalid Pi worker protocol message' : error.message,
  code: protocol ? 'protocol_error' : controller.signal.aborted ? 'cancelled' : error.code ?? 'execution_failed',
  phase: protocol ? 'bridge' : error.phase ?? 'execution',
  error_type: protocol ? 'PiBridgeError' : controller.signal.aborted ? 'AbortError' : error.error_type ?? error.name,
  ...(error.request_id ? {request_id: error.request_id} : {}),
});
const rpc = (method, payload) => new Promise((resolve, reject) => {
  const id = ++nextId;
  pending.set(id, {resolve, reject});
  send({type: 'request', id, method, payload}).catch(error => {pending.delete(id); reject(error);});
});
const input = createInterface({input: process.stdin});
// Do not bypass Pi's cancellation path when a supervisor terminates this worker.
process.on('SIGTERM', () => input.close());
process.on('SIGINT', () => input.close());
input.on('line', async line => {
  try {
    const message = JSON.parse(line);
    if (message.type === 'response') {
      const request = pending.get(message.id);
      if (!request) throw new Error('Unknown response id');
      pending.delete(message.id);
      if (message.error) request.reject(new Error(message.error));
      else request.resolve(message.result);
    } else if (message.type === 'cancel') {
      controller.abort();
    } else if (message.type === 'start' && !started && message.protocol === 1) {
      started = true;
      execute(message.options, rpc, controller.signal, notify).then(
        result => send({type: 'done', result}),
        error => {process.exitCode = 1; return reportError(error);},
      ).finally(() => input.close());
    } else throw new Error('Invalid protocol message');
  } catch (error) {
    process.exitCode = 1;
    await reportError(error, true);
    input.close();
  }
});
input.on('close', () => {
  controller.abort();
  for (const {reject} of pending.values()) reject(new Error('Cota bridge disconnected'));
  pending.clear();
});
