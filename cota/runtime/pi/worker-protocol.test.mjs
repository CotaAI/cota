import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';

async function worker(t,{cancel=false,fail=false,wrapup=false}={}) {
  const requests=[];
  const server=createServer(async(req,res)=>{let body='';for await(const part of req)body+=part;requests.push(JSON.parse(body));
    if(fail){res.writeHead(503,{'content-type':'application/json'});res.end('{"error":{"message":"unavailable"}}');return;}
    res.writeHead(200,{'content-type':'text/event-stream'});
    if(cancel){res.write(': waiting\n\n');return;}
    if(wrapup&&requests.length===1){res.end('data: '+JSON.stringify({id:'c',choices:[{index:0,delta:{tool_calls:[{index:0,id:'work-1',type:'function',function:{name:'act',arguments:'{}'}}]},finish_reason:'tool_calls'}]})+'\n\ndata: [DONE]\n\n');return;}
    res.end('data: '+JSON.stringify({id:'c',choices:[{index:0,delta:{content:'streamed'},finish_reason:null}]})+'\n\ndata: '+JSON.stringify({id:'c',choices:[{index:0,delta:{},finish_reason:'stop'}]})+'\n\ndata: [DONE]\n\n');
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const child=spawn(process.execPath,[new URL('./worker.mjs',import.meta.url).pathname],{stdio:['pipe','pipe','pipe']});
  t.after(()=>{child.kill();server.closeAllConnections();server.close();});
  let stderr='';child.stderr.on('data',data=>stderr+=data);
  const frames=[];const lines=createInterface({input:child.stdout});
  const send=value=>child.stdin.write(JSON.stringify(value)+'\n');
  const completion=new Promise((resolve,reject)=>{
    lines.on('line',line=>{const frame=JSON.parse(line);frames.push(frame);
      if(frame.type==='request') {
        let result={};
        if(frame.method==='prepare')result={systemPrompt:'policy',tools:wrapup?[{type:'function',function:{name:'act',description:'Save one result',parameters:{type:'object',properties:{}}}}]:[],attachments:[]};
        if(frame.method==='tool')result={content:[{type:'text',text:'one result saved'}]};
        if(frame.method==='model_begin')result={request_id:'req-worker',debug:false};
        send({type:'response',id:frame.id,result});
      }else if(frame.type==='notification'&&frame.payload.phase==='start'&&cancel)send({type:'cancel'});
      else if(frame.type==='done'||frame.type==='error')resolve(frame);
    });
    child.on('exit',code=>{if(!frames.some(frame=>['done','error'].includes(frame.type)))reject(new Error(`worker exited ${code}: ${stderr}`));});
  });
  send({type:'start',protocol:1,options:{messages:[{role:'user',content:'hello',timestamp:1}],maxIterations:wrapup?2:1,...(wrapup?{wrapUpIterations:1}:{}),
    provider:{apiKey:'test',baseUrl:`http://127.0.0.1:${server.address().port}/v1`,model:'test',timeoutSeconds:2,maxRetries:0,thinking:'disabled',vision:false}}});
  return {frame:await completion,frames,requests};
}
test('production worker emits bounded stream frames and a compact final outcome',async t=>{
  const {frame,frames}=await worker(t);
  assert.equal(frame.type,'done');assert.deepEqual(frame.result,{status:'completed'});
  assert.deepEqual(frames.filter(f=>f.type==='notification').map(f=>f.payload.phase),['start','delta','end']);
});
test('cancel frame aborts the provider stream through Pi cancellation',async t=>{
  const {frame,frames}=await worker(t,{cancel:true});
  assert.equal(frame.type,'error');assert.doesNotMatch(frame.error,/Invalid protocol message/);
  assert(frames.some(f=>f.type==='request'&&f.method==='model_failed'));
  assert(frames.some(f=>f.type==='notification'&&f.payload.phase==='error'));
});

test('worker identifies provider errors without exposing provider detail',async t=>{
  const {frame}=await worker(t,{fail:true});assert.equal(frame.type,'error');
  assert.equal(frame.code,'model_error');assert.match(frame.error,/request=req-worker/);
  assert.doesNotMatch(frame.error,/unavailable/);
});


test('production protocol retains committed wrap-up acknowledgment without returning history',async t=>{
  const {frame,frames,requests}=await worker(t,{wrapup:true});
  assert.equal(frame.type,'done');
  assert.deepEqual(frame.result,{status:'limited',hasFinalReply:true});
  assert.equal(requests.length,2);
  assert.deepEqual(requests[1].tools,requests[0].tools);
  assert.equal(requests[1].tool_choice,'none');
  assert.equal(frames.filter(f=>f.type==='request'&&f.method==='tool').length,1);
  assert(frames.some(f=>f.type==='request'&&f.method==='event'
    &&f.payload.event.type==='message_end'&&f.payload.event.message.role==='assistant'
    &&f.payload.event.message.content.some(b=>b.type==='text'&&b.text==='streamed')));
  assert.equal('messages' in frame.result,false);
});
