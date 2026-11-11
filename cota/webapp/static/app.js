/* Optional chat companion. Uses only the public HTTP API and CotaClient. */
(function (root) {
  'use strict';
  const PREFIX = 'cota.chat.app.v1:';
  const IDENTITY_KEY = PREFIX + 'identity';
  const INVITE_KEY = PREFIX + 'invite';
  function captureInvite(location, history, storage) {
    const params = new URLSearchParams(location.hash.slice(1));
    const invite = params.get('invite');
    if (params.has('invite')) {
      history.replaceState(null, '', location.pathname + location.search);
      if (invite) storage.setItem(INVITE_KEY, invite);
    }
    return invite || storage.getItem(INVITE_KEY) || '';
  }
  async function acceptInvite(app, invite, storage) {
    const token = app.identity?.token;
    if (!token || !invite) return false;
    await app.join(invite);
    if (token !== app.identity?.token || storage.getItem(INVITE_KEY) !== invite) return false;
    storage.removeItem(INVITE_KEY);
    return true;
  }
  class Controller {
    constructor({fetch, Client, storage, changed}) {
      Object.assign(this, {fetch, Client, storage, changed});
      this.unsavedRooms = new Map(); this.clientKey = null;
      this.identity = null; this.config = {}; this.conversations = []; this.hasMore = false;
      this.room = null; this.client = null; this.messages = []; this.previews = []; this.pending = {}; this.receipts = {};
      this.notice = ''; this.status = ''; this.epoch = 0; this.listEpoch = 0; this.identityEpoch = 0;
    }
    update() {this.changed(this);}
    async api(path, data) {
      const token = this.identity?.token;
      const response = await this.fetch('/chat/api/' + path, {
        method: data === undefined ? 'GET' : 'POST',
        headers: {'Content-Type': 'application/json', ...(token ? {Authorization: 'Bearer ' + token} : {})},
        ...(data === undefined ? {} : {body: JSON.stringify(data)})
      });
      const value = await response.json();
      if (!response.ok) {
        if ([401, 403].includes(response.status) && token && token === this.identity?.token) {
          if (path === 'me') this.expire();
          else {
            try {await this.api('me');} catch (_) { /* me expires only proven invalid credentials */ }
          }
        }
        const error = new Error(value.message || '请求失败，请稍后再试');
        error.code = value.error; throw error;
      }
      return value;
    }
    async start() {
      this.config = await this.api('config'); this.update();
      let saved;
      try {saved = JSON.parse(this.storage.getItem(IDENTITY_KEY));} catch (_) {this.storage.removeItem(IDENTITY_KEY);}
      if (!saved?.token || !saved?.user_id) return;
      this.identity = saved;
      const epoch = this.identityEpoch;
      const me = await this.api('me');
      if (epoch !== this.identityEpoch) return;
      this.identity = {...saved, ...me}; this.update(); await this.list();
    }
    async login(name) {
      const epoch = ++this.identityEpoch;
      try {
        const identity = await this.api('guests', {name: name.trim()});
        if (epoch !== this.identityEpoch) return;
        this.storage.setItem(IDENTITY_KEY, JSON.stringify(identity)); this.identity = identity;
        this.notice = ''; this.update(); await this.list();
      } catch (error) {
        if (epoch === this.identityEpoch) {this.notice = error.message || '无法创建访客，请稍后再试'; this.update();}
        throw error;
      }
    }
    async list(more = false) {
      const token = this.identity?.token; if (!token) return;
      const epoch = ++this.listEpoch;
      const page = await this.api('conversations?offset=' + (more ? this.conversations.length : 0) + '&limit=100&summaries=1');
      if (token !== this.identity?.token || epoch !== this.listEpoch) return;
      this.conversations = more ? [...this.conversations, ...page.conversations] : page.conversations;
      this.hasMore = page.has_more; this.update();
    }
    closeRoom() {
      ++this.epoch;
      const client = this.client;
      if (client && (client.storageFailed || client.cacheBlocked) && Object.keys(client.state.pending).length) {
        this.unsavedRooms.set(this.clientKey, {state: {...client.state, messages: client.state.messages.slice(-200)},
          failedDraft: client.failedDraft});
      }
      this.client = null; this.clientKey = null; client?.close();
      this.room = null; this.messages = []; this.previews = []; this.pending = {}; this.receipts = {}; this.status = ''; this.readSequence = 0;
    }
    async open(id) {
      const cacheKey = PREFIX + 'session:' + encodeURIComponent(this.identity?.user_id) + ':' + encodeURIComponent(id);
      if (this.unsavedRooms.size >= 32 && !this.unsavedRooms.has(cacheKey))
        throw new Error('当前标签页有多个会话的未保存消息。请先返回这些会话重试保存，再打开新会话。');
      this.closeRoom(); const epoch = this.epoch; const identity = this.identity;
      if (!identity) return;
      this.notice = ''; this.status = '正在打开…'; this.update();
      const active = () => epoch === this.epoch && identity.token === this.identity?.token;
      try {
        const room = await this.api('conversations/' + encodeURIComponent(id));
        if (!active()) return;
        this.room = room; this.status = '连接中…';
        const client = this.client = new this.Client({token: identity.token, sessionId: id,
          storageKey: cacheKey});
        this.clientKey = cacheKey;
        const unsaved = this.unsavedRooms.get(cacheKey);
        if (unsaved) {
          client.state = {...unsaved.state, token: identity.token, session_id: id};
          client.failedDraft = unsaved.failedDraft;
          client.storageFailed = true;
          this.unsavedRooms.delete(cacheKey);
          this.notice = '已恢复此标签页中尚未保存的消息，请保持页面打开并重试。';
        }
        const guard = fn => data => {if (active() && this.client === client) fn(data);};
        let syncScheduled = false;
        const sync = () => {
          if (syncScheduled) return;
          syncScheduled = true;
          // Cached history emits synchronously. Take one final snapshot for the
          // whole batch, and re-check ownership when this deferred work runs.
          queueMicrotask(() => {
            syncScheduled = false;
            if (!active() || this.client !== client) return;
            this.messages = [...new Map(client.state.messages.map(message => [message.event_id, message])).values()]
              .sort((a, b) => a.sequence - b.sequence);
            this.previews = [...(client.streams?.values() || [])];
            this.pending = {...client.state.pending}; this.update();
            if (client.connected) this.markRead().catch(() => {});
          });
        };
        client.on('history', guard(sync));
        client.on('stream', guard(data => {
          if (data.phase === 'error' || data.interrupted)
            this.notice = '实时预览已中断，最终结果请以保存的消息为准';
          sync();
        }));
        client.on('message', guard(() => {sync(); if (room.mode === 'group') this.refreshMembers(epoch);}));
        client.on('connected', guard(() => {this.status = '已连接'; sync(); this.refreshMembers(epoch);}));
        client.on('disconnected', guard(() => {this.status = '连接中断，正在重连…'; this.previews = []; this.update();}));
        client.on('receipt', guard(data => {
          if (client.failedDraft?.id === data.message_id && !['queued', 'running'].includes(data.status))
            client.failedDraft = null;
          this.receipts[data.message_id] = data;
          if (['failed', 'interrupted'].includes(data.status)) this.notice = '本次处理未完成。请检查聊天记录，确认后发送新的请求。';
          sync();
        }));
        client.on('error', guard(data => {
          if (data.code === 'unauthorized') {this.checkRoomAccess(epoch); return;}
          this.notice = data.code === 'busy' ? '服务繁忙，消息将在连接恢复后继续提交。' : data.message || '发送失败，请检查聊天记录后重试。';
          if (data.message_id) this.receipts[data.message_id] = {status: data.code === 'busy' ? 'queued' : 'failed'};
          sync();
        }));
        sync();
      } catch (error) {if (active()) {this.status = ''; this.notice = error.message; this.update();}}
    }
    async checkRoomAccess(epoch) {
      this.client?.close();
      try {
        await this.api('me');
        if (epoch !== this.epoch) return;
        this.closeRoom(); this.notice = '已失去此会话的访问权限。你的访客身份仍然有效。'; this.update();
        await this.list();
      } catch (error) {
        if (epoch === this.epoch && this.identity) {
          this.closeRoom(); this.notice = '暂时无法验证会话权限，请刷新会话列表后重试。'; this.update();
        }
      }
    }
    async refreshMembers(epoch = this.epoch) {
      if (!this.room || this.membersLoading === epoch) return;
      const id = this.room.session_id; this.membersLoading = epoch;
      try {
        const room = await this.api('conversations/' + encodeURIComponent(id));
        if (epoch === this.epoch && this.room?.session_id === id) {this.room = room; this.update();}
      } catch (error) {
        if (epoch === this.epoch && this.identity) {
          if (['unauthorized', 'forbidden', 'not_found'].includes(error.code)) this.closeRoom();
          this.notice = error.message; this.update();
        }
      } finally {if (this.membersLoading === epoch) this.membersLoading = null;}
    }
    async send(text, options = {}) {
      if (!this.identity || !this.client) throw new Error('请先建立访客身份并打开会话');
      if (!text.trim() && !options.attachments?.length) return;
      const client = this.client, epoch = this.epoch;
      let id;
      const fingerprint = JSON.stringify([text, options.mentioned, options.reply_to, options.attachments]);
      const messageId = client.failedDraft?.fingerprint === fingerprint ? client.failedDraft.id : crypto.randomUUID();
      try {
        id = await client.chat(text, messageId, options);
        client.failedDraft = null;
      } catch (error) {
        if (Object.hasOwn(client.state.pending, messageId)) client.failedDraft = {fingerprint, id: messageId};
        throw error;
      }
      finally {
        if (epoch === this.epoch && client === this.client) {this.pending = {...client.state.pending}; this.update();}
      }
      if (epoch === this.epoch && client === this.client) {
        this.pending = {...client.state.pending};
        this.notice = client.connected ? '' : '消息已保存在此浏览器，重连后提交。'; this.update();
      }
      return id;
    }
    async older() {
      if (this.client) await this.client.loadOlder();
    }
    async markRead() {
      const client = this.client, epoch = this.epoch, sequence = client?.state.cursor;
      if (!client?.connected || !this.room || !Number.isSafeInteger(sequence) ||
          sequence <= (this.readSequence || 0) || this.readLoading === epoch ||
          (typeof document !== 'undefined' && document.hidden)) return;
      this.readLoading = epoch;
      try {
        const value = await this.api('conversations/' + encodeURIComponent(this.room.session_id) + '/read', {sequence});
        if (epoch === this.epoch) {
          this.readSequence = value.read_sequence;
          const room = this.conversations.find(r => r.session_id === this.room?.session_id);
          if (room) room.unread = 0;
          this.update();
        }
      } finally {if (this.readLoading === epoch) this.readLoading = null;}
    }
    async create(title) {
      const token = this.identity?.token;
      const room = await this.api('conversations', {title: title.trim()});
      if (token !== this.identity?.token) return;
      await this.list(); if (token === this.identity?.token) await this.open(room.session_id);
    }
    async join(invite) {
      const token = this.identity?.token;
      const room = await this.api('join', {invite});
      if (token !== this.identity?.token) return;
      await this.list(); if (token === this.identity?.token) await this.open(room.session_id);
    }
    async invite() {
      if (!this.room) return;
      const epoch = this.epoch;
      const result = await this.api('conversations/' + encodeURIComponent(this.room.session_id) + '/invite', {});
      return epoch === this.epoch ? result : null;
    }
    async remove(user_id) {
      if (!this.room) return;
      const epoch = this.epoch;
      await this.api('conversations/' + encodeURIComponent(this.room.session_id) + '/remove', {user_id});
      if (epoch === this.epoch) await this.refreshMembers(epoch);
    }
    async leave() {
      if (!this.room) return;
      const epoch = this.epoch;
      await this.api('conversations/' + encodeURIComponent(this.room.session_id) + '/leave', {});
      if (epoch === this.epoch) {this.closeRoom(); this.update(); await this.list();}
    }
    expire() {this.signout('访客凭据已失效。旧消息缓存与未发送消息已保留；不会用新身份自动重发。', false); this.storage.removeItem(IDENTITY_KEY);}
    signout(notice = '', clearCache = true) {
      ++this.identityEpoch; ++this.listEpoch; this.closeRoom(); this.identity = null; this.conversations = []; this.hasMore = false;
      if (clearCache) this.unsavedRooms.clear();
      const keys = Array.from({length: this.storage.length}, (_, i) => this.storage.key(i));
      if (clearCache) for (const key of keys) if (key?.startsWith(PREFIX)) this.storage.removeItem(key);
      this.notice = notice; this.update();
    }
  }
  function messageParts(text) {
    const parts = [], pattern = /\[([^\]\n]+)\]\(([^\s)]+)\)/g;
    let offset = 0;
    for (const match of text.matchAll(pattern)) {
      const href = match[2];
      let safe = !/[\\\u0000-\u0020]/.test(href);
      if (href.startsWith('/')) safe &&= !href.startsWith('//');
      else {
        try {
          const url = new URL(href);
          safe &&= ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password;
        } catch (_) {safe = false;}
      }
      if (!safe) continue;
      if (match.index > offset) parts.push({text: text.slice(offset, match.index)});
      parts.push({label: match[1], href}); offset = match.index + match[0].length;
    }
    if (offset < text.length) parts.push({text: text.slice(offset)});
    return parts;
  }
  root.CotaChat = {Controller, captureInvite, acceptInvite, messageParts};
  if (typeof document === 'undefined') return;

  const $ = id => document.getElementById(id);
  const make = (tag, text, className) => {
    const node = document.createElement(tag); if (text !== undefined) node.textContent = text;
    if (className) node.className = className; return node;
  };
  const button = (text, action, className = 'subtle') => {
    const node = make('button', text, className); node.type = 'button'; node.onclick = action; return node;
  };
  let invite = captureInvite(location, history, sessionStorage), inviteBusy = false;
  let quote = null, displayedRoom = null, displayedIdentity = null, memberNames = new Map();
  let selectedFiles = [], uploading = false;
  const app = new Controller({fetch: (...args) => fetch(...args), Client: CotaClient, storage: localStorage, changed: render});
  const statuses = {recorded: '已记录', limited: '已达到处理限制', queued: '排队中', running: '处理中', completed: '已完成', succeeded: '已完成', failed: '处理失败', interrupted: '处理已中断'};
  function author(message) {
    if (message.role !== 'user') return app.config.bot_name || 'Bot';
    if (message.sender_id === app.identity?.user_id || (!message.sender_id && app.room?.mode === 'direct')) return '你';
    return memberNames.get(message.sender_id) || message.sender_name || '群成员';
  }
  function render() {
    memberNames = new Map((app.room?.members || []).map(member => [member.user_id, member.name]));
    $('login').hidden = !!app.identity; $('workspace').hidden = !app.identity;
    $('notice').textContent = app.notice;
    $('invite-retry').hidden = !app.identity || !invite;
    $('invite-retry').disabled = inviteBusy;
    $('brand-name').textContent = app.config.bot_name || 'Cota';
    document.title = (app.config.bot_name || 'Cota') + ' · 聊天';
    $('identity-name').textContent = app.identity?.name || '';
    if (displayedIdentity !== app.identity?.user_id) {
      displayedIdentity = app.identity?.user_id;
      $('nickname').value = ''; $('draft').value = ''; $('invite-link').value = '';
      for (const dialog of document.querySelectorAll('dialog[open]')) dialog.close();
    }
    const current = app.room?.session_id || null;
    if (displayedRoom !== current) {
      displayedRoom = current; quote = null; $('draft').value = ''; $('mention').checked = false; $('invite-panel').hidden = true;
      selectedFiles = []; $('file-input').value = '';
    }
    $('conversation-list').replaceChildren();
    for (const room of app.conversations) {
      const row = button(room.title || '未命名会话', () => run(() => app.open(room.session_id)), 'conversation' + (room.session_id === current ? ' active' : ''));
      row.setAttribute('aria-current', room.session_id === current ? 'true' : 'false');
      row.append(make('span', room.mode === 'group' ? '群聊' : '私聊', 'room-kind'));
      if (room.unread) row.append(make('span', String(room.unread) + ' 未读', 'room-kind'));
      if (room.last_message) row.append(make('small', (room.last_message.text ||
        (room.last_message.attachments || []).map(file => file.name).join('、')).slice(0, 80), 'room-preview'));
      if (room.last_active) row.append(make('small', new Date(room.last_active * 1000).toLocaleString('zh-CN'), 'room-preview'));
      $('conversation-list').append(row);
    }
    $('empty-list').hidden = app.conversations.length > 0;
    $('load-more').hidden = !app.hasMore;
    $('room-title').textContent = app.room?.title || '开始一段对话'; $('connection').textContent = app.status;
    $('empty-room').hidden = !!app.room; $('composer').hidden = !app.room;
    $('room-actions').hidden = !app.room || app.room.mode !== 'group';
    const owner = app.room?.owner_id === app.identity?.user_id;
    $('share').hidden = !owner; $('leave').hidden = owner;
    $('join-open').hidden = app.config.mode !== 'group';
    $('mention-wrap').hidden = app.room?.mode !== 'group';
    $('mode-help').textContent = app.room?.mode === 'group'
      ? (app.config.response === 'proactive' ? 'Bot 可主动参与；勾选 @Bot 可明确邀请回复。引用本身不会触发回复。' : '勾选 @Bot 才会邀请 Bot 回复；引用本身不会触发回复。')
      : 'Enter 发送，Shift + Enter 换行';
    $('mention-label').textContent = '@' + (app.config.bot_name || 'Bot');
    $('quote').hidden = !quote;
    $('quote-text').textContent = quote ? '回复 ' + author(quote) + '：' + quote.text : '';
    $('older-messages').hidden = !app.room || app.client?.hasMore === false;
    renderMessages(); renderMembers();
    $('selected-files').replaceChildren();
    for (const file of selectedFiles) {
      const row = make('span', file.name + ' ', 'selected-file');
      row.append(button('移除', () => {selectedFiles = selectedFiles.filter(f => f.id !== file.id); render();}));
      $('selected-files').append(row);
    }
  }
  function renderMessages() {
    const list = $('messages'); const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 90;
    const previousTop = list.scrollTop; list.replaceChildren();
    const messagesById = new Map(app.messages.map(message => [message.event_id, message]));
    const submittedIds = new Set(app.messages.map(message => message.message_id));
    for (const message of app.messages) {
      const mine = message.role === 'user' && (message.sender_id === app.identity?.user_id || app.room?.mode === 'direct');
      const row = make('article', undefined, 'message' + (mine ? ' mine' : ''));
      row.append(make('div', author(message), 'author'));
      if (message.reply_to) {
        const original = messagesById.get(message.reply_to);
        row.append(make('blockquote', original ? author(original) + '：' + original.text : '引用的消息'));
      }
      const body = make('div', undefined, 'message-text');
      for (const part of messageParts(message.text)) {
        if (!part.href) body.append(document.createTextNode(part.text));
        else {
          const link = make('a', part.label); link.setAttribute('href', part.href);
          link.target = '_blank'; link.rel = 'noopener noreferrer'; link.referrerPolicy = 'no-referrer';
          body.append(link);
        }
      }
      row.append(body);
      for (const file of message.attachments || []) {
        const item = button(file.name + ' · ' + Math.ceil(file.size / 1024) + ' KiB ↓', () => run(async () => {
          const client = app.client;
          if (!client) throw new Error('请先打开会话');
          const downloaded = await client.download(file);
          if (client !== app.client) return;
          const url = URL.createObjectURL(downloaded.blob);
          const anchor = make('a'); anchor.href = url; anchor.download = downloaded.name;
          document.body.append(anchor); anchor.click(); anchor.remove();
          setTimeout(() => URL.revokeObjectURL(url), 1000);
        }), 'attachment');
        row.append(item);
      }
      if (message.mentioned) row.append(make('span', '@' + (app.config.bot_name || 'Bot'), 'mention-tag'));
      row.append(button('回复', () => {quote = message; render(); $('draft').focus();}, 'reply-button'));
      const receipt = app.receipts[message.message_id];
      if (receipt) row.append(make('small', statuses[receipt.status] || receipt.status, 'message-status'));
      list.append(row);
    }
    for (const preview of app.previews) {
      const row = make('article', undefined, 'message pending stream-preview');
      row.setAttribute('aria-label', '回复预览');
      row.append(make('div', app.config.bot_name || 'Bot', 'author'),
        make('div', preview.text || '', 'message-text'),
        make('small', preview.phase === 'end' ? '正在保存…' : '正在回复…', 'message-status'));
      list.append(row);
    }
    for (const [id, pending] of Object.entries(app.pending)) {
      if (submittedIds.has(id)) continue;
      const row = make('article', undefined, 'message mine pending');
      row.append(make('div', '你', 'author'), make('div', typeof pending === 'string' ? pending :
        (pending.text || (pending.attachments?.length ? `附件消息（${pending.attachments.length}个文件）` : '')), 'message-text'));
      row.append(make('small', statuses[app.receipts[id]?.status] || '待确认 · 重连后继续提交', 'message-status')); list.append(row);
    }
    list.scrollTop = nearBottom ? list.scrollHeight : previousTop;
  }
  function renderMembers() {
    const list = $('member-list'); list.replaceChildren();
    for (const member of app.room?.members || []) {
      const row = make('li'); row.append(make('span', member.name + (member.user_id === app.room.owner_id ? ' · 创建者' : '')));
      if (app.room.owner_id === app.identity?.user_id && member.user_id !== app.identity.user_id) {
        row.append(button('移除', () => {if (confirm('将 ' + member.name + ' 移出此会话？')) run(() => app.remove(member.user_id));}));
      }
      list.append(row);
    }
  }
  async function run(action) {
    const identityEpoch = app.identityEpoch, epoch = app.epoch;
    try {await action();} catch (error) {
      if (identityEpoch === app.identityEpoch && epoch === app.epoch) {app.notice = error.message || '操作失败，请稍后再试'; render();}
    }
  }
  async function useInvite() {
    if (!invite || !app.identity || inviteBusy) return;
    const captured = invite; inviteBusy = true; render();
    try {
      if (await acceptInvite(app, captured, sessionStorage) && invite === captured) invite = '';
    } finally {inviteBusy = false; render();}
  }
  $('invite-retry').onclick = () => run(useInvite);
  $('login-form').onsubmit = event => {
    event.preventDefault(); const submit = $('login-submit'); submit.disabled = true;
    run(async () => {await app.login($('nickname').value); await run(useInvite);}).finally(() => {submit.disabled = false;});
  };
  $('signout').onclick = () => {
    if (confirm('退出后，此访客身份无法找回。确定退出并清除此浏览器的聊天缓存？')) {
      invite = ''; sessionStorage.removeItem(INVITE_KEY); app.signout('已退出。可使用新昵称创建新的访客身份。');
    }
  };
  $('new-chat').onclick = () => {$('create-dialog').showModal(); $('chat-title').focus();};
  $('create-form').onsubmit = event => {event.preventDefault(); const title = $('chat-title').value; $('create-dialog').close(); run(() => app.create(title));};
  $('join-open').onclick = () => {$('join-dialog').showModal(); $('join-value').focus();};
  $('join-form').onsubmit = event => {
    event.preventDefault(); let token = $('join-value').value.trim();
    if (token.includes('#')) {try {token = new URL(token).hash; token = new URLSearchParams(token.slice(1)).get('invite') || '';} catch (_) {token = '';}}
    if (!token) {$('join-value').setCustomValidity('请输入有效的邀请链接'); $('join-value').reportValidity(); return;}
    $('join-dialog').close(); $('join-value').value = ''; run(() => app.join(token));
  };
  $('join-value').oninput = () => $('join-value').setCustomValidity('');
  for (const node of document.querySelectorAll('[data-close]')) node.onclick = () => $(node.dataset.close).close();
  $('older-messages').onclick = () => run(() => app.older());
  $('load-more').onclick = () => run(() => app.list(true));
  $('refresh-list').onclick = () => run(() => app.list());
  $('share').onclick = () => run(async () => {
    const result = await app.invite(); if (!result) return;
    const link = new URL('/chat/', location.href); link.hash = new URLSearchParams({invite: result.invite}).toString();
    $('invite-link').value = link.href; $('invite-panel').hidden = false;
    const expiry = typeof result.expires_at === 'number' ? result.expires_at * 1000 : result.expires_at;
    $('invite-help').textContent = '持有链接的人可加入此群。有效期至 ' + new Date(expiry).toLocaleString('zh-CN');
  });
  $('copy-invite').onclick = () => run(async () => {
    try {await navigator.clipboard.writeText($('invite-link').value); app.notice = '邀请链接已复制';}
    catch (_) {$('invite-link').select(); app.notice = '请手动复制已选中的邀请链接';}
    $('notice').textContent = app.notice;
  });
  $('members').onclick = () => { $('members-dialog').showModal(); run(() => app.refreshMembers());};
  $('leave').onclick = () => {if (confirm('确定退出此群聊？再次加入需要邀请链接。')) run(() => app.leave());};
  $('cancel-quote').onclick = () => {quote = null; render();};
  $('composer').onsubmit = event => {
    event.preventDefault(); const text = $('draft').value; if (uploading || !text.trim() && !selectedFiles.length) return;
    const epoch = app.epoch; const options = {mentioned: app.room?.mode === 'group' && $('mention').checked};
    if (quote) options.reply_to = quote.event_id;
    if (selectedFiles.length) options.attachments = selectedFiles.map(file => file.id);
    $('send').disabled = true;
    run(async () => {
      await app.send(text, options);
      if (epoch === app.epoch && $('draft').value === text) {$('draft').value = ''; quote = null; selectedFiles = []; render();}
    }).finally(() => {$('send').disabled = false;});
  };
  $('file-input').onchange = () => run(async () => {
    const files = [...$('file-input').files], client = app.client, epoch = app.epoch;
    if (!client || uploading) return;
    if (files.length + selectedFiles.length > 8) throw new Error('每条消息最多8个附件');
    if (files.some(file => file.size < 1 || file.size > 20 * 1024 * 1024)) throw new Error('每个文件须为1字节至20 MiB');
    uploading = true; $('send').disabled = true; $('file-input').disabled = true;
    try {
      for (const file of files) {
        const uploaded = await client.upload(file);
        if (epoch !== app.epoch || client !== app.client) return;
        selectedFiles.push(uploaded); render();
      }
    } finally {
      uploading = false; $('send').disabled = false; $('file-input').disabled = false; $('file-input').value = '';
    }
  });
  $('draft').onkeydown = event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {event.preventDefault(); if (!$('send').disabled) $('composer').requestSubmit();}
  };
  addEventListener('hashchange', () => {invite = captureInvite(location, history, sessionStorage); run(useInvite);});
  addEventListener('storage', event => {
    if (event.key === IDENTITY_KEY && event.newValue !== JSON.stringify(app.identity)) app.signout('访客身份已在其他标签页更改，请刷新页面后继续。', false);
  });
  document.addEventListener('visibilitychange', () => {if (!document.hidden) run(() => app.markRead());});
  let refreshing = false;
  setInterval(async () => {
    if (!app.identity || document.hidden || refreshing) return;
    refreshing = true;
    try {await app.list(); await app.markRead();} catch (_) {} finally {refreshing = false;}
  }, 15000);
  addEventListener('beforeunload', () => app.client?.close());
  render(); run(async () => {await app.start(); await useInvite();});
})(globalThis);
