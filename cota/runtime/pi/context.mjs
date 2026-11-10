/** Adapt Cota's event identities to Pi's public compaction APIs; no session files. */
import {getBuiltinProviders, getBuiltinModels} from '@earendil-works/pi-ai/providers/all';
import {estimateTokens, calculateContextTokens, findCutPoint, compact} from '@earendil-works/pi-coding-agent';

export function resolveContextModel(options = {}) {
  const id = options.id || 'cota-configured-model';
  const candidates = options.contextWindow ? [] : getBuiltinProviders().flatMap(p => getBuiltinModels(p)).filter(m => m.id === id);
  const contextWindow = options.contextWindow ?? (candidates.length ? Math.min(...candidates.map(m => m.contextWindow)) : 65536);
  const maxTokens = options.maxTokens ?? 4096;
  if (!Number.isInteger(contextWindow) || contextWindow < 2 || !Number.isInteger(maxTokens)
      || maxTokens < 1 || maxTokens >= contextWindow) throw new Error('Model context_window must exceed max_tokens');
  return {id, name: id, api: 'openai-completions', provider: 'cota', baseUrl: '', reasoning: false,
    input: ['text', 'image'], contextWindow, maxTokens,
    capacitySource: options.contextWindow ? 'configured' : candidates.length ? 'pi_catalog' : 'fallback',
    cost: {input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0}};
}

export function compactionSettings(model, options = {}) {
  const reserveTokens = options.reserve_tokens ?? Math.max(model.maxTokens, Math.min(16384, Math.floor(model.contextWindow / 4)));
  const keepRecentTokens = options.keep_recent_tokens ?? Math.min(20000, Math.floor((model.contextWindow - reserveTokens) / 2));
  if (!Number.isInteger(reserveTokens) || reserveTokens < model.maxTokens || reserveTokens >= model.contextWindow
      || !Number.isInteger(keepRecentTokens) || keepRecentTokens < 1 || keepRecentTokens >= model.contextWindow - reserveTokens)
    throw new Error('Invalid compaction budget: reserve_tokens must cover output; keep_recent_tokens must fit remaining context');
  return {enabled: true, reserveTokens, keepRecentTokens};
}

export function estimateRequest(messages, tools = []) {
  const sections = {system: 0, user: 0, assistant: 0, tool_results: 0,
    tool_definitions: tools.length ? Math.ceil(JSON.stringify(tools).length / 4) : 0};
  let images = 0, imageBytes = 0;
  for (const message of messages) {
    const section = message.role === 'toolResult' ? 'tool_results' : message.role;
    if (section in sections) sections[section] += estimateTokens(message);
    if (Array.isArray(message.content)) for (const block of message.content) {
      if (block.type === 'image') {
        images++;
        const data = block.data ?? '';
        imageBytes += Math.max(0, Math.floor(data.length * 3 / 4) - (data.endsWith('==') ? 2 : data.endsWith('=') ? 1 : 0));
      }
    }
    // Incoming attachments are hydrated by Cota only at the provider boundary.
    if (!Array.isArray(message.content)) for (const file of message.cotaAttachments ?? []) {
      if (file.mime_type?.startsWith('image/') && file.size <= 2 * 1024 * 1024) {
        images++; imageBytes += file.size;
        sections[section] += estimateTokens({role: 'user', content: [{type: 'image'}]});
      }
    }
  }
  const estimated = Object.values(sections).reduce((a, b) => a + b, 0);
  // Retained responses preceding a summary describe the old context and are stale.
  const boundary = messages.findLastIndex(m => m.cotaCompaction);
  const last = messages.findLastIndex((m, i) => i > boundary && m.role === 'assistant' && m.usage?.totalTokens > 0
    && (boundary < 0 || m.timestamp > messages[boundary].timestamp));
  // Previous usage includes old instructions, whose footprint is not a durable
  // fact. Reserve current system/tools conservatively so changed Policy cannot
  // hide behind an older, higher provider count. This may compact earlier.
  const instructionReserve = sections.system + sections.tool_definitions;
  const usage = last < 0 ? 0 : calculateContextTokens(messages[last].usage) + instructionReserve
    + messages.slice(last + 1).reduce((n, m) => n + estimateTokens(m), 0);
  return {estimated_tokens: estimated, budget_tokens: Math.max(estimated, usage),
    sections, images, image_bytes: imageBytes, usage_based_tokens: usage || null,
    instruction_reserve_tokens: last < 0 ? 0 : instructionReserve};
}

export async function compactContext(messages, model, settings, streamFn, signal) {
  signal?.throwIfAborted();
  const history = messages.filter(m => m.role !== 'system');
  const entries = history.map((message, i) => ({type: 'message', id: message.cotaEventId,
    parentId: i ? history[i - 1].cotaEventId : null,
    timestamp: new Date(message.timestamp ?? 0).toISOString(), message}));
  if (entries.some(e => !e.id)) throw new Error('Compaction requires durable Cota message identities');
  const cut = findCutPoint(entries, 0, entries.length, settings.keepRecentTokens);
  if (cut.firstKeptEntryIndex <= 0) throw new Error('Context cannot be compacted at a safe message boundary; narrow the task or increase context_window');
  const prefix = history.slice(0, cut.firstKeptEntryIndex);
  const fileOps = {read: new Set(), written: new Set(), edited: new Set()};
  for (const m of prefix) if (m.role === 'assistant') for (const b of m.content) {
    const field = {read: 'read', write: 'written', edit: 'edited'}[b.name];
    if (b.type === 'toolCall' && field && typeof b.arguments?.path === 'string') fileOps[field].add(b.arguments.path);
  }
  const historyEnd = cut.isSplitTurn ? cut.turnStartIndex : cut.firstKeptEntryIndex;
  const summaryStream = async (...args) => {
    // Imported histories can already exceed the provider window. Pi bounds
    // tool excerpts, but long user/assistant text must also fit the summary call.
    if (estimateRequest(args[1].messages).estimated_tokens > model.contextWindow - Math.min(2000, settings.reserveTokens))
      throw new Error('Pi summary input exceeds the available model budget; use a larger context_window or reduce imported history');
    const stream = await streamFn(...args);
    const response = await stream.result();
    if (!response.content?.some(b => b.type === 'text' && b.text?.trim()))
      throw new Error('Pi received an empty summary response');
    return stream;
  };
  const result = await compact({firstKeptEntryId: entries[cut.firstKeptEntryIndex].id,
    messagesToSummarize: history.slice(0, historyEnd),
    turnPrefixMessages: cut.isSplitTurn ? history.slice(cut.turnStartIndex, cut.firstKeptEntryIndex) : [],
    isSplitTurn: cut.isSplitTurn, tokensBefore: estimateRequest(messages).budget_tokens, fileOps, settings},
  model, undefined, undefined,
  'Preserve user constraints, speaker identities, confirmed decisions, exact project/file paths, verified outcomes, unresolved work and unknown external effects. Do not invent facts.',
  signal, 'off', summaryStream, undefined, {enabled: false, maxRetries: 0});
  signal?.throwIfAborted();
  if (!result.summary?.trim()) throw new Error('Pi returned an empty compaction summary');
  return {summary: result.summary, replaced_message_ids: prefix.map(m => m.cotaEventId),
    first_kept_id: result.firstKeptEntryId};
}
