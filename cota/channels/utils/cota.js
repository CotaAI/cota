/** Cota WebSocket client: durable identity, submission IDs and replay cursor. */
class CotaClient {
  constructor(options = {}) {
    this.base = options.base || '';
    this.external = options.token !== undefined || options.sessionId !== undefined;
    if (this.external && (!options.token || !options.sessionId))
      throw new Error('External chat requires token and sessionId from your application');
    this.storageKey = options.storageKey || 'cota.chat.v1:' + this.base +
      (this.external ? ':' + options.sessionId : '');
    this.handlers = {};
    this.stopped = false;
    this.attempt = 0;
    this.connected = false;
    this.retries = {};
    try {this.storage = options.storage || localStorage;}
    catch (_) {this.storage = {getItem() {throw new Error('storage blocked');}};}
    this.maxCachedMessages = Math.max(1, Math.min(500, options.maxCachedMessages || 200));
    this.maxPending = 100;
    this.recent = options.recent !== false;
    this.cacheBlocked = false;
    const empty = () => ({token: null, session_id: null, cursor: 0, messages: [], pending: {}});
    this.state = empty();
    try {
      const raw = this.storage.getItem(this.storageKey);
      if (raw) {
        const saved = JSON.parse(raw);
        if (!saved || !Array.isArray(saved.messages) || !saved.pending || typeof saved.pending !== 'object' ||
            Array.isArray(saved.pending) || !Number.isSafeInteger(saved.cursor) || saved.cursor < 0 ||
            saved.messages.some(m => !m || typeof m.event_id !== 'string' || !Number.isSafeInteger(m.sequence)) ||
            Object.values(saved.pending).some(p => typeof p !== 'string' && (!p || typeof p.text !== 'string')))
          throw new Error('invalid cache');
        this.state = saved;
        this.state.messages = this.state.messages.slice(-1000);
      }
    } catch (_) {
      // Preserve the original bytes: corrupt pending inputs require explicit recovery.
      this.cacheBlocked = true;
      this.cacheError = {code: 'cache_corrupt', message: 'Browser storage cannot be read. Existing unsent data has been preserved; recover or clear this cache before sending.'};
    }
    if (this.external && (this.state.token !== options.token || this.state.session_id !== options.sessionId)) {
      if (Object.keys(this.state.pending).length) {
        this.cacheBlocked = true;
        this.cacheError = {code: 'cache_identity_changed', message: 'Browser storage contains unsent messages for another identity. Recover them before sending.'};
      }
      this.state = {...empty(), token: options.token, session_id: options.sessionId};
    }
    this.ready = this.start().catch(error => this.emit('error', {message: error.message, code: error.code}));
  }
  on(name, fn) { (this.handlers[name] ||= []).push(fn); return this; }
  emit(name, data) { for (const fn of this.handlers[name] || []) fn(data); }
  save() {
    if (this.cacheBlocked) return false;
    try {
      this.storage.setItem(this.storageKey, JSON.stringify({...this.state,
        messages: this.state.messages.slice(-this.maxCachedMessages)}));
      this.storageFailed = false;
      return true;
    } catch (_) {
      this.storageFailed = true;
      this.emit('error', {code: 'storage_unavailable', message: 'Browser storage is full or unavailable. Unsent messages remain in this tab; keep it open and retry.'});
      return false;
    }
  }
  async api(path, data) {
    const res = await fetch(this.base + '/api/' + path, {
      method: data === undefined ? 'GET' : 'POST',
      headers: {'Content-Type': 'application/json', ...(this.state.token ? {Authorization: 'Bearer ' + this.state.token} : {})},
      ...(data === undefined ? {} : {body: JSON.stringify(data)})
    });
    const value = await res.json();
    if (!res.ok) {
      const error = new Error(value.message || value.error || 'Request failed');
      error.code = value.error;
      throw error;
    }
    return value;
  }
  async start() {
    await Promise.resolve();
    if (this.cacheError) this.emit('error', this.cacheError);
    for (const message of this.state.messages) this.emit('message', message);
    if (!this.state.token) {
      const identity = await this.api('guests', {});
      this.state.token = identity.token;
      this.save();
    }
    if (!this.state.session_id) {
      this.state.session_id = (await this.api('conversations', {})).session_id;
      this.save();
    }
    this.connect();
  }
  connect() {
    if (this.stopped) return;
    const url = new URL(this.base + '/ws', location.href);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = this.socket = new WebSocket(url);
    socket.onopen = () => {
      if (this.stopped || this.socket !== socket) return;
      socket.send(JSON.stringify({type: 'resume', token: this.state.token,
        session_id: this.state.session_id, after_sequence: this.state.cursor, recent: this.recent && this.state.cursor === 0}));
    };
    socket.onmessage = event => {
      if (this.stopped || this.socket !== socket) return;
      const data = JSON.parse(event.data);
      if (data.type === 'ready') {
        this.hasMore = data.has_more ?? this.hasMore;
        this.state.cursor = Math.max(this.state.cursor, data.cursor);
        this.attempt = 0;
        this.connected = true;
        this.save();
        for (const message_id of Object.keys(this.state.pending)) this.sendPending(message_id, socket);
        this.emit('connected', data);
      } else if (data.type === 'message') {
        if (!this.state.messages.some(message => message.event_id === data.event_id)) {
          this.state.messages.push(data);
          this.state.messages.sort((a, b) => a.sequence - b.sequence);
          if (this.state.messages.length > 1000) {this.state.messages.shift(); this.hasMore = true;}
          this.emit('message', data);
        }
        this.state.cursor = Math.max(this.state.cursor, data.sequence);
        this.save();
      } else if (data.type === 'receipt') {
        // Keep accepted submissions until terminal: reconnect queries their
        // durable receipt by safely resubmitting the same message ID.
        if (!['queued', 'running'].includes(data.status)) {
          delete this.state.pending[data.message_id];
          clearTimeout(this.retries[data.message_id]);
          delete this.retries[data.message_id];
        }
        this.save();
        this.emit('receipt', data);
      } else if (data.type === 'error') {
        if (data.code === 'unauthorized') this.close();
        if (data.code === 'busy' && this.state.pending[data.message_id] !== undefined) {
          clearTimeout(this.retries[data.message_id]);
          this.retries[data.message_id] = setTimeout(() => {
            if (this.connected && this.state.pending[data.message_id] !== undefined)
              this.sendPending(data.message_id);
          }, 2000);
        }
        // Errors do not acknowledge acceptance. Keep the input until an explicit
        // terminal receipt or the caller's decision; retries retain its ID.
        this.emit('error', data);
      }
    };
    socket.onclose = () => {
      if (this.socket !== socket) return;
      this.connected = false;
      this.emit('disconnected', {});
      if (!this.stopped) this.timer = setTimeout(() => this.connect(), Math.min(1000 * 2 ** this.attempt++, 10000));
    };
    socket.onerror = () => {if (!this.stopped && this.socket === socket) this.emit('error', {message: '连接暂不可用，正在重连'});};
  }
  sendPending(message_id, socket = this.socket) {
    const pending = this.state.pending[message_id];
    if (pending === undefined) return;
    // Existing guest sessions may still have string-valued pending messages.
    const data = typeof pending === 'string' ? {text: pending} : pending;
    const frame = {type: 'send', message_id, text: data.text};
    for (const key of ['mentioned', 'reply_to', 'attachments'])
      if (Object.hasOwn(data, key)) frame[key] = data[key];
    socket.send(JSON.stringify(frame));
  }
  async chat(text, message_id = crypto.randomUUID(), options = {}) {
    await this.ready;
    if (options === null || typeof options !== 'object' || Array.isArray(options))
      throw new TypeError('chat options must be an object');
    const pending = {text};
    if (Object.hasOwn(options, 'attachments')) {
      if (!Array.isArray(options.attachments) || options.attachments.length > 8 ||
          options.attachments.some(id => typeof id !== 'string' || !/^f_[0-9a-f]{32}$/.test(id)) ||
          new Set(options.attachments).size !== options.attachments.length)
        throw new TypeError('attachments must contain at most eight unique file IDs');
      pending.attachments = [...options.attachments];
    }
    if (Object.hasOwn(options, 'mentioned')) {
      if (typeof options.mentioned !== 'boolean') throw new TypeError('mentioned must be boolean');
      pending.mentioned = options.mentioned;
    }
    if (Object.hasOwn(options, 'reply_to')) {
      if (typeof options.reply_to !== 'string' || !options.reply_to.trim() || options.reply_to.length > 255)
        throw new TypeError('reply_to must contain 1–255 characters');
      pending.reply_to = options.reply_to;
    }
    if (typeof text !== 'string' || !text.trim() && !pending.attachments?.length) return;
    if (text.length > 32768) throw new Error('Message exceeds 32768 characters');
    if (!Object.hasOwn(this.state.pending, message_id) && Object.keys(this.state.pending).length >= this.maxPending)
      throw new Error('Too many unsent messages; wait for delivery before sending more');
    Object.defineProperty(this.state.pending, message_id, {value: Object.keys(pending).length === 1 ? text : pending,
      writable: true, configurable: true, enumerable: true});
    if (!this.save()) throw new Error('Browser storage unavailable; your unsent message remains in this tab. Keep this tab open and retry.');
    if (this.connected) this.sendPending(message_id);
    return message_id;
  }
  async upload(file) {
    await this.ready;
    if (!file || typeof file.name !== 'string' || !Number.isSafeInteger(file.size) || file.size < 1 || file.size > 20 * 1024 * 1024)
      throw new Error('附件必须为 1 字节至 20 MiB 的文件');
    const response = await fetch(this.base + '/api/conversations/' + encodeURIComponent(this.state.session_id) + '/files', {
      method:'POST', headers:{Authorization:'Bearer ' + this.state.token, 'Content-Type':'application/octet-stream',
                            'X-File-Name':encodeURIComponent(file.name)}, body:file});
    const value = await response.json();
    if (this.stopped) throw new Error('会话已切换，请重新选择附件');
    if (!response.ok) throw new Error(value.message || '附件上传失败');
    return value;
  }
  async download(file) {
    await this.ready;
    if (!file || !/^f_[0-9a-f]{32}$/.test(file.id)) throw new Error('无效附件');
    const response = await fetch(this.base + '/api/conversations/' + encodeURIComponent(this.state.session_id) + '/files/' + file.id,
                                 {headers:{Authorization:'Bearer ' + this.state.token}});
    if (!response.ok) throw new Error('附件不可用或已无访问权限');
    const blob = await response.blob();
    if (this.stopped) throw new Error('会话已切换，下载已取消');
    return {blob, name:file.name};
  }
  async loadOlder(limit = 50) {
    await this.ready;
    if (this.state.messages.length >= 1000) throw new Error('History view limit reached; reopen the conversation to view recent messages');
    const before = this.state.messages[0]?.sequence;
    const page = await this.api('conversations/' + encodeURIComponent(this.state.session_id) +
      '/messages?recent=1&limit=' + Math.min(100, limit) + (before ? '&before_sequence=' + before : ''));
    if (this.stopped) return page;
    const messages = new Map(this.state.messages.map(m => [m.event_id, m]));
    for (const message of page.messages) messages.set(message.event_id, message);
    this.state.messages = [...messages.values()].sort((a, b) => a.sequence - b.sequence).slice(-1000);
    this.hasMore = page.has_more;
    this.save();
    this.emit('history', page);
    return page;
  }
  close() {
    this.stopped = true;
    this.connected = false;
    clearTimeout(this.timer);
    for (const timer of Object.values(this.retries)) clearTimeout(timer);
    this.socket?.close();
  }
}
