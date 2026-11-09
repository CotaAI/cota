/** Pi owns the loop; Cota owns context policy, tools, models and durable state. */
import { createSkillResources } from './skills.mjs';
import { createHttpTool } from './http.mjs';
import { createNativeTools } from './tools.mjs';
import { Agent } from '@earendil-works/pi-agent-core';
import piPackage from '@earendil-works/pi-agent-core/package.json' with {type: 'json'};
import { createAssistantMessageEventStream, getCurrentSystemPrompt } from '@earendil-works/pi-ai';

if (piPackage.version !== '1.4.0') throw new Error('Cota requires Pi Core 1.4.0; reinstall with npm ci');

const zeroUsage = () => ({input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
  cost: {input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0}});

export function assistantMessage(response, model) {
  const content = [];
  if (response.content) content.push({type: 'text', text: response.content});
  for (const call of response.tool_calls ?? []) {
    const block = {type: 'toolCall', id: call.id, name: call.function.name, arguments: {}};
    try {
      const args = JSON.parse(call.function.arguments || '{}');
      if (!args || Array.isArray(args) || typeof args !== 'object') throw new Error('Expected an object');
      block.arguments = args;
    } catch (error) {
      block.argumentsError = `Invalid JSON arguments: ${call.function.arguments}; ${error.message}`;
    }
    content.push(block);
  }
  return {role: 'assistant', content, api: model.api, provider: model.provider, model: model.id,
    usage: response.usage ?? zeroUsage(), timestamp: Date.now(),
    stopReason: response.finish_reason === 'length' ? 'length' :
      content.some(c => c.type === 'toolCall') ? 'toolUse' : 'stop'};
}

export async function runAgent(options, rpc, signal) {
  if (!Number.isInteger(options.maxIterations) || options.maxIterations < 1)
    throw new Error('maxIterations must be a positive integer');
  let turns = 0, limited = false, fatal;
  let schemas = [], latestAssistant;
  const pendingStarts = new Map();
  const model = {id: 'cota-configured-model', name: 'Cota model adapter',
    api: 'openai-completions', provider: 'cota', baseUrl: '', reasoning: false,
    input: ['text', 'image'], contextWindow: 128000, maxTokens: 4096,
    cost: {input: 0, output: 0, cacheRead: 0, cacheWrite: 0}};
  const request = async (method, payload) => {
    if (fatal) throw fatal;
    try { return await rpc(method, payload); }
    catch (error) { fatal = error; throw error; }
  };
  const record = async event => {
    const recorded = await request('event', {event});
    if (recorded?.assistantMessage && latestAssistant)
      Object.assign(latestAssistant, recorded.assistantMessage);
    return recorded;
  };
  const resources = await createSkillResources(options);
  const native = await createNativeTools(options, resources, request, signal);
  // Discovery notification, not a conversation event. Cota retains the catalog
  // as run metadata for Policy validation and later annotation.
  await request('skills_loaded', {skills: resources.skills, diagnostics: resources.diagnostics,
    ...(options.environment?.type === 'machine' ? {nativeTools: native.inventory} : {})});
  const http = createHttpTool();
  const localTools = [...native.tools, {...http, execute: async (toolCallId, args, signal, onUpdate) => {
    const result = await http.execute(toolCallId, args, signal, onUpdate);
    await request('tool_result', {toolCallId, name: http.name, args, result});
    return result;
  }}];
  const extensionTools = [{type: 'function', function: {
    name: http.name, description: http.description, parameters: http.parameters,
  }}];
  const toolsFor = definitions => definitions.map(({function: fn}) => localTools.find(tool => tool.name === fn.name) ?? ({
    name: fn.name, label: fn.name, description: fn.description ?? '', parameters: fn.parameters,
    execute: async (toolCallId, args) => {
      const result = await request('tool', {toolCallId, name: fn.name, args});
      return {...result, details: result.details ?? {}, isError: result.isError ?? false};
    },
  }));
  const agent = new Agent({
    initialState: {model, messages: options.messages},
    toolExecution: 'sequential',
    prepareRequest: async ({context}) => {
      const prepared = await request('prepare', {messages: context.messages, skillPrompt: resources.prompt, toolPrompt: native.prompt, nativeTools: native.schemas, extensionTools});
      schemas = prepared.tools;
      const tools = toolsFor(schemas);
      // prepareRequest changes the low-level loop's context, not Agent.state.
      // Keep the public snapshot (used by checkpoints) on the same projection.
      agent.state.messages = prepared.messages;
      agent.state.tools = tools;
      return {context: {messages: prepared.messages, tools}};
    },
    beforeToolCall: async ({toolCall, args}) => {
      if (fatal) throw fatal;
      const start = pendingStarts.get(toolCall.id);
      if (!start) throw new Error('Tool execution requires a start observation');
      // Pi's start event precedes schema conversion. Checkpoint the actual
      // validated arguments before allowing any tool side effect.
      await record({...start, args, requestedArgs: start.args});
      pendingStarts.delete(toolCall.id);
      if (localTools.some(tool => tool.name === toolCall.name)) {
        const permission = await request('authorize_tool', {toolCallId: toolCall.id, name: toolCall.name, args});
        if (!permission.allowed) return {block: true, reason: permission.reason};
      }
    },
    streamFn: async (_, context) => {
      const response = await request('model', {
        messages: context.messages, systemPrompt: getCurrentSystemPrompt(context.messages), tools: schemas,
      });
      const message = response._cota_message ?? assistantMessage(response, model);
      latestAssistant = message;
      const stream = createAssistantMessageEventStream();
      stream.push({type: 'done', reason: message.stopReason, message});
      return stream;
    },
    finishTurn: () => {
      turns++;
      if (fatal) throw fatal;
      if (turns >= options.maxIterations) {
        // A final text response at the limit is still a completed run.
        limited = agent.state.messages.at(-1)?.role === 'toolResult';
        return {action: 'end'};
      }
    },
  });
  agent.subscribe(async event => {
    if (event.type === 'tool_execution_start') {
      pendingStarts.set(event.toolCallId, event);
      return;
    }
    if (['message_end', 'tool_execution_end'].includes(event.type)) {
      // Unknown tools, invalid arguments and truncation never enter the hook.
      // They still get one start and one blocked result, using the proposal.
      if (event.type === 'tool_execution_end' && pendingStarts.has(event.toolCallId)) {
        await record(pendingStarts.get(event.toolCallId));
        pendingStarts.delete(event.toolCallId);
      }
      const recorded = await record(event);
      // Durable Cota identity survives repeated call IDs across runs. It is
      // context metadata, never a model/tool argument or inferred Skill owner.
      if (event.type === 'message_end' && event.message.role === 'toolResult' && recorded?.messageId) {
        Object.assign(event.message, {cotaEventId: recorded.messageId, timestamp: recorded.timestamp,
          cotaRunId: recorded.runId});
        if (recorded.resultEventId) event.message.cotaResultEventId = recorded.resultEventId;
      }
    }
  });
  const abort = () => agent.abort();
  signal?.addEventListener('abort', abort, {once: true});
  try {
    if (signal?.aborted) throw new Error('Aborted before start');
    await agent.continue();
    if (fatal) throw fatal;
    if (agent.state.errorMessage) throw new Error(agent.state.errorMessage);
    return {messages: agent.state.messages, status: limited ? 'limited' : 'completed'};
  } finally {
    signal?.removeEventListener('abort', abort);
  }
}
