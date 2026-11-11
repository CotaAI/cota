/** Pi owns the loop; Cota owns context policy, tools, models and durable state. */
import { createSkillResources } from './skills.mjs';
import {nativeModel, nativeStream} from './model.mjs';
import {projectImageContext, hydrateImageRefs} from './image-context.mjs';
import { createHttpTool } from './http.mjs';
import { createNativeTools } from './tools.mjs';
import { createSendFilesTool } from './files.mjs';
import {resolveContextModel, compactionSettings, estimateRequest, compactContext, exceedsImageBudget} from './context.mjs';
import {shouldCompact} from '@earendil-works/pi-coding-agent';
import { Agent } from '@earendil-works/pi-agent-core';
import piPackage from '@earendil-works/pi-agent-core/package.json' with {type: 'json'};
import { createAssistantMessageEventStream, createInitialSystemMessage, getCurrentSystemPrompt,
  toToolDeclaration } from '@earendil-works/pi-ai';

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

export async function runAgent(options, rpc, signal, notify = async () => {}) {
  if (!Number.isInteger(options.maxIterations) || options.maxIterations < 1)
    throw new Error('maxIterations must be a positive integer');
  let turns = 0, limited = false, fatal;
  let schemas = [], latestAssistant;
  const pendingStarts = new Map();
  const model = options.provider ? nativeModel(resolveContextModel(options.model), options.provider) : resolveContextModel(options.model);
  let requestMessages;
  const settings = compactionSettings(model, options.compaction);
  let contextBudget;
  const request = async (method, payload) => {
    if (fatal) throw fatal;
    try { return await rpc(method, payload); }
    catch (error) { fatal = error; throw error; }
  };
  const record = async event => {
    const recorded = await request('event', {event});
    if (recorded?.assistantMessage && latestAssistant)
      Object.assign(latestAssistant, options.provider ? Object.fromEntries(Object.entries(recorded.assistantMessage)
        .filter(([key]) => ['cotaEventId', 'timestamp', 'cotaRunId'].includes(key))) : recorded.assistantMessage);
    return recorded;
  };
  const resources = await createSkillResources(options);
  const native = await createNativeTools(options, resources, request, signal);
  // Discovery notification, not a conversation event. Cota retains the catalog
  // as run metadata for Policy validation and later annotation.
  await request('skills_loaded', {skills: resources.skills, diagnostics: resources.diagnostics,
    ...(options.environment?.type === 'machine' ? {nativeTools: native.inventory} : {})});
  const http = createHttpTool();
  const files = createSendFilesTool(async (toolCallId, args) => {
    const result = await request('send_files', {toolCallId, args});
    await request('tool_result', {toolCallId, name: 'send_files', args, result});
    return result;
  });
  const localTools = [...native.tools, {...http, execute: async (toolCallId, args, signal, onUpdate) => {
    const result = await http.execute(toolCallId, args, signal, onUpdate);
    await request('tool_result', {toolCallId, name: http.name, args, result});
    return result;
  }}, files];
  const extensionTools = [http, files].map(tool => ({type: 'function', function: {
    name: tool.name, description: tool.description, parameters: tool.parameters,
  }}));
  const toolsFor = definitions => definitions.map(({function: fn}) => localTools.find(tool => tool.name === fn.name) ?? ({
    name: fn.name, label: fn.name, description: fn.description ?? '', parameters: fn.parameters,
    execute: async (toolCallId, args) => {
      const result = await request('tool', {toolCallId, name: fn.name, args});
      return {...result, details: result.details ?? {}, isError: result.isError ?? false};
    },
  }));
  const agent = new Agent({
    initialState: {model, messages: options.messages.filter(message => !message.cotaDeferred)},
    toolExecution: 'sequential',
    prepareRequest: async ({context}) => {
      const prepare = async messages => {
        const prepared = await request('prepare', {native: !!options.provider, skillPrompt: resources.prompt,
          toolPrompt: native.prompt, nativeTools: native.schemas, extensionTools});
        native.imageResources.register(prepared.imageResources);
        if (!options.provider) return {...prepared, messages: prepared.messages.filter(message => !message.cotaDeferred)};
        return {...prepared, messages: [...(prepared.systemPrompt ? [{role: 'system', content: prepared.systemPrompt, timestamp: 0}] : []),
          ...messages.filter(message => message.role !== 'system' && !message.cotaDeferred)]};
      };
      let prepared = await prepare(context.messages);
      for (let attempt = 0; ; attempt++) {
        requestMessages = projectImageContext(await hydrateImageRefs(prepared.messages, native.imageResources, settings), native.imageResources);
        contextBudget = {...estimateRequest(requestMessages, prepared.tools, model), context_window: model.contextWindow,
          capacity_source: model.capacitySource, reserve_tokens: settings.reserveTokens,
          max_request_bytes: settings.maxRequestBytes, max_images: settings.maxImages,
          max_image_bytes: settings.maxImageBytes};
        const fixed = estimateRequest(prepared.messages.filter(m => m.role === 'system'), prepared.tools, model);
        if (fixed.budget_tokens >= model.contextWindow - settings.reserveTokens)
          throw new Error('System prompt and tool definitions exceed the model budget; reduce guidance or increase context_window');
        if (fixed.serialized_bytes >= settings.maxRequestBytes - Math.min(65536, Math.floor(settings.maxRequestBytes / 4)))
          throw new Error('System prompt and tool definitions exceed the byte budget; reduce guidance or increase compaction.max_request_bytes');
        // Projection has already omitted historical pixels. The remaining
        // images are active input, so compaction must not hide an over-limit
        // user input or split its current comparison batch to make it fit.
        if (exceedsImageBudget(contextBudget, settings))
          throw new Error('Current user input/tool batch exceeds the image budget; use fewer/smaller images or increase compaction.max_images/max_image_bytes');
        if (!shouldCompact(contextBudget.budget_tokens, model.contextWindow, settings)
            && contextBudget.serialized_bytes <= settings.maxRequestBytes) break;
        if (attempt >= 2) throw new Error('Context still exceeds the Pi token/byte/image budget after compaction; narrow the task or increase the context budget');
        const summaryStream = async (_model, summaryContext) => {
          if (options.provider) {
            const stream = await nativeStream({model, provider: options.provider, context: summaryContext,
              purpose: 'compaction', maxTokens: Math.min(2000, settings.reserveTokens), rpc: request, signal});
            const message = await stream.result();
            if (['error', 'aborted'].includes(message.stopReason)) {
              fatal ??= Object.assign(new Error(message.errorMessage || 'Native summary failed'),
                message.cotaModelError ? {code: 'model_error', error_type: message.cotaErrorType} : {});
              throw fatal;
            }
            return stream;
          }
          const response = await request('summarize', {messages: summaryContext.messages,
            systemPrompt: getCurrentSystemPrompt(summaryContext.messages), maxTokens: Math.min(2000, settings.reserveTokens)});
          const message = assistantMessage(response, model);
          const stream = createAssistantMessageEventStream();
          stream.push({type: 'done', reason: message.stopReason, message});
          return stream;
        };
        const result = await compactContext(requestMessages, model, settings, summaryStream, signal, prepared.tools);
        const committed = await request('compact', result);
        native.imageResources.register(committed.imageResources);
        prepared = await prepare(committed.messages);
      }
      schemas = prepared.tools;
      const tools = toolsFor(schemas);
      // Pi 1.4 providers read callable schemas from transcript declarations,
      // not AgentContext.tools (which only binds executors). prepareRequest
      // runs after Core's automatic declaration step, so rebuilding the system
      // prompt must also declare this request's exact, current tool loadout.
      const system = createInitialSystemMessage(getCurrentSystemPrompt(prepared.messages), tools.map(toToolDeclaration));
      prepared.messages = [...(system ? [system] : []), ...prepared.messages.filter(message => message.role !== 'system')];
      requestMessages = [...(system ? [system] : []), ...requestMessages.filter(message => message.role !== 'system')];
      // prepareRequest changes the low-level loop's context, not Agent.state.
      // Keep checkpoints on the raw prepared history. Only transformContext
      // selects request pixels; tool results and original images stay intact.
      agent.state.messages = prepared.messages;
      agent.state.tools = tools;
      return {context: {messages: prepared.messages, tools}};
    },
    transformContext: () => requestMessages,
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
    streamFn: async (_, context, streamOptions) => {
      if (options.provider) return nativeStream({model, provider: options.provider, context, contextBudget,
        rpc: request, signal: streamOptions?.signal ?? signal, notify, onComplete: message => {latestAssistant = message;}});
      const response = await request('model', {
        messages: context.messages, systemPrompt: getCurrentSystemPrompt(context.messages), tools: schemas, contextBudget,
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
    if (event.type === 'message_end' && event.message.role === 'assistant'
        && ['error', 'aborted'].includes(event.message.stopReason)) {
      fatal ??= Object.assign(new Error(event.message.errorMessage || 'Pi model request interrupted'),
        options.provider && event.message.cotaModelError && !signal?.aborted
          ? {code: 'model_error', error_type: event.message.cotaErrorType} : {});
      throw fatal;
    }
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
