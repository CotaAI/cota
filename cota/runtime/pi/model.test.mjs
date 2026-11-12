import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {runAgent} from './engine.mjs';

const user = {role:'user', content:'hello', timestamp:1, cotaEventId:'user-1'};
const schema = {type:'function',function:{name:'act',description:'act',parameters:{type:'object',properties:{n:{type:'number'}},required:['n']}}};
const delay = ms => new Promise(resolve=>setTimeout(resolve,ms));
const chunk = (delta,finish_reason=null) => `data: ${JSON.stringify({id:'c',object:'chat.completion.chunk',created:1,model:'native-test',choices:[{index:0,delta,finish_reason}]})}\n\n`;
async function fixture(t,handler, extra={}) {
  const requests=[], rpcCalls=[], notifications=[], toolCalls=[];
  const server=createServer(async(req,res)=>{let body='';for await(const part of req)body+=part;requests.push({url:req.url,body:JSON.parse(body)});await handler(req,res,requests.length);});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(()=>{server.closeAllConnections();server.close();});
  const options={messages:[user],maxIterations:3,provider:{apiKey:'test-secret',baseUrl:`http://127.0.0.1:${server.address().port}/v1`,model:'native-test',timeoutSeconds:2,maxRetries:0,thinking:false,vision:false},...extra};
  const rpc=async(method,payload)=>{rpcCalls.push({method,payload});
    if(method==='skills_loaded')return {};
    if(method==='prepare')return {systemPrompt:`policy-${rpcCalls.filter(c=>c.method==='prepare').length}`,tools:[schema],attachments:[]};
    if(method==='model_begin')return {request_id:`req-${rpcCalls.filter(c=>c.method==='model_begin').length}`,debug:false};
    if(method==='model_complete'||method==='model_failed'||method==='model_observation')return {};
    if(method==='reject_output')return {};
    if(method==='event')return {};
    if(method==='tool'){toolCalls.push(payload);return {content:[{type:'text',text:'acted'}]};}
    throw new Error(`Unexpected RPC ${method}`);
  };
  return {options,rpc,requests,rpcCalls,notifications,toolCalls,notify:async(method,payload)=>notifications.push({method,...payload})};
}
function sse(res){res.writeHead(200,{'content-type':'text/event-stream'});}
function done(res,text='done'){sse(res);res.write(chunk({content:text}));res.write(chunk({},'stop'));res.end('data: [DONE]\n\n');}

test('split DSML never leaks through native streaming or becomes a committed reply', async t => {
  const raw = 'Saved progress.\n<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name="act">\n</｜｜DSML｜｜ calls>';
  const f = await fixture(t, async (_req,res) => {
    sse(res);
    for (const part of raw) res.write(chunk({content:part}));
    res.write(chunk({},'stop'));res.end('data: [DONE]\n\n');
  });
  const result = await runAgent(f.options,f.rpc,undefined,f.notify);
  assert.equal(result.status,'failed');
  assert.equal(result.outputError,'invalid_model_output');
  const preview=f.notifications.filter(n=>n.phase==='delta').map(n=>n.text).join('');
  assert(!preview.includes('<｜') && !preview.includes('DSML'));
  assert.equal(f.notifications.at(-1).phase,'error');
  assert(!f.rpcCalls.some(c=>c.method==='event' && c.payload.event.message?.role==='assistant'));
  assert.equal(f.rpcCalls.find(c=>c.method==='model_complete').payload.message.content[0].text,raw);
  assert(f.rpcCalls.some(c=>c.method==='reject_output'));
  assert.equal(f.toolCalls.length,0);
});

test('restored protocol-only replies stay in evidence but are omitted from the next request', async t => {
  const f = await fixture(t, async (_req,res) => done(res));
  const invalid = {role:'assistant',content:[{type:'text',text:'<｜｜DSML｜｜ calls>broken</｜｜DSML｜｜ calls>'}],
    stopReason:'stop',timestamp:2};
  f.options.messages = [user,invalid,{...user,content:'Continue saved work.',timestamp:3}];
  const original=structuredClone(f.options.messages);
  await runAgent(f.options,f.rpc);
  assert(!JSON.stringify(f.requests[0].body.messages).includes('DSML'));
  assert.deepEqual(f.options.messages,original);
});

test('native text deltas arrive before completion and persistence gates end',async t=>{
  let released;const gate=new Promise(resolve=>released=resolve);
  const f=await fixture(t,async(_req,res)=>{sse(res);res.write(chunk({reasoning_content:'private thought'}));res.write(chunk({content:'early'}));await gate;res.write(chunk({content:' answer'}));res.write(chunk({},'stop'));res.end('data: [DONE]\n\n');});
  const running=runAgent(f.options,f.rpc,undefined,f.notify);
  try {for(let i=0;i<100&&!f.notifications.some(n=>n.phase==='delta');i++)await delay(10);
    assert.equal(f.notifications.find(n=>n.phase==='delta')?.text,'early');
    assert.equal(f.rpcCalls.some(c=>c.method==='model_complete'),false);
  }finally{released();}
  const result=await running;
  assert.equal(result.status,'completed');
  assert.deepEqual(f.notifications.filter(n=>n.phase==='delta').map(n=>n.text),['early',' answer']);
  assert.equal(f.notifications.at(-1).phase,'end');
  assert.equal(f.rpcCalls.filter(c=>c.method==='model_complete').length,1);
  assert.equal(f.rpcCalls.some(c=>c.method==='model_observation' && c.payload.kind==='request'),false);
  assert.equal(f.rpcCalls.find(c=>c.method==='prepare').payload.messages,undefined);
  const request=f.requests[0];assert.equal(request.url,'/v1/chat/completions');
  assert.equal(request.body.model,'native-test');assert.equal(request.body.stream,true);
  assert.equal(request.body.max_tokens??request.body.max_completion_tokens,4096);
  assert.deepEqual(request.body.thinking,{type:'disabled'});
  assert.equal(request.body.messages[0].content,'policy-1');
});

test('native tool continuation refreshes policy and preserves Pi thinking',async t=>{
  const f=await fixture(t,async(_req,res,n)=>{if(n===2)return done(res);sse(res);res.write(chunk({reasoning_content:'private reasoning'}));res.write(chunk({tool_calls:[{index:0,id:'tool-1',type:'function',function:{name:'act',arguments:'{"n":1}'}}]}));res.write(chunk({},'tool_calls'));res.end('data: [DONE]\n\n');});
  const result=await runAgent(f.options,f.rpc,undefined,f.notify);
  assert.equal(result.status,'completed');assert.equal(f.toolCalls.length,1);assert.equal(f.requests.length,2);
  assert.equal(f.requests[1].body.messages[0].content,'policy-2');
  assert(f.requests[1].body.messages.some(m=>m.role==='tool'&&m.content==='acted'));
  assert(f.requests[1].body.messages.some(m=>m.role==='assistant'&&m.reasoning_content==='private reasoning'));
  assert.equal(f.rpcCalls.filter(c=>c.method==='model_complete').length,2);
});

test('total deadline aborts whitespace keepalive and never executes partial tool calls',async t=>{
  const f=await fixture(t,async(_req,res)=>{sse(res);res.write(chunk({tool_calls:[{index:0,id:'tool-1',type:'function',function:{name:'act',arguments:'{"n":1}'}}]}));const timer=setInterval(()=>res.write(': keepalive\n\n'),10);res.on('close',()=>clearInterval(timer));});
  f.options.provider.timeoutSeconds=.12;
  const began=Date.now();await assert.rejects(runAgent(f.options,f.rpc,undefined,f.notify),/timed out|timeout|abort/i);
  assert(Date.now()-began<1000);assert.equal(f.toolCalls.length,0);
  assert.equal(f.rpcCalls.filter(c=>c.method==='model_failed').length,1);
  assert.equal(f.notifications.at(-1).phase,'error');
});

for(const maxRetries of [0,1])test(`Pi native retry limit ${maxRetries}`,async t=>{
  const f=await fixture(t,async(_req,res,n)=>{if(n===1){res.writeHead(503,{'content-type':'application/json','retry-after':'0'});res.end(JSON.stringify({error:{message:'temporary outage'}}));}else done(res);});
  f.options.provider.maxRetries=maxRetries;
  if(maxRetries)assert.equal((await runAgent(f.options,f.rpc)).status,'completed');
  else await assert.rejects(runAgent(f.options,f.rpc),/Native model request failed/);
  assert.equal(f.requests.length,maxRetries+1);
  const report=f.rpcCalls.find(c=>c.method===(maxRetries?'model_complete':'model_failed')).payload;
  assert.equal(report.transport.attempts.length,maxRetries+1);
  assert.equal(JSON.stringify(report.transport).includes('test-secret'),false);
});

test('native completion acknowledgment failure prevents tools and end notification',async t=>{
  const f=await fixture(t,async(_req,res)=>{sse(res);res.write(chunk({tool_calls:[{index:0,id:'tool-1',type:'function',function:{name:'act',arguments:'{"n":1}'}}]}));res.write(chunk({},'tool_calls'));res.end('data: [DONE]\n\n');});
  const rpc=async(method,payload)=>{if(method==='model_complete')throw new Error('stage unavailable');return f.rpc(method,payload);};
  await assert.rejects(runAgent(f.options,rpc,undefined,f.notify),/stage unavailable/);
  assert.equal(f.toolCalls.length,0);assert.equal(f.notifications.some(n=>n.phase==='end'),false);
});

test('provider failure diagnostics never escape into public run error',async t=>{
  const f=await fixture(t,async(_req,res)=>{res.writeHead(401,{'content-type':'application/json'});res.end(JSON.stringify({error:{message:'rejected test-secret and confidential response body'}}));});
  let caught;try{await runAgent(f.options,f.rpc);}catch(error){caught=error;}
  assert(caught);assert.doesNotMatch(caught.message,/test-secret|confidential/);
  assert.match(caught.message,/request=req-1/);
  assert.equal(f.toolCalls.length,0);
});

test('native transport preserves P0 attempt states and completion timing',async t=>{
  const f=await fixture(t,async(_req,res)=>done(res));
  delete f.options.provider.timeoutSeconds;
  await runAgent(f.options,f.rpc);
  const transport=f.rpcCalls.find(c=>c.method==='model_complete').payload.transport;
  assert.equal(transport.timeout_seconds,180);assert.equal(transport.attempts[0].status,'completed');
  assert.equal(transport.attempts[0].status_code,200);
  assert(transport.response_ready_ms>=transport.attempts[0].headers_ms);
});

test('native resource hydration preserves metadata, unavailable notes and automatic image limits', async t => {
  const data = Buffer.from('fake-image-bytes');
  const resources = [
    {id: 'f_image', path: '/bot/.cota/context-images/session/image.png', mimeType: 'image/png', size: data.length},
    {id: 'f_missing', path: '/bot/.cota/context-images/session/missing.png', mimeType: 'image/png', size: 10},
    {id: 'f_big', path: '/bot/.cota/context-images/session/big.png', mimeType: 'image/png', size: 2097153}];
  const f = await fixture(t, async (_req, res) => done(res)); f.options.provider.vision = true;
  f.options.imageResources = resources;
  f.options.messages = [{...user, cotaAttachmentsHydrated: true, content: [
    {type: 'text', text: 'image.png reference; pixels omitted'}, {type: 'text', text: 'gone.png reference; pixels omitted'},
    {type: 'text', text: 'big.png exceeds automatic model-input limit of 2 MiB'},
    {type: 'text', text: 'document.pdf: file contents not parsed'}],
    cotaImageRefs: resources.map((resource, index) => ({index, ...resource, auto: index !== 2}))}];
  const original = structuredClone(f.options.messages);
  await runAgent(f.options, async (method, payload) => method === 'image_resource'
    ? payload.id === 'f_image' ? {type: 'image', mimeType: 'image/png', data: data.toString('base64')}
      : {error: 'Image resource unavailable; contents not reviewed'} : f.rpc(method, payload));
  const content = f.requests[0].body.messages.find(m => m.role === 'user').content;
  assert.equal(content.filter(c => c.type === 'image_url').length, 1);
  assert.equal(content.find(c => c.type === 'image_url').image_url.url, `data:image/png;base64,${data.toString('base64')}`);
  const text = content.filter(c => c.type === 'text').map(c => c.text).join('\n');
  assert.match(text, /document.pdf/); assert.match(text, /unavailable; contents not reviewed/); assert.match(text, /2 MiB/);
  assert.doesNotMatch(text, /local_copy|private.pdf/); assert.deepEqual(f.options.messages, original);
});

test('native text-only model retains canonical file metadata without hydrating disabled references', async t => {
  const f = await fixture(t, async (_req, res) => done(res));
  const resource = {id: 'f_image', path: '/bot/.cota/context-images/session/image.png', mimeType: 'image/png', size: 10};
  f.options.imageResources = [resource];
  f.options.messages = [{...user, cotaAttachmentsHydrated: true, content: [
    {type: 'text', text: 'book.pdf: File contents have not been parsed'},
    {type: 'text', text: 'Image resource reference: Selected model is not configured for image input'}],
    cotaImageRefs: [{index: 1, ...resource, auto: false}]}];
  await runAgent(f.options, f.rpc);
  const content = f.requests[0].body.messages.find(m => m.role === 'user').content;
  assert.match(JSON.stringify(content), /book.pdf/); assert.match(JSON.stringify(content), /not configured/);
  assert.equal(f.rpcCalls.some(call => call.method === 'image_resource'), false);
});

function oversizedHistory(){return [user,
  {role:'assistant',content:[{type:'toolCall',id:'old-tool',name:'act',arguments:{n:1}}],timestamp:2,cotaEventId:'old-call'},
  {role:'toolResult',toolCallId:'old-tool',toolName:'act',content:[{type:'text',text:'guide '.repeat(6000)}],timestamp:3,cotaEventId:'old-result'},
  {role:'user',content:'continue',timestamp:4,cotaEventId:'latest'}];}
for(const fail of [false,true])test(`native compaction uses provider stream without public deltas (failure=${fail})`,async t=>{
  const f=await fixture(t,async(_req,res,n)=>{if(fail&&n===1){res.writeHead(503,{'content-type':'application/json'});return res.end('{"error":{"message":"summary unavailable"}}');}done(res,n===1?'useful summary':'final answer');});
  f.options.messages=oversizedHistory();f.options.model={contextWindow:8000,maxTokens:500};
  f.options.compaction={reserve_tokens:1000,keep_recent_tokens:1000};
  const rpc=async(method,payload)=>{
    if(method==='compact')return {messages:[{role:'user',content:payload.summary,timestamp:5,cotaEventId:'summary',cotaCompaction:true},f.options.messages.at(-1)]};
    return f.rpc(method,payload);
  };
  if(fail){await assert.rejects(runAgent(f.options,rpc,undefined,f.notify),error=>error.code==='model_error');assert.equal(f.notifications.length,0);}
  else {await runAgent(f.options,rpc,undefined,f.notify);
    assert.deepEqual(f.rpcCalls.filter(c=>c.method==='model_begin').map(c=>c.payload.purpose),['compaction','dialogue']);
    assert.deepEqual(f.notifications.filter(n=>n.phase==='delta').map(n=>n.text),['final answer']);
    assert.equal(f.requests[0].body.max_tokens??f.requests[0].body.max_completion_tokens,1000);
  }
});

test('native model failures carry model_error while persistence failures retain original type',async t=>{
  const f=await fixture(t,async(_req,res)=>{res.writeHead(503,{'content-type':'application/json'});res.end('{"error":{"message":"unavailable"}}');});
  await assert.rejects(runAgent(f.options,f.rpc),error=>error.code==='model_error');
});

test('native truncated tool proposals do not execute',async t=>{
  const f=await fixture(t,async(_req,res,n)=>{if(n===2)return done(res);sse(res);res.write(chunk({tool_calls:[{index:0,id:'truncated',type:'function',function:{name:'act',arguments:'{"n":1}'}}]}));res.write(chunk({},'length'));res.end('data: [DONE]\n\n');});
  await runAgent(f.options,f.rpc);assert.equal(f.toolCalls.length,0);
});

test('total provider deadline also bounds a stalled Debug request observer', async t => {
  const f = await fixture(t, async (_req, res) => done(res));
  f.options.provider.timeoutSeconds = .1;
  const rpc = async (method, payload) => {
    if (method === 'model_begin') return {request_id: 'slow-debug', debug: true};
    if (method === 'model_observation') {await delay(600); return {};}
    return f.rpc(method, payload);
  };
  const began = performance.now();
  await assert.rejects(runAgent(f.options, rpc), /timed out/);
  assert(performance.now() - began < 400, 'Debug persistence must not extend provider deadline');
  assert.equal(f.requests.length, 0);
});

test('safe transport observations arrive while native body is still streaming', async t => {
  const f = await fixture(t, async (_req, res) => done(res));
  await runAgent(f.options, f.rpc);
  const headers = f.rpcCalls.find(c => c.method === 'model_observation' && c.payload.kind === 'transport' && c.payload.transport.attempts.at(-1)?.status_code === 200);
  assert(headers, 'HTTP headers must be observable before the completed model response');
  assert(f.rpcCalls.indexOf(headers) < f.rpcCalls.findIndex(c => c.method === 'model_complete'));
  assert.equal(JSON.stringify(headers).includes('test-secret'), false);
});

test('native provider receives actual callable schemas on the first request', async t => {
  const f = await fixture(t, async (_req, res) => done(res));
  await runAgent(f.options, f.rpc);
  assert.deepEqual(f.requests[0].body.tools?.map(tool => tool.function.name), ['act']);
  assert.deepEqual(f.requests[0].body.tools[0].function.parameters, schema.function.parameters);
  assert.equal(JSON.stringify(f.requests[0].body.tools).includes('execute'), false);
});

test('schema-aware provider calls tools only when declared, then respects refreshed loadout', async t => {
  const f = await fixture(t, async (_req, res, n) => {
    const body = f.requests[n - 1].body;
    if (n === 1 && body.tools?.some(tool => tool.function.name === 'act')) {
      sse(res);
      res.write(chunk({content: 'I will check the instructions.'}));
      res.write(chunk({tool_calls: [{index: 0, id: 'declared-call', type: 'function',
        function: {name: 'act', arguments: '{"n":1}'}}]}));
      res.write(chunk({}, 'tool_calls'));
      res.end('data: [DONE]\n\n');
    } else done(res, n === 1 ? '<DSML invoke name="act">not a real tool call</DSML>' : 'finished');
  });
  let preparations = 0;
  const rpc = async (method, payload) => {
    if (method === 'prepare') return {systemPrompt: `policy-${++preparations}`,
      tools: preparations === 1 ? [schema] : [], attachments: []};
    return f.rpc(method, payload);
  };
  const result = await runAgent(f.options, rpc, undefined, f.notify);
  assert.equal(f.toolCalls.length, 1);
  assert.equal(f.requests.length, 2);
  assert.deepEqual(f.requests[0].body.tools.map(tool => tool.function.name), ['act']);
  assert.deepEqual(f.requests[1].body.tools, []);
  assert.equal(f.requests[1].body.messages[0].content, 'policy-2');
  assert(f.requests[1].body.messages.some(message => message.role === 'tool'));
  assert.equal(result.messages.at(-1).content[0].text, 'finished');
});

test('request projection bounds restored image history and attachments before budgets without changing raw state', async t => {
  const {mkdtemp, writeFile, rm} = await import('node:fs/promises');
  const {tmpdir} = await import('node:os'); const {join} = await import('node:path');
  const root = await mkdtemp(join(tmpdir(), 'cota-image-context-'));
  t.after(() => rm(root, {recursive: true, force: true}));
  const file = join(root, 'attachment.png'); const bytes = Buffer.from('current attachment'); await writeFile(file, bytes);
  const history = [{...user, cotaEventId: 'old-user'}];
  for (let i = 0; i < 10; i++) history.push(
    {role: 'assistant', cotaEventId: `call-${i}`, timestamp: i + 2, reasoningSignature: 'provider-metadata',
      content: [{type: 'toolCall', id: `read-${i}`, name: 'read', arguments: {path: `/book/${i}.png`}}]},
    {role: 'toolResult', cotaEventId: `result-${i}`, timestamp: i + 2, toolCallId: `read-${i}`, toolName: 'read',
      details: {original: true}, content: [{type: 'image', data: Buffer.from(`old ${i}`).toString('base64'), mimeType: 'image/png'}]});
  const attachment = {id: 'f_new', path: '/bot/.cota/context-images/session/new.png', mimeType: 'image/png', size: bytes.length};
  history.push({...user, cotaEventId: 'new-user', cotaAttachmentsHydrated: true, content: [{type: 'text', text: 'Image resource; pixels omitted'}], cotaImageRefs: [{index: 0, ...attachment}]});
  history.push({role: 'assistant', cotaEventId: 'compare', content: [0, 1].map(i =>
    ({type: 'toolCall', id: `compare-${i}`, name: 'read', arguments: {path: `/book/current-${i}.png`}}))});
  for (let i = 0; i < 2; i++) history.push({role: 'toolResult', cotaEventId: `current-${i}`, toolCallId: `compare-${i}`, toolName: 'read',
    content: [{type: 'image', mimeType: 'image/png', data: Buffer.from(`current ${i}`).toString('base64')}]});
  const original = structuredClone(history);
  const f = await fixture(t, async (_req, res) => done(res));
  f.options.messages = history; f.options.provider.vision = true; f.options.compaction = {max_images: 3};
  f.options.imageResources = [attachment];
  const rpc = async (method, payload) => method === 'prepare' ? {systemPrompt: 'policy', tools: []}
    : method === 'image_resource' ? {type: 'image', mimeType: 'image/png', data: bytes.toString('base64')} : f.rpc(method, payload);
  const result = await runAgent(f.options, rpc);
  const wire = f.requests[0].body.messages;
  const pixels = wire.flatMap(m => Array.isArray(m.content) ? m.content.filter(b => b.type === 'image_url') : []);
  assert.equal(pixels.length, 3);
  assert.match(JSON.stringify(wire), /\/book\/0.png/);
  assert.doesNotMatch(JSON.stringify(wire), new RegExp(Buffer.from('old 0').toString('base64')));
  const budget = f.rpcCalls.find(c => c.method === 'model_begin').payload.contextBudget;
  assert.equal(budget.images, 3);
  assert.deepEqual(history, original);
  assert.equal(result.messages.filter(m => m.role === 'toolResult').flatMap(m => m.content.filter(b => b.type === 'image')).length, 12);
  assert(!JSON.stringify(result.messages).includes('Image pixels omitted'));
  // A later run starts from the returned raw checkpoint. Previous attachments
  // and answered tool images must not be reintroduced at the provider boundary.
  f.options.messages = [...result.messages, {...user, cotaEventId: 'restart-user', content: 'continue from your observations'}];
  await runAgent(f.options, rpc);
  assert.equal(f.requests[1].body.messages.flatMap(m => Array.isArray(m.content) ? m.content.filter(b => b.type === 'image_url') : []).length, 0);
});

test('an oversized active user input plus tool image batch fails before compaction can discard input pixels', async t => {
  const f = await fixture(t, async (_req, res) => done(res));
  const image = text => ({type: 'image', mimeType: 'image/png', data: Buffer.from(text).toString('base64')});
  f.options.messages = [
    {...user, content: [image('user first'), image('user second')]},
    {role: 'assistant', cotaEventId: 'call', content: [{type: 'toolCall', id: 'read', name: 'read', arguments: {path: '/result.png'}}]},
    {role: 'toolResult', cotaEventId: 'result', toolCallId: 'read', toolName: 'read', content: [image('tool result')]},
  ];
  f.options.compaction = {max_images: 2};
  await assert.rejects(runAgent(f.options, f.rpc), /current|latest.*(?:image|batch)/i);
  assert.equal(f.rpcCalls.some(c => c.method === 'compact' || c.method === 'model_begin'), false);
  assert.equal(f.requests.length, 0);
});

test('native compaction summarizes projected sources and recorded observations without sending pixels', async t => {
  const f = await fixture(t, async (_req, res, n) => done(res, n === 1 ? 'summary preserves /old.png and the recorded blue border' : 'done'));
  f.options.messages = oversizedHistory();
  f.options.messages[0] = {...user, content: [{type: 'text', text: 'Inspect this image; source /old.png.'},
    {type: 'image', mimeType: 'image/png', data: Buffer.from('old image').toString('base64')}]};
  f.options.messages[2].content.unshift({type: 'text', text: 'Explicit observation: the border is blue.'});
  const before = structuredClone(f.options.messages);
  f.options.model = {contextWindow: 8000, maxTokens: 500};
  f.options.compaction = {reserve_tokens: 1000, keep_recent_tokens: 1000};
  f.options.provider.vision = true;
  const rpc = async (method, payload) => method === 'compact' ? {messages: [
    {role: 'user', content: payload.summary, timestamp: 5, cotaEventId: 'summary', cotaCompaction: true},
    f.options.messages.at(-1)]} : f.rpc(method, payload);
  await runAgent(f.options, rpc);
  const summary = JSON.stringify(f.requests[0].body.messages);
  assert.match(summary, /sha256:/); assert.match(summary, /source_id/);
  assert.match(summary, /border is blue/); assert.match(summary, /re-read/);
  assert.doesNotMatch(summary, /data:image/);
  assert.deepEqual(f.options.messages, before);
});

test('image provenance survives Pi truncation of long tool-result text', async t => {
  const f = await fixture(t, async (_req, res, n) => done(res, n === 1 ? 'summary' : 'done'));
  const sourceId = 'long-image-result';
  f.options.messages = [user,
    {role: 'assistant', cotaEventId: 'long-image-call', content: [{type: 'toolCall', id: 'long-image', name: 'read', arguments: {path: '/book/long.png'}}]},
    {role: 'toolResult', cotaEventId: sourceId, toolCallId: 'long-image', toolName: 'read', content: [
      {type: 'text', text: 'details '.repeat(6000)}, {type: 'image', mimeType: 'image/png', data: 'eA=='}]},
    {...user, cotaEventId: 'latest-input', content: 'continue'}];
  f.options.model = {contextWindow: 8000, maxTokens: 500};
  f.options.compaction = {reserve_tokens: 1000, keep_recent_tokens: 100};
  const rpc = async (method, payload) => method === 'compact' ? {messages: [
    {role: 'user', content: payload.summary, timestamp: 5, cotaEventId: 'summary', cotaCompaction: true}, f.options.messages.at(-1)]} : f.rpc(method, payload);
  await runAgent(f.options, rpc);
  const summary = JSON.stringify(f.requests[0].body.messages);
  assert.match(summary, new RegExp(sourceId)); assert.match(summary, /sha256:/); assert.match(summary, /re-read/);
});

test('deadline error type survives an unacknowledged failure observation', async t => {
  const f = await fixture(t, async (_req, res) => {sse(res); res.write(': keepalive\n\n');});
  f.options.provider.timeoutSeconds = .1;
  const rpc = async (method, payload) => method === 'model_failed' ? new Promise(() => {}) : f.rpc(method, payload);
  await assert.rejects(runAgent(f.options, rpc), error => error.code === 'model_error' && error.error_type === 'TimeoutError');
});
