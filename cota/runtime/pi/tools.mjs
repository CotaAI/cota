/** Bind Pi's native tool definitions to a trusted Cota execution environment.
 * No shell/parser/edit implementation lives here; Operations are the backend seam.
 */
import { access, mkdir, mkdtemp, readFile, realpath, rm, stat } from 'node:fs/promises';
import { constants } from 'node:fs';
import { isAbsolute, join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { createHash } from 'node:crypto';
import {
  createReadToolDefinition, createWriteToolDefinition, createEditToolDefinition,
  createBashToolDefinition, createLocalBashOperations, detectSupportedImageMimeTypeFromFile,
  createGrepToolDefinition, createFindToolDefinition, createLsToolDefinition,
  createPowerShellToolDefinition, createLocalPowerShellOperations, getShellConfig, getPowerShellConfig,
} from '@earendil-works/pi-coding-agent';
import { within } from './skills.mjs';

function validateEnvironment(deploy, environment) {
  if (!['personal', 'service'].includes(deploy)) throw new Error('deploy must be personal or service');
  if (!environment || !['none', 'machine'].includes(environment.type))
    throw new Error('Unsupported execution environment; no machine fallback');
  if (deploy === 'service' && environment.type !== 'none')
    throw new Error('deploy: service cannot use the unrestricted machine environment');
  if (!['auto', 'bash', 'powershell', 'both'].includes(environment.shell ?? 'auto'))
    throw new Error('Invalid environment shell selection');
  const keys = environment.type === 'machine' ? ['type', 'workspace', 'timeout_seconds', 'shell'] : ['type'];
  if (Object.keys(environment).some(key => !keys.includes(key))) throw new Error('Unknown environment option');
  if (environment.type === 'machine' && (typeof environment.workspace !== 'string'
      || !isAbsolute(environment.workspace) || !Number.isFinite(environment.timeout_seconds)
      || environment.timeout_seconds <= 0)) throw new Error('Machine requires absolute workspace and positive timeout');
}

export async function createNativeTools({cwd = process.cwd(), pythonExecutable, uvExecutable, deploy = 'service', environment = {type: 'none'}}, resources, request, signal) {
  validateEnvironment(deploy, environment);
  // This worker never installs dependencies during a Bot turn. Pi handles the
  // search binary lookup itself; its native offline switch prevents downloads.
  process.env.PI_OFFLINE = '1';
  signal?.throwIfAborted();
  const machine = environment.type === 'machine';
  const workdir = machine ? environment.workspace : cwd;
  if (machine) await mkdir(workdir, {recursive: true});
  const {skills} = resources;
  const roots = [...new Set(skills.map(skill => skill.baseDir))];
  const definitions = [], unavailable = {};
  if (machine || skills.length) {
    const definition = createReadToolDefinition(workdir);
    if (!machine) definition.description += " Only files inside this Bot's discovered Skill directories are available.";
    definitions.push({...definition, execute: async (id, args, signal, onUpdate) => {
      let bytes, file, mimeType;
      async function checked(path) {
        const canonical = await realpath(path);
        if (!machine && !roots.some(root => within(root, canonical)))
          throw new Error('Read is outside the Bot Skill resources');
        if (!(await stat(canonical)).isFile()) throw new Error('Read requires a regular file');
        return canonical;
      }
      // Capture exactly the bytes Pi consumes, not a second post-read hash.
      const reader = createReadToolDefinition(workdir, {operations: {
        access: async path => { await checked(path); },
        readFile: async path => { file = await checked(path); bytes = await readFile(file); return bytes; },
        detectImageMimeType: async path => {
          mimeType = await detectSupportedImageMimeTypeFromFile(await checked(path));
          return mimeType;
        },
      }});
      const result = await reader.execute(id, args, signal, onUpdate);
      const owner = file && skills.filter(skill => within(skill.baseDir, file))
        .sort((a, b) => b.baseDir.length - a.baseDir.length)[0];
      let resource;
      if (owner && bytes && !result.isError) {
        const skill = skills.find(item => item.filePath === file);
        resource = {kind: skill ? 'skill' : 'reference', skill: owner.name, path: file,
          hash: 'sha256:' + createHash('sha256').update(bytes).digest('hex')};
        if (!mimeType) {
          const range = {};
          if (args.offset != null && args.offset !== 1) range.offset = args.offset;
          if (args.limit != null) range.limit = args.limit;
          if (result.details?.truncation?.truncated) range.truncated = true;
          if (Object.keys(range).length) resource.range = range;
        }
      }
      return {result, resource};
    }});
  }
  if (machine) {
    definitions.push(createWriteToolDefinition(workdir), createEditToolDefinition(workdir), createLsToolDefinition(workdir));
    // Probe public factories, rather than duplicating Pi's rg/fd resolution or
    // reaching into private modules. The empty directory contains no user data.
    const probeDir = await mkdtemp(join(tmpdir(), 'cota-pi-check-'));
    try {
      for (const [definition, args] of [
        [createGrepToolDefinition(workdir), {pattern: '.', path: probeDir}],
        [createFindToolDefinition(workdir), {pattern: '*', path: probeDir}],
      ]) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 3000);
        const probeSignal = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
        try {
          probeSignal.throwIfAborted();
          const result = await definition.execute('dependency-check', args, probeSignal);
          if (result.isError) throw new Error(result.content.filter(b => b.type === 'text').map(b => b.text).join('\n'));
          definitions.push(definition);
        } catch (error) {
          signal?.throwIfAborted();
          unavailable[definition.name] = controller.signal.aborted ? 'Dependency check timed out' : error.message;
        } finally { clearTimeout(timer); }
      }
    } finally { await rm(probeDir, {recursive: true, force: true}); }
    const selection = environment.shell ?? 'auto';
    for (const [name, config, factory, operations] of [
      ['bash', getShellConfig, createBashToolDefinition, createLocalBashOperations],
      ['powershell', getPowerShellConfig, createPowerShellToolDefinition, createLocalPowerShellOperations],
    ]) {
      if (!['auto', 'both', name].includes(selection)) continue;
      try {
        // Official platform selection: Pi 1.4 PowerShell supports Windows only.
        const {shell} = config();
        if (isAbsolute(shell)) await access(shell, constants.X_OK);
        const local = operations();
        definitions.push(factory(workdir, {exposeSessionEnvironment: false, operations: {
          exec(command, cwd, options) {
            const timeout = options.timeout ?? environment.timeout_seconds;
            if (!Number.isFinite(timeout) || timeout <= 0) throw new Error('Shell timeout must be positive and finite');
            return local.exec(command, cwd, {...options, timeout: Math.min(timeout, environment.timeout_seconds)});
          },
        }}));
      } catch (error) {
        if (selection !== 'auto') throw new Error(`Requested ${name} is unavailable: ${error.message}`);
        unavailable[name] = error.message;
      }
    }
  }
  // ToolDefinition.execute is Agent Core-compatible without an AgentSession.
  // Keep Pi's argument preparation, schemas and execution hints intact.
  const tools = definitions.map(definition => ({...definition, execute: async (toolCallId, args, signal, onUpdate) => {
    let result, resource;
    try {
      const value = await definition.execute(toolCallId, args, signal, onUpdate);
      ({result, resource} = definition.name === 'read' ? value : {result: value});
    } catch (error) {
      if (signal?.aborted) throw error;
      result = {content: [{type: 'text', text: error.message}], isError: true};
    }
    result = {...result, details: result.details ?? {}, isError: result.isError ?? false};
    // An unavailable Store is fatal, not a model-retryable ordinary tool error.
    await request('tool_result', {toolCallId, name: definition.name, args, result, ...(resource ? {resource} : {})});
    return result;
  }}));
  const guidelines = definitions.flatMap(definition => definition.promptGuidelines ?? []);
  const python = typeof pythonExecutable === 'string' && isAbsolute(pythonExecutable)
    ? ` Python executable: ${JSON.stringify(pythonExecutable)}.` : '';
  const uv = typeof uvExecutable === 'string'
    ? ` For Bot scripts with PEP 723 inline metadata (# /// script), use ${JSON.stringify(uvExecutable + ' run')} instead of the Python executable for automatic dependency isolation.` : '';
  const context = machine
    ? `Execution environment: machine. Bot directory: ${JSON.stringify(resolve(cwd))}. Working directory: ${JSON.stringify(workdir)}.${python}${uv} Relative tool paths use the working directory; a shell cd applies only to that command, not later tool calls. This is a starting directory, not a sandbox. Commands run on the deployment machine, not the chat user's device. Shell timeout limit: ${environment.timeout_seconds} seconds.`
    : 'Execution environment: none. read can only access the advertised Bot Skill resources. No user filesystem or shell is available.';
  return {tools, inventory: {available: tools.map(tool => tool.name), unavailable}, schemas: tools.map(tool => ({type: 'function', function: {
    name: tool.name, description: tool.description, parameters: tool.parameters,
  }})), prompt: '\n\n' + context + (guidelines.length ? '\n' + guidelines.join('\n') : '')};
}
