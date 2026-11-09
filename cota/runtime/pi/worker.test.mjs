import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { runAgent } from './engine.mjs';

const user = {role: 'user', content: 'do it', timestamp: 1};

test('service rejects machine binding before creating directories or invoking Pi', async () => {
  const {mkdtemp, access, rm} = await import('node:fs/promises');
  const {tmpdir} = await import('node:os');
  const {join} = await import('node:path');
  const {createNativeTools} = await import('./tools.mjs');
  const root = await mkdtemp(join(tmpdir(), 'cota-deploy-'));
  const workspace = join(root, 'never-created');
  try {
    for (const deploy of ['service', 'local', 'host', 'remote', null]) {
      await assert.rejects(createNativeTools({deploy,
        environment: {type: 'machine', workspace, timeout_seconds: 1}},
      {skills: []}, async () => { throw new Error('unexpected RPC'); }), /deploy|service/);
    }
    await assert.rejects(access(workspace));
  } finally { await rm(root, {recursive: true, force: true}); }
});
const schema = {type: 'function', function: {name: 'act', description: 'act', parameters: {
  type: 'object', properties: {n: {type: 'number'}}, required: ['n']}}};
const call = (id, args = '{"n":1}') => ({id, type: 'function', function: {name: 'act', arguments: args}});

function harness(responses, tool = async () => ({content: [{type: 'text', text: 'ok'}]})) {
  const events = [], calls = [], contexts = [];
  return {events, calls, contexts, rpc: async (method, payload) => {
    if (method === 'skills_loaded') return {};
    if (method === 'prepare') return {messages: payload.messages, tools: [schema]};
    if (method === 'model') { contexts.push(payload); return responses.shift(); }
    if (method === 'tool') {calls.push(payload); return tool(payload);}
    if (method === 'event') {events.push(payload.event); return {};}
    throw new Error(method);
  }};
}

test('real Pi loop validates tools, records artifacts and continues', async () => {
  const h = harness([{tool_calls: [call('a')]}, {content: 'done'}]);
  const result = await runAgent({messages: [user], maxIterations: 3}, h.rpc);
  assert.equal(result.status, 'completed');
  assert.equal(h.calls.length, 1);
  assert.equal(h.contexts.length, 2);
  assert.equal(result.messages.at(-1).content[0].text, 'done');
  assert(h.events.some(e => e.type === 'message_end' && e.message.role === 'toolResult'));
});

test('invalid arguments never reach Python tools', async () => {
  const h = harness([{tool_calls: [call('a', '{"n":"bad"}')]}, {content: 'done'}]);
  await runAgent({messages: [user], maxIterations: 3}, h.rpc);
  assert.equal(h.calls.length, 0);
  assert(h.events.some(e => e.type === 'message_end' && e.message.isError));
});

test('a clarification is a plain final answer and does not implicitly suppress tool calls', async () => {
  const question = 'Which city would you like the weather for?';
  const h = harness([{tool_calls: [call('a'), call('b')]}, {content: question}], async () => ({
    content: [{type: 'text', text: 'A city is required'}],
  }));
  const result = await runAgent({messages: [user], maxIterations: 3}, h.rpc);
  assert.equal(result.status, 'completed');
  assert.equal(h.calls.length, 2);
  assert.equal(h.contexts.length, 2);
  assert.equal(result.messages.filter(m => m.role === 'toolResult').length, 2);
  assert.equal(result.messages.at(-1).content[0].text, question);
});

test('iteration limit stops the real loop', async () => {
  const h = harness([{tool_calls: [call('a')]}]);
  const result = await runAgent({messages: [user], maxIterations: 1}, h.rpc);
  assert.equal(result.status, 'limited');
  assert.equal(h.contexts.length, 1);
});

test('failed durable acknowledgment prevents tool side effects', async () => {
  const h = harness([{tool_calls: [call('a')]}]);
  const rpc = async (method, payload) => {
    if (method === 'event' && payload.event.type === 'message_end') throw new Error('store unavailable');
    return h.rpc(method, payload);
  };
  await assert.rejects(runAgent({messages: [user], maxIterations: 3}, rpc), /store unavailable/);
  assert.equal(h.calls.length, 0);
});

test('prepared context replaces the persisted projection, including compaction', async () => {
  const h = harness([{content: 'done'}]);
  const rpc = async (method, payload) => {
    if (method === 'skills_loaded') return {};
    if (method === 'prepare') return {
      messages: [{role: 'system', content: 'current policy', timestamp: 1},
                 {role: 'user', content: 'summary and current input', timestamp: 1}], tools: []};
    return h.rpc(method, payload);
  };
  const result = await runAgent({messages: [user], maxIterations: 3}, rpc);
  assert.equal(result.messages[0].content, 'current policy');
  assert.equal(result.messages[1].content, 'summary and current input');
  assert.equal(result.messages.length, 3);
});

function httpHarness({advertise = true, allowed = true, recordFailure = false, args = {url: 'http://127.0.0.1'}} = {}) {
  const records = [], authorizations = [], contexts = [], preparations = [], events = [], order = [];
  const responses = [{tool_calls: [{id: 'http-1', type: 'function', function: {
    name: 'http_request', arguments: JSON.stringify(args),
  }}]}, {content: 'The HTTP request could not be completed.'}];
  return {records, authorizations, contexts, preparations, events, order, rpc: async (method, payload) => {
    order.push(method);
    if (method === 'skills_loaded') return {};
    if (method === 'prepare') {
      preparations.push(payload);
      return {messages: payload.messages, tools: advertise ? payload.extensionTools : []};
    }
    if (method === 'model') { contexts.push(payload); return responses.shift(); }
    if (method === 'authorize_tool') {
      authorizations.push(payload); return {allowed, reason: 'HTTP disabled by policy'};
    }
    if (method === 'tool_result') {
      records.push(payload);
      if (recordFailure) throw new Error('HTTP result store unavailable');
      return {};
    }
    if (method === 'event') { events.push(payload.event); return {}; }
    // Native HTTP must never fall back to a Python/custom-tool RPC.
    throw new Error(`Unexpected HTTP engine RPC: ${method}`);
  }};
}

test('native HTTP tool is validated, authorized, recorded and returned to the next Pi model request', async () => {
  const h = httpHarness();
  const result = await runAgent({messages: [user], maxIterations: 3}, h.rpc);
  assert.equal(result.status, 'completed');
  assert.deepEqual(h.preparations[0].extensionTools.map(schema => schema.function.name), ['http_request']);
  assert.equal(h.contexts[0].tools[0].function.parameters.properties.timeout_seconds.maximum, 60);
  assert.equal(h.authorizations.length, 1);
  assert.deepEqual(h.authorizations[0], {toolCallId: 'http-1', name: 'http_request', args: {url: 'http://127.0.0.1'}});
  assert.equal(h.records.length, 1);
  const recorded = h.records[0];
  assert.equal(recorded.name, 'http_request');
  assert.equal(recorded.result.isError, true);
  assert.match(recorded.result.content[0].text, /Blocked URL/);
  assert.deepEqual(recorded.result.details, {error: 'Blocked URL (private/reserved IP)'});
  assert.equal(h.contexts.length, 2);
  const nextResult = h.contexts[1].messages.find(message => message.role === 'toolResult');
  assert.equal(nextResult.toolName, 'http_request');
  assert.equal(nextResult.toolCallId, 'http-1');
  assert.equal(nextResult.isError, true);
  assert.deepEqual(nextResult.content, recorded.result.content);
  assert.deepEqual(nextResult.details, recorded.result.details);
  assert(h.order.indexOf('authorize_tool') < h.order.indexOf('tool_result'));
  assert(h.order.indexOf('tool_result') < h.order.lastIndexOf('model'));
});

test('native HTTP durable result acknowledgment failure prevents another model request', async () => {
  const h = httpHarness({recordFailure: true});
  await assert.rejects(runAgent({messages: [user], maxIterations: 3}, h.rpc), /HTTP result store unavailable/);
  assert.equal(h.authorizations.length, 1);
  assert.equal(h.records.length, 1);
  assert.equal(h.contexts.length, 1);
});

test('policy can omit HTTP from the prepared tool schemas without a fallback execution', async () => {
  const h = httpHarness({advertise: false});
  await runAgent({messages: [user], maxIterations: 3}, h.rpc);
  assert.deepEqual(h.contexts[0].tools, []);
  assert.equal(h.authorizations.length, 0);
  assert.equal(h.records.length, 0);
  const result = h.contexts[1].messages.find(message => message.role === 'toolResult');
  assert.equal(result.isError, true);
  assert.match(result.content[0].text, /not found|unknown|not available/i);
});

test('HTTP authorization denial blocks the native implementation', async () => {
  const h = httpHarness({allowed: false});
  await runAgent({messages: [user], maxIterations: 3}, h.rpc);
  assert.equal(h.authorizations.length, 1);
  assert.equal(h.records.length, 0);
  const result = h.contexts[1].messages.find(message => message.role === 'toolResult');
  assert.equal(result.isError, true);
  assert.match(result.content[0].text, /HTTP disabled by policy/);
});

test('Pi rejects invalid HTTP arguments before authorization and execution', async () => {
  const h = httpHarness({args: {url: 'http://127.0.0.1', timeout_seconds: 61}});
  await runAgent({messages: [user], maxIterations: 3}, h.rpc);
  assert.equal(h.authorizations.length, 0);
  assert.equal(h.records.length, 0);
  const result = h.contexts[1].messages.find(message => message.role === 'toolResult');
  assert.equal(result.isError, true);
  assert.match(result.content[0].text, /timeout_seconds/);
});

// Exercise the published Pi Skill loader, formatter and reader, not a Python clone.
import { mkdtemp, mkdir, writeFile, symlink, rm, realpath } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createSkillResources } from './skills.mjs';
import { createNativeTools } from './tools.mjs';

async function skillFixture(t) {
  const cwd = await mkdtemp(join(tmpdir(), 'cota-pi-skills-'));
  t.after(() => rm(cwd, {recursive: true, force: true}));
  const root = join(cwd, 'skills');
  await mkdir(join(root, 'weather', 'references'), {recursive: true});
  await writeFile(join(root, 'weather', 'SKILL.md'), '---\nname: weather\ndescription: weather guide\n---\nWEATHER_SOP\n');
  await writeFile(join(root, 'weather', 'references', 'api.md'), 'one\ntwo\nthree');
  await mkdir(join(cwd, '.pi', 'skills', 'personal'), {recursive: true});
  await writeFile(join(cwd, '.pi', 'skills', 'personal', 'SKILL.md'), '---\nname: personal\ndescription: do not load\n---\nprivate');
  const records = [];
  const resources = await createSkillResources({cwd, skillPaths: [root]});
  const native = await createNativeTools({cwd}, resources, async (method, payload) => {
    records.push({method, payload}); return {};
  });
  resources.tools = native.tools;
  return {cwd, root, records, resources};
}

test('Pi discovery uses only explicit Bot paths and advertises metadata, not SOP', async t => {
  const {resources} = await skillFixture(t);
  assert.deepEqual(resources.skills.map(skill => skill.name), ['weather']);
  assert.match(resources.prompt, /weather guide/);
  assert.match(resources.prompt, /Use the read tool/);
  assert(!resources.prompt.includes('WEATHER_SOP'));
  assert(!resources.prompt.includes('personal'));
});

test('Pi reads SOP and reference pagination, and acknowledges trace before returning', async t => {
  const {root, resources, records} = await skillFixture(t);
  const reader = resources.tools[0];
  const sop = await reader.execute('s', {path: join(root, 'weather/SKILL.md')});
  assert.match(sop.content[0].text, /WEATHER_SOP/);
  assert.equal(records[0].payload.resource.skill, 'weather');
  assert.deepEqual(Object.keys(records[0].payload.resource).sort(), ['hash', 'kind', 'path', 'skill']);
  const ref = await reader.execute('r', {path: join(root, 'weather/references/api.md'), offset: 2, limit: 1});
  assert.match(ref.content[0].text, /^two/);
  assert.match(ref.content[0].text, /offset=3/);
  assert.equal(records[1].payload.resource.kind, 'reference');
});

test('resource read refuses direct and symlink escapes without leaking contents', async t => {
  const {cwd, root, resources, records} = await skillFixture(t);
  const secret = join(cwd, 'outside.txt');
  await writeFile(secret, 'PRIVATE_CONTENT');
  const link = join(root, 'weather', 'outside.txt');
  await symlink(secret, link);
  for (const path of [secret, link]) {
    const result = await resources.tools[0].execute('denied', {path});
    assert.equal(result.isError, true);
    assert(!JSON.stringify(result).includes('PRIVATE_CONTENT'));
    assert.equal(records.at(-1).payload.resource, undefined);
  }
});

test('Pi loader exposes malformed metadata diagnostics and excludes hidden skills from catalog', async t => {
  const {cwd, root} = await skillFixture(t);
  for (const [name, frontmatter] of [['invalid', 'name: invalid'], ['explicit', 'name: explicit\ndescription: explicit only\ndisable-model-invocation: true']]) {
    await mkdir(join(root, name));
    await writeFile(join(root, name, 'SKILL.md'), `---\n${frontmatter}\n---\nSOP`);
  }
  const resources = await createSkillResources({cwd, skillPaths: [root]});
  assert(!resources.skills.some(skill => skill.name === 'invalid'));
  assert(resources.diagnostics.some(d => d.message.includes('description')));
  assert(resources.skills.some(skill => skill.name === 'explicit'));
  assert(!resources.prompt.includes('<name>explicit</name>'));
});

test('read checkpoint failure is fatal, not converted to ordinary tool error', async t => {
  const {cwd, root} = await skillFixture(t);
  const resources = await createSkillResources({cwd, skillPaths: [root]});
  resources.tools = (await createNativeTools({cwd}, resources, async () => {throw new Error('store unavailable');})).tools;
  await assert.rejects(resources.tools[0].execute('s', {path: join(root, 'weather/SKILL.md')}), /store unavailable/);
});

test('Pi resource reader returns an image block for Skill image assets', async t => {
  const {root, resources} = await skillFixture(t);
  const path = join(root, 'weather/references/pixel.png');
  await writeFile(path, Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGP8zwACTGCSAQANHQEDgslx/wAAAABJRU5ErkJggg==', 'base64'));
  const result = await resources.tools[0].execute('image', {path});
  assert(result.content.some(block => block.type === 'image' && block.mimeType === 'image/png'));
});

test('out-of-root symlink Skills cannot shadow an internal Skill name', async t => {
  const {cwd, root} = await skillFixture(t);
  const external = join(cwd, 'external');
  await mkdir(external);
  await writeFile(join(external, 'SKILL.md'), '---\nname: weather\ndescription: external override\n---\nPRIVATE');
  await symlink(external, join(root, 'aaa-external'));
  const resources = await createSkillResources({cwd, skillPaths: [root]});
  assert.deepEqual(resources.skills.map(skill => skill.name), ['weather']);
  assert.match(resources.prompt, /weather guide/);
  assert(!resources.prompt.includes('external override'));
});

test('outside Skill parser diagnostics cannot leak file contents', async t => {
  const {cwd, root} = await skillFixture(t);
  const external = join(cwd, 'external-broken');
  await mkdir(external);
  await writeFile(join(external, 'SKILL.md'), '---\nname: broken\ndescription: [PRIVATE_MARKER\n---\n');
  await symlink(external, join(root, 'broken-link'));
  const resources = await createSkillResources({cwd, skillPaths: [root]});
  assert(!JSON.stringify(resources.diagnostics).includes('PRIVATE_MARKER'));
  assert.deepEqual(resources.skills.map(skill => skill.name), ['weather']);
});

test('read trace identifies resource owner, exact file version and requested range', async t => {
  const {root, resources, records} = await skillFixture(t);
  const path = join(root, 'weather/references/api.md');
  const bytes = 'new one\nnew two\nnew three';
  await writeFile(path, bytes);
  await resources.tools[0].execute('ref', {path, offset: 2, limit: 1});
  const read = records.at(-1).payload;
  assert.equal(read.resource.skill, 'weather');
  assert.equal(read.resource.kind, 'reference');
  assert.equal(read.resource.path, await realpath(path));
  assert.deepEqual(Object.keys(read).sort(), ['args', 'name', 'resource', 'result', 'toolCallId']);
  assert.equal(read.resource.hash, 'sha256:' + createHash('sha256').update(bytes).digest('hex'));
  assert.equal(read.resource.range.offset, 2);
  assert.equal(read.resource.range.limit, 1);
  assert.deepEqual(read.resource.range, {offset: 2, limit: 1});
  assert.match(read.result.content[0].text, /^new two/);
  assert.equal(read.skill, undefined);
});

test('large reads keep a concise truncation marker and the original Pi details', async t => {
  const {root, resources, records} = await skillFixture(t);
  const path = join(root, 'weather/references/long.txt');
  await writeFile(path, 'line\n'.repeat(3000));
  await resources.tools[0].execute('long', {path});
  const read = records.at(-1).payload;
  assert.deepEqual(read.resource.range, {truncated: true});
  assert.equal(read.result.details.truncation.truncated, true);
});

test('machine factory preserves Pi schemas, argument preparation, images and nonzero outcomes', async t => {
  const {cwd, resources} = await skillFixture(t);
  const records = [];
  const native = await createNativeTools({deploy: 'personal', cwd, environment: {type: 'machine', workspace: cwd, timeout_seconds: 1}},
    resources, async (method, payload) => { records.push({method, payload}); });
  assert(['read', 'write', 'edit', 'ls', 'bash'].every(name => native.tools.some(tool => tool.name === name)));
  assert.equal(typeof native.tools.find(tool => tool.name === 'edit').prepareArguments, 'function');
  assert.match(native.prompt, /Use write only for new files/);
  assert(!native.prompt.includes('PI_SESSION'));
  const result = await native.tools.find(tool => tool.name === 'bash').execute('exit', {command: 'printf failure; exit 7'});
  assert.equal(result.isError, true);
  assert.equal(result.structuredContent.exit_code, 7);
  assert.equal(records.at(-1).method, 'tool_result');
  const path = join(cwd, 'pixel.png');
  await writeFile(path, Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGP8zwACTGCSAQANHQEDgslx/wAAAABJRU5ErkJggg==', 'base64'));
  const image = await native.tools[0].execute('image', {path});
  assert(image.content.some(block => block.type === 'image'));
  assert.equal(records.at(-1).payload.resource, undefined);
});

test('unsupported backends never select a machine tool implementation', async () => {
  for (const environment of [{type: 'device'}, {type: 'machine', workspace: '.'}, {type: 'none', workspace: '/tmp'}]) {
    await assert.rejects(createNativeTools({deploy: 'personal', environment}, {skills: []}, async () => {}), /environment|Machine/);
  }
});

test('machine advertises native listing and records missing dependency reasons', async t => {
  const {cwd, resources} = await skillFixture(t);
  const records = [];
  const native = await createNativeTools({deploy: 'personal', cwd, environment: {type: 'machine', workspace: cwd, timeout_seconds: 1}},
    resources, async (method, payload) => records.push({method, payload}));
  assert(native.tools.some(tool => tool.name === 'ls'));
  assert.deepEqual(native.inventory.available, native.tools.map(tool => tool.name));
  assert.equal(process.env.PI_OFFLINE, '1');
  if (process.platform !== 'win32') {
    assert(!native.tools.some(tool => tool.name === 'powershell'));
    assert.match(native.inventory.unavailable.powershell, /Windows/);
  }
  const result = await native.tools.find(tool => tool.name === 'ls').execute('listing', {path: '.'});
  assert.match(result.content[0].text, /skills/);
  assert.equal(records.at(-1).payload.name, 'ls');
});

test('official grep and find preserve results through the native result checkpoint', async t => {
  const {cwd, resources} = await skillFixture(t);
  const records = [];
  const native = await createNativeTools({deploy: 'personal', cwd, environment: {type: 'machine', workspace: cwd, timeout_seconds: 1}},
    resources, async (method, payload) => records.push({method, payload}));
  assert(native.inventory);
  for (const name of ['grep', 'find']) {
    await t.test(name, async st => {
      const tool = native.tools.find(tool => tool.name === name);
      if (!tool) { st.skip(native.inventory.unavailable[name]); return; }
      const args = name === 'grep' ? {pattern: 'WEATHER_SOP', path: 'skills'} : {pattern: 'SKILL.md', path: 'skills'};
      const result = await tool.execute(name, args);
      assert.equal(result.isError, false);
      assert.match(result.content[0].text, /weather.*SKILL.md/);
      assert.equal(records.at(-1).method, 'tool_result');
      assert.deepEqual(records.at(-1).payload.result.content, result.content);
      assert.equal(records.at(-1).payload.resource, undefined);
      const controller = new AbortController(); controller.abort();
      await assert.rejects(tool.execute('cancelled', args, controller.signal), /abort/i);
    });
  }
});

test('explicit PowerShell selection follows the official platform boundary', async t => {
  if (process.platform === 'win32') { t.skip('Non-Windows contract'); return; }
  const {cwd, resources} = await skillFixture(t);
  await assert.rejects(createNativeTools({deploy: 'personal', cwd, environment: {
    type: 'machine', workspace: cwd, timeout_seconds: 1, shell: 'powershell',
  }}, resources, async () => {}), /PowerShell|powershell/);
});

test('missing search dependencies are omitted without downloading', async t => {
  const {cwd} = await skillFixture(t);
  const {execFile} = await import('node:child_process');
  const {promisify} = await import('node:util');
  const source = `
    globalThis.fetch = () => { throw new Error('Unexpected network request'); };
    const {createNativeTools} = await import(${JSON.stringify(new URL('./tools.mjs', import.meta.url).href)});
    const native = await createNativeTools({deploy: 'personal', environment: {type:'machine', workspace:process.cwd(), timeout_seconds:1}},
      {skills:[]}, async () => {});
    console.log(JSON.stringify(native.inventory));
  `;
  const {stdout} = await promisify(execFile)(process.execPath, ['--input-type=module', '-e', source], {
    cwd, env: {...process.env, PATH: join(cwd, 'empty-path'), PI_CODING_AGENT_DIR: join(cwd, 'empty-pi')}, timeout: 10000,
  });
  const inventory = JSON.parse(stdout);
  assert(!inventory.available.includes('grep'));
  assert(!inventory.available.includes('find'));
  assert.match(inventory.unavailable.grep, /ripgrep|rg/);
  assert.match(inventory.unavailable.find, /fd/);
});

test('native search cancellation reaches Pi child-process cleanup', async t => {
  if (process.platform === 'win32') { t.skip('POSIX process fixture'); return; }
  const {cwd} = await skillFixture(t);
  const {execFile} = await import('node:child_process');
  const {promisify} = await import('node:util');
  const source = `
    import assert from 'node:assert/strict';
    import {mkdir,writeFile,readFile} from 'node:fs/promises';
    import {join} from 'node:path';
    const bin=join(process.env.PI_CODING_AGENT_DIR,'bin');
    await mkdir(bin,{recursive:true});
    for (const command of ['rg','fd']) await writeFile(join(bin,command),'#!/bin/sh\\nexit 0\\n',{mode:0o755});
    const {createNativeTools}=await import(${JSON.stringify(new URL('./tools.mjs', import.meta.url).href)});
    const native=await createNativeTools({deploy: 'personal', environment:{type:'machine',workspace:process.cwd(),timeout_seconds:1}},
      {skills:[]},async()=>{});
    for (const [name,command] of [['grep','rg'],['find','fd']]) {
      const pidFile=join(process.cwd(),command+'.pid');
      await writeFile(join(bin,command),'#!/bin/sh\\necho $$ > "'+pidFile+'"\\nexec /bin/sleep 30\\n');
      const controller=new AbortController();
      const tool=native.tools.find(tool=>tool.name===name);
      assert(tool, name+' should be available');
      const outcome=tool.execute('cancel',{pattern:'x'},controller.signal).then(
        ()=>{throw new Error('Expected cancellation');},error=>error);
      let pid;
      for(let i=0;i<100;i++) {
        try { pid=Number(await readFile(pidFile,'utf8')); if(pid)break; } catch {}
        await new Promise(resolve=>setTimeout(resolve,10));
      }
      controller.abort();
      assert(pid,'child should have started');
      assert.match((await outcome).message,/abort/i);
      for(let i=0;i<100;i++) {
        try { process.kill(pid,0); } catch(error) { if(error.code==='ESRCH'){pid=null;break;} throw error; }
        await new Promise(resolve=>setTimeout(resolve,10));
      }
      if(pid) { process.kill(pid,'SIGKILL'); throw new Error('Child survived cancellation'); }
    }
  `;
  await promisify(execFile)(process.execPath, ['--input-type=module', '-e', source], {
    cwd, env: {...process.env, PI_CODING_AGENT_DIR: join(cwd, 'probe-pi')}, timeout: 10000,
  });
});

test('PowerShell native execution returns exit metadata and honors cancellation', async t => {
  if (process.platform !== 'win32') { t.skip('Official Pi PowerShell requires Windows'); return; }
  const {cwd, resources} = await skillFixture(t);
  const records = [];
  const native = await createNativeTools({deploy: 'personal', environment: {type: 'machine', workspace: cwd, timeout_seconds: 3, shell: 'powershell'}},
    resources, async (method, payload) => records.push({method, payload}));
  const tool = native.tools.find(tool => tool.name === 'powershell');
  assert(tool);
  assert(!native.tools.some(tool => tool.name === 'bash'));
  const result = await tool.execute('output', {command: 'Write-Output hello; exit 7'});
  assert.equal(result.structuredContent.exit_code, 7);
  assert.equal(records.at(-1).payload.name, 'powershell');
  assert.match(result.content[0].text, /hello/);
  const timed = await tool.execute('timeout', {command: 'Start-Sleep -Seconds 30', timeout: 20});
  assert.equal(timed.isError, true);
  assert.match(timed.content[0].text, /timed out|timeout/i);
  const controller = new AbortController();
  const running = tool.execute('cancel', {command: 'Start-Sleep -Seconds 30'}, controller.signal);
  setTimeout(() => controller.abort(), 30);
  // Pi rejects an aborted shell; Cota must not swallow cancellation or retry it.
  await assert.rejects(running, /abort/i);
});
