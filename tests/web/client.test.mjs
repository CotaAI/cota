import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

function harness(options = {}, fetch = undefined) {
  const sockets = [], timers = new Map(), stored = new Map();
  stored.set('cota.chat.v1:', JSON.stringify({token:'valid-token',session_id:'s',cursor:0,messages:[],pending:{}}));
  class Socket {
    constructor(url) {this.url=url;this.sent=[];sockets.push(this);}
    send(raw) {this.sent.push(JSON.parse(raw));}
    close() {this.onclose?.();}
    frame(data) {this.onmessage({data:JSON.stringify(data)});}
  }
  let nextTimer=0;
  const context=vm.createContext({options,fetch,URL,WebSocket:Socket,location:{href:'http://localhost/'},crypto:{randomUUID:()=> 'id1'},
    localStorage:{getItem:key=>stored.get(key),setItem:(key,value)=>stored.set(key,value)},
    setTimeout:fn=>{timers.set(++nextTimer,fn);return nextTimer;},clearTimeout:id=>timers.delete(id)});
  vm.runInContext(readFileSync('cota/channels/utils/cota.js','utf8')+'\nglobalThis.client=new CotaClient(options);',context);
  return {client:context.client,sockets,timers,stored};
}

test('queued receipt retains identity, busy retries and terminal receipt clears', async()=>{
  const {client,sockets,timers}=harness();await client.ready;
  const ws=sockets[0];ws.onopen();ws.frame({type:'ready',cursor:0});
  await client.chat('hello');assert.equal(ws.sent.at(-1).message_id,'id1');
  ws.frame({type:'receipt',message_id:'id1',status:'queued'});
  assert.equal(client.state.pending.id1,'hello');
  ws.frame({type:'error',code:'busy',message_id:'id1'});
  [...timers.values()][0]();assert.equal(ws.sent.at(-1).message_id,'id1');
  ws.frame({type:'receipt',message_id:'id1',status:'completed'});
  assert.equal(client.state.pending.id1,undefined);
  client.close();
});

test('reconnect reuses cursor and submission IDs; repeated history is rendered once',async()=>{
  const {client,sockets,timers}=harness();await client.ready;
  let count=0;client.on('message',()=>count++);
  const ws=sockets[0];ws.onopen();ws.frame({type:'ready',cursor:0});
  await client.chat('hello');
  const message={type:'message',event_id:'e1',sequence:3,role:'user',text:'hello'};
  ws.frame(message);ws.frame(message);assert.equal(count,1);
  ws.close();[...timers.values()].at(-1)();
  const resumed=sockets[1];resumed.onopen();assert.equal(resumed.sent[0].after_sequence,3);
  resumed.frame({type:'ready',cursor:4});assert.equal(resumed.sent.at(-1).message_id,'id1');
  resumed.frame({type:'error',code:'unauthorized'});assert.equal(client.stopped,true);
});


test('external identity skips provisioning and isolates cached conversations',async()=>{
  const {client,sockets}=harness({token:'external-token',sessionId:'external-session'});
  await client.ready;
  const ws=sockets[0];ws.onopen();
  assert.equal(ws.sent[0].token,'external-token');
  assert.equal(ws.sent[0].session_id,'external-session');
  assert.equal(client.state.messages.length,0);
  assert.notEqual(client.storageKey,'cota.chat.v1:');
  ws.frame({type:'ready',cursor:0});
  assert.equal(await client.chat('hello','external-message'), 'external-message');
  assert.equal(ws.sent.at(-1).message_id, 'external-message');
  client.close();
});

test('group mention and reply survive busy retry, reconnect, and pending storage',async()=>{
  const {client,sockets,timers,stored}=harness();await client.ready;
  const ws=sockets[0];ws.onopen();ws.frame({type:'ready',cursor:0});
  const options={mentioned:true,reply_to:'parent-1',sender_id:'spoof',sender_name:'spoof',session_id:'other'};
  await client.chat('hello','group-1',options);
  const expected={type:'send',message_id:'group-1',text:'hello',mentioned:true,reply_to:'parent-1'};
  assert.deepEqual(ws.sent.at(-1),expected);
  options.mentioned=false;options.reply_to='changed';
  assert.deepEqual(JSON.parse(stored.get(client.storageKey)).pending['group-1'],
    {text:'hello',mentioned:true,reply_to:'parent-1'});
  ws.frame({type:'error',code:'busy',message_id:'group-1'});
  [...timers.values()].at(-1)();
  assert.deepEqual(ws.sent.at(-1),expected);
  ws.close();[...timers.values()].at(-1)();
  const resumed=sockets[1];resumed.onopen();resumed.frame({type:'ready',cursor:0});
  assert.deepEqual(resumed.sent.at(-1),expected);
  resumed.frame({type:'receipt',message_id:'group-1',status:'recorded'});
  assert.equal(client.state.pending['group-1'],undefined);
  assert.equal(client.retries['group-1'],undefined);
  assert.equal(JSON.parse(stored.get(client.storageKey)).pending['group-1'],undefined);
  client.close();
});

test('explicit false mention remains false on reconnect',async()=>{
  const {client,sockets,timers}=harness();await client.ready;
  const ws=sockets[0];ws.onopen();ws.frame({type:'ready',cursor:0});
  await client.chat('@bot is plain text','observed-1',{mentioned:false});
  const expected={type:'send',message_id:'observed-1',text:'@bot is plain text',mentioned:false};
  assert.deepEqual(ws.sent.at(-1),expected);
  ws.close();[...timers.values()].at(-1)();
  const resumed=sockets[1];resumed.onopen();resumed.frame({type:'ready',cursor:0});
  assert.deepEqual(resumed.sent.at(-1),expected);
  client.close();
});

test('invalid group options reject before sending or persisting',async()=>{
  const {client,sockets}=harness();await client.ready;
  const ws=sockets[0];ws.onopen();ws.frame({type:'ready',cursor:0});
  for (const options of [null,[],true,'group',{mentioned:'true'},{mentioned:1},{mentioned:null},
    {reply_to:42},{reply_to:null},{reply_to:''},{reply_to:' '},{reply_to:'x'.repeat(256)}]) {
    await assert.rejects(client.chat('hello','invalid',options),/options|mentioned|reply_to/);
    assert.equal(client.state.pending.invalid,undefined);
  }
  assert.equal(ws.sent.filter(frame=>frame.type==='send').length,0);
  client.close();
});

test('attachment-only submissions keep stable file IDs across reconnect', async () => {
  const {client,sockets} = harness(); await client.ready;
  const file = 'f_' + 'a'.repeat(32);
  const ws = sockets[0]; ws.onopen(); ws.frame({type:'ready',cursor:0});
  await client.chat('', 'file-only', {attachments:[file]});
  assert.deepEqual(ws.sent.at(-1), {type:'send',message_id:'file-only',text:'',attachments:[file]});
  assert.deepEqual([...client.state.pending['file-only'].attachments], [file]);
  for (const attachments of ['url', ['../../secret'], Array(9).fill(file)])
    await assert.rejects(client.chat('', 'invalid', {attachments}), /attachment/i);
  client.close();
});

test('file APIs authenticate headers and keep bearer credentials out of URLs', async () => {
  const calls = [], item = {id:'f_' + 'a'.repeat(32), name:'参考.txt', size:4, mime_type:'text/plain'};
  const {client} = harness({}, async (url, options) => {
    calls.push({url, options});
    return {ok:true, json:async()=>item, blob:async()=>({bytes:'test'})};
  });
  await client.ready;
  const file = {name:'参考.txt', size:4};
  assert.equal((await client.upload(file)).id, item.id);
  assert.equal((await client.download(item)).name, '参考.txt');
  assert.equal(calls[0].options.headers['X-File-Name'], encodeURIComponent(file.name));
  for (const call of calls) {
    assert.equal(call.options.headers.Authorization, 'Bearer valid-token');
    assert.ok(!call.url.includes('valid-token') && !call.url.includes('?'));
  }
  client.close();
});

test('corrupt cache is reported and preserved while external chat can reconnect', async()=>{
  const storage={getItem:()=>'{broken',setItem:()=>{throw new Error('quota');}};
  const {client,sockets}=harness({token:'external',sessionId:'room',storage});
  const errors=[];client.on('error',e=>errors.push(e));await client.ready;
  assert.equal(sockets.length,1);
  assert.ok(errors.some(e=>e.code==='cache_corrupt'));
  await assert.rejects(client.chat('keep my draft','unsent'),/storage/i);
  assert.equal(client.state.pending.unsent,'keep my draft');
  client.close();
});

test('bounded cache keeps unsent data and transient errors never discard it', async()=>{
  const {client,sockets,stored}=harness({maxCachedMessages:2});await client.ready;
  const ws=sockets[0];ws.onopen();ws.frame({type:'ready',cursor:0});
  await client.chat('pending','unsent');
  for(let n=1;n<=4;n++)ws.frame({type:'message',event_id:'e'+n,sequence:n,text:'hi'});
  assert.equal(JSON.parse(stored.get(client.storageKey)).messages.length,2);
  ws.frame({type:'error',code:'internal_error',message_id:'unsent'});
  assert.equal(client.state.pending.unsent,'pending');
  client.close();
});

test('storage quota leaves pending visible and allows retry with the same ID', async()=>{
  let full=true;
  const stored=new Map();
  const storage={getItem:key=>stored.get(key),setItem:(key,value)=>{if(full)throw new Error('quota');stored.set(key,value);}};
  const {client,sockets}=harness({token:'external',sessionId:'room',storage});await client.ready;
  const ws=sockets[0];ws.onopen();ws.frame({type:'ready',cursor:0});
  await assert.rejects(client.chat('draft','same-id'),/storage/i);
  assert.equal(client.state.pending['same-id'],'draft');
  assert.equal(ws.sent.filter(x=>x.type==='send').length,0);
  full=false;await client.chat('draft','same-id');
  assert.equal(ws.sent.at(-1).message_id,'same-id');
  assert.equal(JSON.parse(stored.get(client.storageKey)).pending['same-id'],'draft');
  client.close();
});

test('pending capacity refuses new input without evicting prior unsent messages', async()=>{
  const {client}=harness();await client.ready;
  for(let n=0;n<100;n++)await client.chat('draft '+n,'id-'+n);
  await assert.rejects(client.chat('overflow','overflow'),/Too many unsent/);
  assert.equal(Object.keys(client.state.pending).length,100);
  assert.equal(client.state.pending['id-0'],'draft 0');
  client.close();
});

test('older messages use exclusive oldest cursor without rewinding replay position', async()=>{
  const {client,sockets}=harness();await client.ready;
  const ws=sockets[0];ws.onopen();ws.frame({type:'message',event_id:'new',sequence:30,text:'new'});
  ws.frame({type:'ready',cursor:35,has_more:true});
  client.api=async path=>{assert.match(path,/before_sequence=30/);return {
    messages:[{type:'message',event_id:'old',sequence:10,text:'old'}],has_more:false,cursor:10,through:35};};
  await client.loadOlder();
  assert.equal(client.state.cursor,35);
  assert.equal(client.state.messages.map(x=>x.event_id).join(','),'old,new');
  assert.equal(client.hasMore,false);client.close();
});

test('closed clients ignore late frames and cannot recreate cleared cache', async()=>{
  const {client,sockets,stored}=harness();await client.ready;
  const ws=sockets[0];client.close();stored.delete(client.storageKey);
  ws.frame({type:'message',event_id:'late',sequence:1,text:'late'});
  assert.equal(stored.has(client.storageKey),false);
  assert.equal(client.state.messages.length,0);
});

test('stream previews are memory only, session scoped, final wins over late frames', async()=>{
  const {client,sockets,stored}=harness();await client.ready;
  const ws=sockets[0];ws.onopen();ws.frame({type:'ready',cursor:4});
  const stream=(phase,text)=>({type:'stream',session_id:'s',run_id:'run',request_id:'req',phase,...(text===undefined?{}:{text})});
  const seen=[];client.on('stream', value=>seen.push(value));
  const before=stored.get(client.storageKey);
  ws.frame(stream('start'));ws.frame(stream('delta','hello'));
  assert.equal(client.streams.get('req').text,'hello');
  assert.equal(client.state.cursor,4);assert.equal(stored.get(client.storageKey),before);
  ws.frame({...stream('delta','wrong'),session_id:'other'});
  assert.equal(client.streams.get('req').text,'hello');
  ws.frame(stream('end'));assert.equal(client.streams.get('req').text,'hello');
  ws.frame({type:'message',session_id:'s',event_id:'e',sequence:5,role:'bot',text:'hello!',request_id:'req'});
  assert.equal(client.streams.size,0);
  const count=seen.length;
  ws.frame(stream('delta','late'));ws.frame(stream('end'));ws.frame(stream('start'));
  assert.equal(client.streams.size,0);assert.equal(seen.length,count);
  assert.ok(!stored.get(client.storageKey).includes('"streams"'));
  client.close();
});

test('disconnect clears previews and delayed frames cannot resurrect them', async()=>{
  const {client,sockets}=harness();await client.ready;
  const ws=sockets[0];ws.onopen();ws.frame({type:'ready',cursor:0});
  const frame={type:'stream',session_id:'s',run_id:'run',request_id:'req'};
  ws.frame({...frame,phase:'start'});ws.frame({...frame,phase:'delta',text:'partial'});
  assert.equal(client.streams.size,1);
  ws.close();assert.equal(client.streams.size,0);
  ws.frame({...frame,phase:'delta',text:'late'});assert.equal(client.streams.size,0);
  client.close();
});

test('preview memory is bounded and an overflow waits for the durable final', async()=>{
  const {client,sockets}=harness();await client.ready;
  const ws=sockets[0];ws.onopen();ws.frame({type:'ready',cursor:0});
  const frame={type:'stream',session_id:'s',run_id:'run',request_id:'req'};
  ws.frame({...frame,phase:'start'});
  for(let i=0;i<3;i++) ws.frame({...frame,phase:'delta',text:'x'.repeat(65536)});
  assert.equal(client.streams.size,0);
  ws.frame({...frame,phase:'start'});assert.equal(client.streams.size,0);
  for(let i=0;i<100;i++) ws.frame({...frame,request_id:'req'+i,phase:'start'});
  assert.equal(client.streams.size,32);
  client.close();
});

test('error after stream end clears an uncommitted preview', async()=>{
  const {client,sockets}=harness();await client.ready;
  const ws=sockets[0];ws.onopen();ws.frame({type:'ready',cursor:0});
  const frame={type:'stream',session_id:'s',run_id:'run',request_id:'req'};
  ws.frame({...frame,phase:'start'});ws.frame({...frame,phase:'end'});ws.frame({...frame,phase:'error'});
  assert.equal(client.streams.size,0);
  client.close();
});

test('tool-only request closes its empty preview before the next text request commits', async()=>{
  const {client,sockets}=harness();await client.ready;
  const ws=sockets[0];ws.onopen();ws.frame({type:'ready',cursor:0});
  const frame={type:'stream',session_id:'s',run_id:'run',request_id:'tool-only'};
  const seen=[];client.on('stream', data=>seen.push({phase:data.phase,size:client.streams.size}));
  ws.frame({...frame,phase:'start'});ws.frame({...frame,phase:'end'});
  assert.equal(client.streams.size,0);
  assert.equal(seen.at(-1).phase,'end');assert.equal(seen.at(-1).size,0);
  ws.frame({...frame,phase:'delta',text:'late'});assert.equal(client.streams.size,0);
  const answer={...frame,request_id:'answer'};
  ws.frame({...answer,phase:'start'});ws.frame({...answer,phase:'delta',text:'done'});ws.frame({...answer,phase:'end'});
  assert.equal(client.streams.size,1);
  ws.frame({type:'message',session_id:'s',event_id:'e',sequence:1,role:'bot',request_id:'answer',text:'done'});
  assert.equal(client.streams.size,0);assert.equal(client.state.messages.length,1);
  client.close();
});
