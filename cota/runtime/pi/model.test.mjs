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
    if(method==='event')return {};
    if(method==='tool'){toolCalls.push(payload);return {content:[{type:'text',text:'acted'}]};}
    throw new Error(`Unexpected RPC ${method}`);
  };
  return {options,rpc,requests,rpcCalls,notifications,toolCalls,notify:async(method,payload)=>notifications.push({method,...payload})};
}
function sse(res){res.writeHead(200,{'content-type':'text/event-stream'});}
function done(res,text='done'){sse(res);res.write(chunk({content:text}));res.write(chunk({},'stop'));res.end('data: [DONE]\n\n');}

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

test('native hydration keeps all references, missing-file notes, bounded pixels and immutable history',async t=>{
  const {mkdtemp,writeFile,rm}=await import('node:fs/promises');const {tmpdir}=await import('node:os');const {join}=await import('node:path');
  const root=await mkdtemp(join(tmpdir(),'cota-model-'));t.after(()=>rm(root,{recursive:true,force:true}));
  const path=join(root,'image.png');const data=Buffer.from('fake-image-bytes');await writeFile(path,data);
  const attachments=[{message_id:'user-1',files:[{id:'image',name:'image.png',path,mimeType:'image/png',size:data.length},
    {id:'pdf',name:'document.pdf',path:join(root,'private.pdf'),mimeType:'application/pdf',size:20},
    {id:'missing',name:'gone.png',path:join(root,'gone.png'),mimeType:'image/png',size:10},
    {id:'big',name:'big.png',path,mimeType:'image/png',size:2097153}]}];
  const f=await fixture(t,async(_req,res)=>done(res));f.options.provider.vision=true;
  f.options.messages=[{...user,cotaAttachments:attachments[0].files.map(file=>({id:file.id,name:file.name,mime_type:file.mimeType,size:file.size}))}];
  const original=structuredClone(f.options.messages);
  const rpc=async(method,payload)=>method==='prepare'?{systemPrompt:'policy',tools:[],attachments}:f.rpc(method,payload);
  await runAgent(f.options,rpc);
  const content=f.requests[0].body.messages.find(m=>m.role==='user').content;
  assert.equal(content.filter(c=>c.type==='image_url').length,1);
  assert.equal(content.find(c=>c.type==='image_url').image_url.url,`data:image/png;base64,${data.toString('base64')}`);
  const text=content.filter(c=>c.type==='text').map(c=>c.text).join('\n');
  assert.match(text,/document.pdf/);assert.match(text,/Attachment unavailable/);assert.match(text,/2 MiB/);
  assert.doesNotMatch(text,/local_copy|private.pdf/);assert.deepEqual(f.options.messages,original);
});

test('native text-only model receives authorized file metadata and machine local copy',async t=>{
  const f=await fixture(t,async(_req,res)=>done(res));
  f.options.environment={type:'none'};
  const attachments=[{message_id:'user-1',files:[{id:'file-1',name:'book.pdf',mimeType:'application/pdf',size:200,path:'/authorized/book.pdf'},
    {id:'missing',note:'Attachment unavailable'}]}];
  await runAgent(f.options,async(method,payload)=>method==='prepare'?{systemPrompt:'policy',tools:[],attachments}:f.rpc(method,payload));
  const content=f.requests[0].body.messages.find(m=>m.role==='user').content;
  assert.match(JSON.stringify(content),/book.pdf/);assert.match(JSON.stringify(content),/Attachment unavailable/);
  assert.doesNotMatch(JSON.stringify(content),/authorized|local_copy/);
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
