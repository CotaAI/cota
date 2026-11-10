import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function setup() {
  let nextId = 0;
  const context = {console, URL, URLSearchParams, queueMicrotask, crypto: {randomUUID: () => 'submission-' + ++nextId}};
  const path = new URL('../../cota/webapp/static/app.js', import.meta.url);
  if (fs.existsSync(path)) vm.runInNewContext(fs.readFileSync(path, 'utf8'), context);
  assert.ok(context.CotaChat, 'chat application controller must be available');
  const entries = new Map();
  const storage = {get length() {return entries.size;}, key: i => [...entries.keys()][i],
    getItem: k => entries.get(k) || null, setItem: (k,v) => entries.set(k,v), removeItem: k => entries.delete(k)};
  const requests = [];
  const clients = [];
  class Client {
    constructor(options) {this.options=options; this.state={messages:[], pending:{}}; this.handlers={}; clients.push(this);}
    on(name, fn) {this.handlers[name]=fn;return this;}
    close() {this.closed=true;}
    emit(name, value={}) {this.handlers[name]?.(value);}
    async chat(text, id, options) {this.sent={text,id,options};this.state.pending[id]={text,...options}; return id;}
  }
  const fetch = (path, options) => new Promise(resolve => requests.push({path, options, resolve: (body, status=200) => resolve({ok:status<400,status,json:async()=>body})}));
  const app = new context.CotaChat.Controller({fetch, Client, storage, changed:()=>{}});
  app.identity={token:'token-a',user_id:'alice',name:'Alice'};
  return {app,requests,clients,storage,api:context.CotaChat};
}
const tick = () => new Promise(resolve => setImmediate(resolve));

test('reply links preserve text and allow only explicit HTTP or same-origin paths', () => {
  const {api} = setup();
  assert.equal(typeof api.messageParts, 'function');
  const parts = api.messageParts('绘本：[PDF](/books/token/book.pdf) 和 [说明](https://example.com/print)\n<b>原样</b>');
  assert.equal(parts.filter(part => part.href).length, 2);
  assert.equal(parts.find(part => part.label === 'PDF').href, '/books/token/book.pdf');
  assert.ok(parts.some(part => part.text?.includes('<b>原样</b>')));
  for (const url of ['javascript:alert(1)', 'data:text/html,bad', 'file:///etc/passwd', '//evil.com/a', '/\\evil.com/a', 'https://u:p@example.com/a']) {
    assert.equal(api.messageParts(`[bad](${url})`).filter(part => part.href).length, 0);
  }
});

test('late conversation fetch cannot replace the current room', async () => {
  const {app,requests,clients} = setup();
  const first=app.open('old'); const second=app.open('new');
  requests[1].resolve({session_id:'new',members:[]}); await second;
  requests[0].resolve({session_id:'old',members:[]}); await first;
  assert.equal(app.room.session_id,'new'); assert.equal(clients.length,1);
});

test('old socket callbacks cannot add messages or sign out a new room', async () => {
  const {app,requests,clients} = setup();
  let loading=app.open('one'); requests[0].resolve({session_id:'one',members:[]}); await loading;
  loading=app.open('two'); requests[1].resolve({session_id:'two',members:[]}); await loading;
  clients[0].state.messages=[{event_id:'old',sequence:1,text:'old'}];
  clients[0].emit('message'); clients[0].emit('error',{code:'unauthorized'});
  assert.equal(clients[0].closed,true); assert.equal(app.messages.length,0); assert.equal(app.identity.user_id,'alice');
  assert.notEqual(clients[0].options.storageKey,clients[1].options.storageKey);
});

test('messages are deduplicated and ordered, reply does not imply mention', async () => {
  const {app,requests,clients}=setup();
  const loading=app.open('one'); requests[0].resolve({session_id:'one',members:[]}); await loading;
  clients[0].state.messages=[{event_id:'b',sequence:2},{event_id:'a',sequence:1},{event_id:'b',sequence:2}];
  clients[0].emit('message'); await tick(); assert.equal(app.messages.map(x=>x.event_id).join(','),'a,b');
  await app.send('hello',{mentioned:false,reply_to:'a'});
  assert.equal(clients[0].sent.options.mentioned,false);assert.equal(clients[0].sent.options.reply_to,'a');
  assert.equal(Object.keys(app.pending).length,1);
});

test('expired identity closes the socket, preserves unsent app cache and never resends', async () => {
  const {app,requests,clients,storage}=setup();
  const loading=app.open('one'); requests[0].resolve({session_id:'one',members:[]}); await loading;
  storage.setItem('cota.chat.app.v1:identity','secret'); storage.setItem(clients[0].options.storageKey,'pending'); storage.setItem('unrelated','keep');
  clients[0].emit('error',{code:'unauthorized'});
  assert.equal(requests[1]?.path, '/chat/api/me');
  requests[1].resolve({error:'unauthorized',message:'expired'},403); await tick();
  assert.equal(app.identity,null);assert.equal(clients[0].closed,true);assert.equal(storage.getItem('unrelated'),'keep');
  assert.equal(storage.getItem(clients[0].options.storageKey),'pending');
  assert.match(app.notice,/失效/); await assert.rejects(app.send('again'),/身份/);
});

test('late unauthorized API response cannot expire a replacement identity', async () => {
  const {app,requests}=setup();
  const loading=app.open('one'); app.signout(); app.identity={token:'new',user_id:'bob'};
  requests[0].resolve({error:'unauthorized',message:'expired'},401); await loading;
  assert.equal(app.identity.user_id,'bob'); assert.equal(app.room,null);
});

test('invite fragment is removed before login and restored from session storage', () => {
  const {api,storage}=setup(); let replaced;
  assert.equal(api.captureInvite({hash:'#invite=private-token',pathname:'/chat/',search:''},{replaceState:(_,__,url)=>replaced=url},storage),'private-token');
  assert.equal(replaced,'/chat/');
  assert.equal(api.captureInvite({hash:'',pathname:'/chat/',search:''},{},storage),'private-token');
});

test('failed receipt is visible and does not automatically resubmit', async () => {
  const {app,requests,clients}=setup(); const opening=app.open('one'); requests[0].resolve({session_id:'one',members:[]}); await opening;
  await app.send('hello'); const sent=clients[0].sent;
  delete clients[0].state.pending['submission-1']; clients[0].emit('receipt',{message_id:'submission-1',status:'failed'});
  assert.match(app.notice,/未完成/); assert.equal(clients[0].sent,sent); assert.equal(app.receipts['submission-1'].status,'failed');
});


test('removed group member keeps valid visitor identity and closes inaccessible room', async () => {
  const {app,requests,clients}=setup(); const opening=app.open('group');
  requests[0].resolve({session_id:'group',mode:'group',members:[]}); await opening;
  clients[0].emit('error',{code:'unauthorized'});
  assert.equal(clients[0].closed,true);
  assert.equal(requests[1]?.path, '/chat/api/me');
  requests[1].resolve({user_id:'alice',name:'Alice'}); await tick();
  assert.equal(app.identity.user_id,'alice'); assert.equal(app.room,null);
  requests[2].resolve({conversations:[],has_more:false}); await tick();
  assert.match(app.notice,/访问/);
});

test('identity storage separates same room across visitors', async () => {
  const {app,requests,clients}=setup(); let opening=app.open('shared');
  requests[0].resolve({session_id:'shared',members:[]}); await opening;
  app.signout(); app.identity={token:'b',user_id:'bob',name:'Bob'};
  opening=app.open('shared'); requests[1].resolve({session_id:'shared',members:[]}); await opening;
  assert.notEqual(clients[0].options.storageKey,clients[1].options.storageKey);
});

test('identity changed in another tab closes this view without deleting the new credential', () => {
  const {app,storage}=setup(); const next='{"token":"new","user_id":"bob"}';
  storage.setItem('cota.chat.app.v1:identity',next);
  app.signout('changed elsewhere',false);
  assert.equal(app.identity,null); assert.equal(storage.getItem('cota.chat.app.v1:identity'),next);
});

test('stale conversation listing cannot overwrite a newer refresh', async () => {
  const {app,requests}=setup(); const old=app.list(); const fresh=app.list();
  requests[1].resolve({conversations:[{session_id:'fresh'}],has_more:false}); await fresh;
  requests[0].resolve({conversations:[{session_id:'old'}],has_more:true}); await old;
  assert.equal(app.conversations[0].session_id,'fresh'); assert.equal(app.hasMore,false);
});

test('nickname login persists identity then loads conversations with bearer authorization', async () => {
  const {app,requests,storage}=setup(); app.identity=null;
  const login=app.login(' 小明 ');
  assert.equal(JSON.parse(requests[0].options.body).name,'小明');
  requests[0].resolve({token:'visitor',user_id:'visitor-1',name:'小明'}); await tick();
  assert.equal(requests[1].options.headers.Authorization,'Bearer visitor');
  requests[1].resolve({conversations:[],has_more:false}); await login;
  assert.equal(JSON.parse(storage.getItem('cota.chat.app.v1:identity')).user_id,'visitor-1');
});

test('membership denial verifies identity without signing the visitor out', async () => {
  const {app,requests}=setup(); const opening=app.open('removed');
  requests[0].resolve({error:'unauthorized',message:'No access'},403); await tick();
  assert.equal(requests[1]?.path,'/chat/api/me');
  requests[1].resolve({user_id:'alice',name:'Alice'}); await opening;
  assert.equal(app.identity.user_id,'alice'); assert.equal(app.room,null); assert.equal(app.notice,'No access');
});

test('nickname login failure remains visible after the identity epoch changes', async () => {
  const {app,requests}=setup(); app.identity=null;
  const login=app.login('小明');
  requests[0].resolve({error:'invalid_request',message:'昵称不可用'},400);
  await assert.rejects(login,/昵称不可用/);
  assert.equal(app.notice,'昵称不可用'); assert.equal(app.identity,null);
});

test('failed invite acceptance retains captured invite for an explicit retry', async () => {
  const {api,app,storage}=setup(); storage.setItem('cota.chat.app.v1:invite','secret');
  assert.equal(typeof api.acceptInvite,'function');
  app.join=async()=>{throw new Error('network unavailable');};
  await assert.rejects(api.acceptInvite(app,'secret',storage),/network unavailable/);
  assert.equal(storage.getItem('cota.chat.app.v1:invite'),'secret');
  app.join=async()=>{};
  assert.equal(await api.acceptInvite(app,'secret',storage),true);
  assert.equal(storage.getItem('cota.chat.app.v1:invite'),null);
});

test('late invite acceptance cannot discard a newer invite or changed account invitation', async () => {
  const {api,app,storage}=setup(); assert.equal(typeof api.acceptInvite,'function');
  storage.setItem('cota.chat.app.v1:invite','first');
  let resolve; app.join=()=>new Promise(done=>{resolve=done;});
  const first=api.acceptInvite(app,'first',storage);
  storage.setItem('cota.chat.app.v1:invite','second'); resolve();
  assert.equal(await first,false); assert.equal(storage.getItem('cota.chat.app.v1:invite'),'second');
  const second=api.acceptInvite(app,'second',storage);
  app.identity={token:'new-account',user_id:'bob'}; resolve();
  assert.equal(await second,false); assert.equal(storage.getItem('cota.chat.app.v1:invite'),'second');
});

test('nickname and conversation title form limits match the API', () => {
  const html=fs.readFileSync(new URL('../../cota/webapp/static/index.html',import.meta.url),'utf8');
  assert.match(html, /id="nickname"[^>]*maxlength="60"/);
  assert.match(html, /id="chat-title"[^>]*maxlength="100"/);
});


test('a batch of 1000 cached message events causes one state render', async () => {
  const {app,requests,clients}=setup(); const opening=app.open('history');
  requests[0].resolve({session_id:'history',members:[]}); await opening; await tick();
  let renders=0; app.changed=()=>{renders++;};
  clients[0].state.messages=Array.from({length:1000},(_,index)=>({event_id:'event-'+index,sequence:index,text:'history'}));
  for (const message of clients[0].state.messages) clients[0].emit('message',message);
  await tick();
  assert.equal(app.messages.length,1000); assert.equal(renders,1);
});

test('scheduled old-room message render cannot overwrite a newly selected room', async () => {
  const {app,requests,clients}=setup(); const first=app.open('old');
  requests[0].resolve({session_id:'old',members:[]}); await first; await tick();
  clients[0].state.messages=[{event_id:'stale',sequence:1}]; clients[0].emit('message');
  const next=app.open('new'); await tick();
  assert.equal(app.messages.length,0);
  requests[1].resolve({session_id:'new',members:[]}); await next; await tick();
  assert.equal(app.room.session_id,'new'); assert.equal(app.messages.length,0);
});

test('read acknowledgements use the visible connected room cursor', async()=>{
  const {app,requests,clients}=setup();
  const loading=app.open('one'); requests[0].resolve({session_id:'one',members:[]}); await loading;
  clients[0].connected=true;clients[0].state.cursor=12;
  const reading=app.markRead();
  assert.equal(requests[1].path,'/chat/api/conversations/one/read');
  assert.deepEqual(JSON.parse(requests[1].options.body),{sequence:12});
  requests[1].resolve({read_sequence:12}); await reading;
  assert.equal(app.readSequence,12);
});

test('room switch retains quota-failed pending in memory and restores it on return', async()=>{
  const {app,requests,clients}=setup();
  let opening=app.open('one');requests[0].resolve({session_id:'one',members:[]});await opening;
  clients[0].storageFailed=true;
  clients[0].state.pending['unsaved']='keep this draft';
  opening=app.open('two');requests[1].resolve({session_id:'two',members:[]});await opening;
  assert.equal(clients[0].closed,true);
  opening=app.open('one');requests[2].resolve({session_id:'one',members:[]});await opening;
  assert.equal(clients[2].state.pending['unsaved'],'keep this draft');
  await tick();assert.equal(app.pending.unsaved,'keep this draft');
});


test('retrying a quota-failed draft reuses its input ID instead of enqueueing twice', async()=>{
  const {app,requests,clients}=setup();
  const opening=app.open('one');requests[0].resolve({session_id:'one',members:[]});await opening;
  const client=clients[0], sent=[];
  client.chat=async(text,id,options)=>{
    client.state.pending[id]={text,...options};sent.push(id);
    if(sent.length===1){client.storageFailed=true;throw new Error('storage unavailable');}
    client.storageFailed=false;return id;
  };
  await assert.rejects(app.send('same draft',{mentioned:true}),/storage/);
  await app.send('same draft',{mentioned:true});
  assert.deepEqual(sent,['submission-1','submission-1']);
  assert.deepEqual(Object.keys(client.state.pending),['submission-1']);
});

test('terminal receipt clears failed-draft retry identity for later deliberate sends', async()=>{
  const {app,requests,clients}=setup();
  const opening=app.open('one');requests[0].resolve({session_id:'one',members:[]});await opening;
  const client=clients[0];
  client.failedDraft={fingerprint:JSON.stringify(['same',undefined,undefined]),id:'old-id'};
  client.emit('receipt',{message_id:'old-id',status:'completed'});
  await app.send('same');
  assert.equal(client.sent.id,'submission-1');
});
