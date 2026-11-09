/** One invocation per Cota turn. No Pi session files; tools use the bound environment. */
import { createInterface } from 'node:readline';
import { runAgent } from './engine.mjs';
import { createSkillResources } from './skills.mjs';

async function execute(options, rpc, signal) {
  if (options.operation === 'discover_skills') {
    const resources = await createSkillResources(options);
    return resources.skills.filter(skill => !skill.disableModelInvocation)
      .map(({name, description}) => ({name, description}));
  }
  return runAgent(options, rpc, signal);
}

const pending = new Map();
let nextId = 0, started = false;
const controller = new AbortController();
const send = value => process.stdout.write(JSON.stringify(value) + '\n');
const rpc = (method, payload) => new Promise((resolve, reject) => {
  const id = ++nextId;
  pending.set(id, {resolve, reject});
  send({type: 'request', id, method, payload});
});
const input = createInterface({input: process.stdin});
// Do not bypass Pi's cancellation path when a supervisor terminates this worker.
process.on('SIGTERM', () => input.close());
process.on('SIGINT', () => input.close());
input.on('line', line => {
  try {
    const message = JSON.parse(line);
    if (message.type === 'response') {
      const request = pending.get(message.id);
      if (!request) throw new Error('Unknown response id');
      pending.delete(message.id);
      if (message.error) request.reject(new Error(message.error));
      else request.resolve(message.result);
    } else if (message.type === 'start' && !started && message.protocol === 1) {
      started = true;
      execute(message.options, rpc, controller.signal).then(
        result => send({type: 'done', result}),
        error => {send({type: 'error', error: error.message}); process.exitCode = 1;},
      ).finally(() => input.close());
    } else throw new Error('Invalid protocol message');
  } catch (error) {
    send({type: 'error', error: error.message});
    process.exit(1);
  }
});
input.on('close', () => {
  controller.abort();
  for (const {reject} of pending.values()) reject(new Error('Cota bridge disconnected'));
  pending.clear();
});
