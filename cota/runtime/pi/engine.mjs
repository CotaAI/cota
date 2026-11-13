/** Pi owns the loop; Cota owns context policy, tools, models and durable state. */
import { createSkillResources } from './skills.mjs';
import {nativeModel, nativeStream} from './model.mjs';
import {hasToolProtocol} from './output.mjs';
import {projectImageContext, hydrateImageRefs} from './image-context.mjs';
import { createWebFetchTool } from './web-fetch.mjs';
import { createImageGenerateTool } from './image-generate.mjs';
import { createImageUnderstandTool } from './image-understand.mjs';
import { createNativeTools } from './tools.mjs';
import { createSendFilesTool } from './files.mjs';
import {resolveContextModel, compactionSettings, estimateRequest, compactContext, exceedsImageBudget} from './context.mjs';
import {shouldCompact, convertToLlm} from '@earendil-works/pi-coding-agent';
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
  const reserved = options.wrapUpIterations === undefined
    ? options.maxIterations >= 10 ? Math.min(2, options.maxIterations - 1) : 0
    : options.wrapUpIterations;
  if (!Number.isInteger(reserved) || reserved < 0 || reserved >= options.maxIterations)
    throw new Error('wrapUpIterations must be an integer from 0 to maxIterations - 1');
  let turns = 0, limited = false, wrappingUp = false, hasFinalReply = false, fatal;
  let repairRequested = false, outputRejected = false;
  let overflowPending = false, overflowRecovered = false, forceCompaction = false;
  const executionBudget = () => {
    const remaining = options.maxIterations - turns;
    return {total: options.maxIterations, used: turns, remaining, reserved,
      phase: reserved > 0 && remaining <= reserved ? 'wrap_up'
        : remaining <= Math.max(reserved + 2, Math.ceil(options.maxIterations / 5)) ? 'warning' : 'working'};
  };
  const budgetGuidance = budget => {
    if (budget.phase === 'working' || options.maxIterations < 10 && !reserved) return '';
    const guidance = [`Execution decisions: ${budget.used}/${budget.total} used; ${budget.remaining} remaining; ${budget.reserved} reserved for final text.`];
    if (budget.phase === 'warning') guidance.push('Finish necessary verification and delivery of existing work. Stop optional polishing and new branches; preserve completed work and unresolved issues.');
    if (budget.phase === 'wrap_up') guidance.push('No tool calls are available. Reply now using committed evidence: state completed work, remaining or blocked items, and whether files were actually sent. Say clearly if unfinished. Do not claim success or background work that did not happen. Describe task progress rather than internal decision accounting.');
    return `\n\n<execution_budget phase="${budget.phase}">\n${guidance.join('\n')}\n</execution_budget>`;
  };
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
  const acceptAssistant = async message => {
    if (contextBudget) message.cotaImageProjection = contextBudget.image_projection;
    if (hasToolProtocol(message)) {
      await request('reject_output', {error_type: 'ToolProtocolText'});
      // The raw response has been retained in diagnostics. Pi must see no
      // proposed calls from this invalid batch, including structured ones.
      message = {...message, content: [], stopReason: 'stop', cotaOutputError: true};
    }
    latestAssistant = message;
    return message;
  };
  const resources = await createSkillResources(options);
  const native = await createNativeTools(options, resources, request, signal);
  // Discovery notification, not a conversation event. Cota retains the catalog
  // as run metadata for Policy validation and later annotation.
  await request('skills_loaded', {skills: resources.skills, diagnostics: resources.diagnostics,
    ...(options.environment?.type === 'machine' ? {nativeTools: native.inventory} : {})});
  const webFetch = createWebFetchTool();
  const imageGen = options.imageGenerate ? createImageGenerateTool(options.imageGenerate) : null;
  const imageUnd = options.imageUnderstanding ? createImageUnderstandTool(options.imageUnderstanding) : null;
  const files = createSendFilesTool(async (toolCallId, args) => {
    const result = await request('send_files', {toolCallId, args});
    await request('tool_result', {toolCallId, name: 'send_files', args, result});
    return result;
  }, options.fileLimits);
  const wrapExtension = tool => ({...tool, execute: async (toolCallId, args, signal, onUpdate) => {
    const result = await tool.execute(toolCallId, args, signal, onUpdate);
    await request('tool_result', {toolCallId, name: tool.name, args, result});
    return result;
  }});
  const imageExtensions = [imageGen, imageUnd].filter(Boolean);
  const localTools = [...native.tools, wrapExtension(webFetch), ...imageExtensions.map(wrapExtension), files];
  const extensionTools = [webFetch, ...imageExtensions, files].map(tool => ({type: 'function', function: {
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
        const budget = executionBudget();
        const prepared = await request('prepare', {native: !!options.provider, skillPrompt: resources.prompt,
          toolPrompt: native.prompt, nativeTools: native.schemas, extensionTools, executionBudget: budget});
        native.imageResources.register(prepared.imageResources);
        if (budget.phase === 'wrap_up') {wrappingUp = true; limited = true;}
        const source = options.provider ? messages : prepared.messages;
        const systemPrompt = prepared.systemPrompt ?? getCurrentSystemPrompt(source);
        let history = [...(systemPrompt ? [{role: 'system', content: systemPrompt, timestamp: 0}] : []),
          ...source.filter(message => message.role !== 'system')];
        history = history.filter(message => !message.cotaDeferred && !message.cotaOutputError
          && !(message.role === 'assistant' && !message.content.some(block => block.type === 'toolCall')
            && hasToolProtocol(message)));
        const guidance = budgetGuidance(budget) + (repairRequested
          ? '\nThe previous response was invalid tool protocol text and was not delivered or executed. Give a normal text-only final summary of committed results and unresolved work; do not emit protocol markup or propose another tool call.' : '');
        return {...prepared, messages: history, runtimeContext: [prepared.runtimeContext, guidance].filter(Boolean).join('\n\n')};
      };
      // Request-local custom content never enters Agent.state or Cota facts.
      // Pi's public converter maps it to user for every provider uniformly.
      const projectRequest = (messages, guidance) => guidance ? [...messages, {
        role: 'custom', customType: 'cota.runtime_context', display: false, timestamp: 0,
        content: `<runtime_context>\n${guidance}\n</runtime_context>`,
      }] : messages;
      let prepared = await prepare(context.messages);
      for (let attempt = 0; ; attempt++) {
        const projected = wrappingUp
          ? projectImageContext(prepared.messages, native.imageResources, {textOnly: true})
          : projectImageContext(await hydrateImageRefs(prepared.messages, native.imageResources, settings), native.imageResources);
        requestMessages = projectRequest(projected, prepared.runtimeContext);
        contextBudget = {...estimateRequest(convertToLlm(requestMessages), prepared.tools, model), context_window: model.contextWindow,
          capacity_source: model.capacitySource, reserve_tokens: settings.reserveTokens,
          trigger_tokens: settings.triggerTokens, keep_recent_tokens: settings.keepRecentTokens,
          max_request_bytes: settings.maxRequestBytes, max_images: settings.maxImages,
          max_image_bytes: settings.maxImageBytes, execution: executionBudget()};
        const fixed = estimateRequest(convertToLlm(requestMessages.filter(m => m.role === 'system' || m.role === 'custom')), prepared.tools, model);
        if (fixed.budget_tokens >= settings.triggerTokens)
          throw new Error('System prompt, tool definitions and runtime context exceed the working budget; reduce guidance or increase compaction.trigger_tokens');
        if (fixed.serialized_bytes >= settings.maxRequestBytes - Math.min(65536, Math.floor(settings.maxRequestBytes / 4)))
          throw new Error('System prompt and tool definitions exceed the byte budget; reduce guidance or increase compaction.max_request_bytes');
        // Projection has already omitted historical pixels. The remaining
        // images are active input, so compaction must not hide an over-limit
        // user input or split its current comparison batch to make it fit.
        if (exceedsImageBudget(contextBudget, settings))
          throw new Error('Current user input/tool batch exceeds the image budget; use fewer/smaller images or increase compaction.max_images/max_image_bytes');
        if (!forceCompaction && !shouldCompact(contextBudget.budget_tokens, settings.triggerTokens + settings.reserveTokens, settings)
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
        const retention = forceCompaction ? {...settings, keepRecentTokens: Math.min(settings.keepRecentTokens,
          Math.max(1, Math.floor(contextBudget.estimated_tokens / 2)))} : settings;
        const result = await compactContext(projected, model, retention, summaryStream, signal, prepared.tools);
        const committed = await request('compact', {...result,
          reason: forceCompaction ? 'overflow' : contextBudget.serialized_bytes > settings.maxRequestBytes ? 'bytes' : 'threshold',
          tokens_before: contextBudget.budget_tokens});
        forceCompaction = false;
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
      // Keep checkpoints on raw history. Only transformContext selects request
      // pixels and adds ephemeral guidance; original tool evidence stays intact.
      agent.state.messages = prepared.messages;
      agent.state.tools = tools;
      return {context: {messages: prepared.messages, tools}};
    },
    transformContext: () => requestMessages,
    convertToLlm,
    beforeToolCall: async ({toolCall, args}) => {
      if (fatal) throw fatal;
      const start = pendingStarts.get(toolCall.id);
      if (!start) throw new Error('Tool execution requires a start observation');
      // Pi's start event precedes schema conversion. Checkpoint the actual
      // validated arguments before allowing any tool side effect.
      await record({...start, args, requestedArgs: start.args});
      pendingStarts.delete(toolCall.id);
      if (wrappingUp) return {block: true, reason: 'Execution budget is reserved for the final text reply; no tool side effects are allowed'};
      if (localTools.some(tool => tool.name === toolCall.name)) {
        const permission = await request('authorize_tool', {toolCallId: toolCall.id, name: toolCall.name, args});
        if (!permission.allowed) return {block: true, reason: permission.reason};
      }
    },
    streamFn: async (_, context, streamOptions) => {
      if (options.provider) return nativeStream({model, provider: options.provider, context, contextBudget,
        ...(wrappingUp ? {toolChoice: 'none'} : {}),
        rpc: request, signal: streamOptions?.signal ?? signal, notify, onComplete: acceptAssistant});
      const response = await request('model', {
        messages: context.messages, systemPrompt: getCurrentSystemPrompt(context.messages), tools: schemas, contextBudget,
        ...(wrappingUp ? {toolChoice: 'none'} : {}),
      });
      const message = await acceptAssistant(response._cota_message ?? assistantMessage(response, model));
      const stream = createAssistantMessageEventStream();
      stream.push({type: 'done', reason: message.stopReason, message});
      return stream;
    },
    finishTurn: ({message}) => {
      turns++;
      if (fatal) throw fatal;
      if (message.cotaOutputError) {
        if (wrappingUp && !repairRequested && turns < options.maxIterations) {
          repairRequested = true;
          return {action: 'continue'};
        }
        outputRejected = true;
        return {action: 'end'};
      }
      if (turns >= options.maxIterations) {
        // A final text response at the limit is still a completed run.
        limited ||= agent.state.messages.at(-1)?.role === 'toolResult';
        return {action: 'end'};
      }
    },
  });
  agent.subscribe(async event => {
    if (event.type === 'message_end' && event.message.cotaOutputError) return;
    if (event.type === 'message_end' && event.message.role === 'assistant'
        && ['error', 'aborted'].includes(event.message.stopReason)) {
      // Failed requests are diagnostic evidence, never bot/tool facts. Pi ends
      // this invocation; one continuation may compact before requesting again.
      if (event.message.cotaContextOverflow && !overflowRecovered && !wrappingUp
          && turns < options.maxIterations - 1 && !signal?.aborted) {
        overflowPending = true;
        return;
      }
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
      if (wrappingUp && event.type === 'message_end' && event.message.role === 'assistant'
          && event.message.stopReason === 'stop'
          && !event.message.content.some(block => block.type === 'toolCall')
          && event.message.content.some(block => block.type === 'text' && block.text.trim()))
        hasFinalReply = true; // Only after the durable reply acknowledgment.
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
    if (overflowPending) {
      overflowRecovered = true;
      forceCompaction = true;
      agent.state.messages = agent.state.messages.filter(message => !message.cotaContextOverflow);
      await agent.continue();
    }
    if (fatal) throw fatal;
    if (agent.state.errorMessage) throw new Error(agent.state.errorMessage);
    return {messages: agent.state.messages, status: limited ? 'limited' : outputRejected ? 'failed' : 'completed', hasFinalReply,
      ...(outputRejected ? {outputError: 'invalid_model_output'} : {})};
  } finally {
    signal?.removeEventListener('abort', abort);
  }
}
