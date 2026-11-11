/* Read-only projections. Full facts are fetched only when a detail is opened. */
export function hasModelDiagnostics(event) {
  const p = event.payload;
  if (!['bot_utter', 'tool_started'].includes(event.type)) return false;
  return !!(p.llm?.request_id || p.llm_event_id || (event.type === 'bot_utter' && p.tool_event_id));
}

export function debugRequestURL(path, base, sessionId = null) {
  const url = new URL('api/' + path, base);
  if (sessionId && !url.pathname.endsWith('/sessions')) url.searchParams.set('session_id', sessionId);
  return url;
}

export function modelRequestSummary(record, now = Date.now() / 1000) {
  const seconds = record.status === 'running' ? Math.max(0, now - record.started_at) : record.duration_ms / 1000;
  const duration = Number.isFinite(seconds) ? `${seconds.toFixed(1)}s` : '';
  const usage = record.usage;
  return [record.purpose || 'model', record.status === 'running' ? 'waiting for model' : record.status, duration,
    record.transport?.attempts?.length && `HTTP attempt ${record.transport.attempts.length}`,
    usage && `input ${usage.prompt_tokens ?? '?'} · cache ${usage.cached_tokens ?? '?'} · output ${usage.completion_tokens ?? '?'} · reasoning ${usage.reasoning_tokens ?? '?'}`,
  ].filter(Boolean).join(' · ');
}

function boot() {
  const $ = id => document.getElementById(id);
  const headers = [], byID = new Map();
  let cursor = 0, selectedSequence = null, activeTab = 'events', metadataRun = null;
  let visibleCount = 100, busy = false, pending = null, paused = false, timer;
  let copyValue = null, stateSource = 'stored', detailVersion = 0;
  let selectedSession = null, multiSession = false, sessionsLoaded = false, sessionCursor = null;
  let sessionVersion = 0, selectedRequest = null, requestRecord = null, requestStatusNode = null;
  const typeClasses = {user_utter:'type-user', bot_utter:'type-bot', run_started:'type-run',
    run_finished:'type-run', tool_started:'type-tool', tool_result:'type-tool',
    user_context_updated:'type-meta', context_compaction:'type-meta'};
  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const button = (text, action, className) => {
    const node = element('button', text, className);
    node.addEventListener('click', action); return node;
  };
  const notice = text => element('p', text, 'notice');
  const error = message => {
    $('error').textContent = message; $('error').hidden = !message;
    if (message) { $('connection').textContent = '连接 / 查询异常'; $('connection-dot').classList.add('off'); }
  };
  async function api(path) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(debugRequestURL(path, location.href, selectedSession), {signal:controller.signal, cache:'no-store', credentials:'same-origin'});
      const data = await response.json();
      if (!response.ok) {
        const failure = new Error(data.error || `HTTP ${response.status}`);
        failure.code = data.code;
        throw failure;
      }
      return data;
    } finally { clearTimeout(timeout); }
  }
  async function exclusive(job, interactive = true) {
    if (busy) { if (interactive) pending = job; return; }
    busy = true;
    try { await job(); error(''); }
    catch (err) { error(`${err.message}。Bot 执行不受影响；可重试或检查服务是否仍在运行。`); }
    finally {
      busy = false;
      if (pending) { const next = pending; pending = null; exclusive(next); }
    }
  }
  function section(title, value, open = false, messages = false) {
    const details = element('details');
    details.append(element('summary', title));
    let rendered = false;
    const render = () => {
      if (rendered || !details.open) return;
      rendered = true;
      if (messages && Array.isArray(value)) {
        for (const [index, message] of value.entries()) {
          if (!message || typeof message !== 'object') { details.append(element('pre', JSON.stringify(message))); continue; }
          details.append(element('div', `${index + 1} · ${message.role || 'message'}`, 'message-role'));
          details.append(element('pre', typeof message.content === 'string' ? message.content : JSON.stringify(message.content ?? message, null, 2)));
          const extras = Object.fromEntries(Object.entries(message).filter(([key]) => !['content','role'].includes(key)));
          if (Object.keys(extras).length) details.append(element('pre', JSON.stringify(extras, null, 2)));
        }
      } else details.append(element('pre', typeof value === 'string' ? value : JSON.stringify(value, null, 2)));
    };
    details.addEventListener('toggle', render);
    details.open = open;
    render(); return details;
  }
  // A single JSON tree: no extracted payload cards, no altered/copied data.
  function jsonView(value) {
    const view = element('div', undefined, 'json-view');
    const controls = element('div', undefined, 'json-controls');
    const tree = element('div', undefined, 'json-tree');
    const literal = value => element('span', JSON.stringify(value),
      'json-' + (value === null ? 'null' : typeof value));
    function prefix(parent, key) {
      if (key === null) return;
      parent.append(element('span', JSON.stringify(key), 'json-key'), document.createTextNode(': '));
    }
    function node(value, key, path, comma) {
      const container = value !== null && typeof value === 'object';
      if (!container) {
        const row = element('div', undefined, 'json-line');
        prefix(row, key);
        if (typeof value === 'string' && (value.length > 180 || value.includes('\n'))) {
          const text = element('details', undefined, 'json-text');
          const summary = element('summary');
          const preview = value.length > 120 ? value.slice(0, 120) : value;
          summary.append(literal(preview), element('span',
            ` ${value.length > 120 ? '… · ' : ''}${value.length} 字符 · 点击展开`, 'json-hint'));
          text.append(summary);
          let rendered = false;
          text.addEventListener('toggle', () => {
            if (!text.open || rendered) return;
            rendered = true;
            text.append(element('div', '字符串原文 · 按原换行显示；复制 JSON 时保留转义', 'json-hint'),
              element('pre', value, 'json-string-body'));
          });
          row.append(text);
        } else row.append(literal(value));
        if (comma) row.append(document.createTextNode(','));
        return row;
      }
      const array = Array.isArray(value), entries = Object.entries(value);
      const open = array ? '[' : '{', close = array ? ']' : '}';
      if (!entries.length) {
        const row = element('div', undefined, 'json-line');
        prefix(row, key); row.append(document.createTextNode(open + close + (comma ? ',' : '')));
        return row;
      }
      const group = element('details', undefined, 'json-node');
      const summary = element('summary');
      prefix(summary, key); summary.append(document.createTextNode(open));
      const preview = element('span', ` … ${close}${comma ? ',' : ''}`, 'json-collapsed');
      summary.append(preview);
      const role = !array && typeof value.role === 'string' ? ` · role: ${JSON.stringify(value.role)}` : '';
      summary.append(element('span', ` ${entries.length} ${array ? 'items' : 'fields'}${role}`, 'json-hint'));
      group.append(summary);
      const children = element('div', undefined, 'json-children');
      let position = 0;
      function more() {
        const end = Math.min(position + 50, entries.length);
        for (; position < end; position++) {
          const [childKey, child] = entries[position];
          children.append(node(child, array ? null : childKey, [...path, childKey], position < entries.length - 1));
        }
        if (position < entries.length) {
          const next = button(`展开后续 ${Math.min(50, entries.length - position)} 项（剩余 ${entries.length - position}）`,
            () => { next.remove(); more(); }, 'json-more');
          children.append(next);
        }
      }
      let rendered = false;
      const reveal = () => {
        if (!group.open || rendered) return;
        rendered = true; more(); group.append(children, element('div', close + (comma ? ',' : ''), 'json-close'));
      };
      group.addEventListener('toggle', reveal);
      group.open = !path.length || (!array && path.length <= 2) || path.at(-1) === 'messages';
      reveal(); return group;
    }
    function reset() { tree.replaceChildren(node(value, null, [], false)); }
    controls.append(element('span', 'JSON · 点击括号折叠，点击长字符串阅读原文', 'json-hint'),
      button('折叠嵌套内容', () => {
        for (const item of tree.querySelectorAll('details')) item.open = false;
        const root = tree.querySelector('details'); if (root) root.open = true;
      }), button('重置展开', reset));
    reset(); view.append(controls, tree); return view;
  }
  function setDetail(title, value) {
    $('detail-title').textContent = title;
    $('detail-body').replaceChildren(); $('detail-body').scrollTop = 0;
    copyValue = value; $('copy').hidden = value === null;
  }
  function eventLinks(event) {
    const ids = new Set();
    for (const [key, value] of Object.entries(event.payload)) {
      if (key.endsWith('_event_id')) {
        if (typeof value === 'string') ids.add(value);
      } else if (key.endsWith('_event_ids') && Array.isArray(value)) value.forEach(id => ids.add(id));
    }
    const p = event.payload;
    for (const h of headers) {
      if (h.run_id !== event.run_id) continue;
      if ((p.tool_call_id && h.summary.tool_call_id === p.tool_call_id) ||
          (p.request_id && h.summary.request_id === p.request_id)) ids.add(h.event_id);
    }
    ids.delete(event.event_id);
    if (!ids.size) return;
    $('detail-body').append(element('div', '关联记录 · 点击展开', 'detail-label'));
    const links = element('div', undefined, 'links');
    for (const id of ids) {
      const header = byID.get(id);
      if (header) links.append(button(`#${header.sequence} ${header.type}`, () => selectEvent(header.sequence)));
      else links.append(element('span', `尚未加载 ${id}`, 'notice'));
    }
    $('detail-body').append(links);
  }
  async function showEvent(sequence, version) {
    const event = await api('event/' + sequence);
    if (version !== detailVersion) return;
    setDetail(`#${event.sequence} · ${event.type}`, event);
    const body = $('detail-body');
    body.append(element('div', event.debug
      ? '来源：Store 已提交事件；debug 为关联诊断的只读展示，不写入事件或参与 DST 恢复。'
      : '来源：Store 已提交事件', 'meta'));
    eventLinks(event);
    if (hasModelDiagnostics(event) && !event.debug) body.append(notice(
      '没有模型请求详情。该次调用可能未开启 Debug，或关联记录尚未保存。'));
    body.append(jsonView(event));
  }

  function selectModelDebug(requestId = null) {
    selectedRequest = requestId;
    const version = ++detailVersion;
    exclusive(async () => {
      const detail = requestId !== null;
      const query = detail ? '?request_id=' + encodeURIComponent(requestId) : '';
      let data;
      try { data = await api('model-debug' + query); }
      catch (err) {
        if (version !== detailVersion) return;
        if (err.code !== 'model_diagnostics_unavailable') throw err;
        setDetail('Model request · Debug', null);
        $('detail-body').append(notice(err.message), button('返回请求列表', () => selectModelDebug()));
        return;
      }
      if (version !== detailVersion) return;
      setDetail(detail ? 'Model request · Debug' : 'Model requests · Debug', detail ? data : null);
      const body = $('detail-body');
      body.append(element('div', 'Store 独立诊断记录 · 仅 Debug 采集，不属于 Events，不参与 DST 恢复。', 'source-note'));
      if (detail) {
        requestRecord = data;
        requestStatusNode = element('div', modelRequestSummary(data), 'meta');
        body.append(button('返回请求列表', () => selectModelDebug()),
          button('刷新请求', () => selectModelDebug(requestId)),
          requestStatusNode);
        if (data.request_size) body.append(section('Request size · characters / image bytes', data.request_size, true));
        if (data.transport) body.append(section('Transport · attempts / header and response timing', data.transport, true));
        const budget = data.preparation?.context_budget;
        if (budget) body.append(section('Context budget · Pi estimates, not provider usage', budget, true));
        body.append(jsonView(data));
      } else {
        body.append(button('刷新请求', () => selectModelDebug()), element('div', '最近 100 次模型调用（包括尚未结束的请求）', 'meta'));
        for (const row of data.records) body.append(button(
          `${modelRequestSummary(row)} · ${row.request_id}`, () => selectModelDebug(row.request_id), 'entry'));
        if (!data.records.length) body.append(notice('没有模型请求详情。非 Debug 模式不采集完整 prompt。'));
      }
    });
  }

  function selectRunMetadata() {
    const version = ++detailVersion;
    const runs = headers.filter(e => e.type === 'run_started').reverse();
    const run = metadataRun || runs[0]?.run_id;
    if (!run) {
      setDetail('Skills & Tools', null);
      $('detail-body').append(notice('等待首次运行加载 Skill 与工具清单。'), button('刷新目录', selectRunMetadata));
      return;
    }
    exclusive(async () => {
      const data = await api('run-metadata?run_id=' + encodeURIComponent(run));
      if (version !== detailVersion) return;
      setDetail('Skills & Tools', data);
      const controls = element('div', undefined, 'state-controls');
      const select = element('select'); select.setAttribute('aria-label', 'Skill 目录所属运行');
      for (const item of runs) {
        const option = element('option', `#${item.sequence} · ${item.run_id}`);
        option.value = item.run_id; select.append(option);
      }
      select.value = run;
      select.addEventListener('change', () => { metadataRun = select.value; selectRunMetadata(); });
      controls.append(select, button('刷新目录', selectRunMetadata));
      const body = $('detail-body');
      body.append(controls,
        element('div', '本轮开始时的 Skill 与工具清单。环境见下方 JSON；运行中权限变化后的实际工具，以 Model Requests 中对应请求为准。', 'source-note'));
      for (const tool of data.discovery?.tools || []) {
        body.append(element('div', `${tool.name} · ${tool.source} · ${tool.available ? 'Available' : tool.reason}`, 'meta'));
      }
      body.append(jsonView(data));
    });
  }

  function selectEvent(sequence) {
    if (activeTab !== 'events') { selectedSequence = sequence; selectTab('events'); return; }
    selectedSequence = sequence; const version = ++detailVersion;
    renderEvents();
    exclusive(() => showEvent(sequence, version));
  }
  function resetSession(id) {
    selectedRequest = null;
    requestRecord = null; requestStatusNode = null;
    selectedSession = id;
    ++sessionVersion;
    headers.length = 0; byID.clear(); cursor = 0; selectedSequence = null; metadataRun = null;
    visibleCount = 100; ++detailVersion; pending = null;
    renderEvents();
    setDetail('Session', null);
    $('detail-body').append(notice(id ? '已切换会话，请选择左侧视图。' : '暂无会话，发送消息后刷新会话列表。'));
  }
  async function loadSessions(after = null) {
    const data = await api('sessions?limit=100' + (after ? '&after=' + encodeURIComponent(after) : ''));
    sessionsLoaded = true; sessionCursor = data.cursor;
    const select = $('session-select'); select.replaceChildren();
    const rows = data.sessions;
    if (selectedSession && !rows.some(row => row.session_id === selectedSession)) {
      rows.unshift({session_id:selectedSession});
    }
    for (const row of rows) {
      const option = element('option', row.session_id);
      option.value = row.session_id; select.append(option);
    }
    if (!selectedSession && rows.length) resetSession(rows[0].session_id);
    select.value = selectedSession || ''; select.disabled = !rows.length;
    $('session-next').hidden = !data.has_more;
  }
  function showStateControls() {
    const controls = element('div', undefined, 'state-controls');
    const select = element('select'); select.setAttribute('aria-label', 'DST 数据来源');
    for (const [value, label] of Object.entries({stored:'Store 恢复状态', live:'当前进程内存状态', snapshot:'数据库物理快照'})) {
      const option = element('option', label); option.value = value; select.append(option);
    }
    select.value = stateSource;
    select.addEventListener('change', () => { stateSource = select.value; selectState(); });
    controls.append(select, button('刷新状态', selectState)); $('detail-body').append(controls);
  }
  function selectState() {
    const version = ++detailVersion, source = stateSource;
    exclusive(async () => {
      const data = await api('state?source=' + source);
      if (version !== detailVersion) return;
      setDetail('DST · 状态查看', data); showStateControls();
      const notes = {
        stored:'由 Store 中的快照及事件恢复。表示已提交、可恢复的状态，不代表进程中尚未保存的变化。',
        live:'当前或最近一次 Processor 的内存副本，可能包含未提交变化。revision 是最近一次成功保存的版本。',
        snapshot:'数据库中实际保存的缓存快照，可能落后于最新事件。本视图展示原始缓存，不将其视为已校验的最新 DST。',
      };
      $('detail-body').append(element('div', notes[source], 'source-note'));
      if (!data.available) { $('detail-body').append(notice('当前没有这个来源的状态。会话尚未保存、执行尚未开始或快照尚未生成时，这是正常情况。')); return; }
      $('detail-body').append(element('div', `事件位置 #${data.last_sequence ?? '未知'} · revision ${data.revision ?? '不适用'} · 手动刷新`, 'meta'));
      for (const [key, value] of Object.entries(data.state || {})) {
        if (key === 'context_messages') {
          $('detail-body').append(element('div', 'context_messages · 事件推导上下文', 'detail-label'), jsonView(value));
        } else $('detail-body').append(section(key, value, ['execution','active_skill'].includes(key)));
      }
      $('detail-body').append(section('完整数据 JSON', data));
    });
  }
  function renderEvents() {
    let events = headers;
    const search = $('search').value.toLowerCase().trim();
    if (search) events = events.filter(event => JSON.stringify(event).toLowerCase().includes(search));
    $('count').textContent = events.length > visibleCount ? `最近 ${visibleCount} / 共 ${events.length} 项` : `${events.length} 项`;
    $('run-info').textContent = '当前会话 · 按 sequence 展示全部事件';
    const container = $('events'); container.replaceChildren();
    const displayed = events.slice(-visibleCount);
    if (!displayed.length) container.append(notice(headers.length ? '当前筛选条件下没有事件。' : '等待当前会话的第一条消息……'));
    for (const event of displayed) {
      const s = event.summary;
      const failed = ['error', 'blocked', 'failed'].includes(s.status);
      const tCls = event.type === 'bot_utter' ? (s.tool && !s.text ? 'type-tool' : 'type-bot')
        : (typeClasses[event.type] || 'type-meta');
      const item = button('', () => selectEvent(event.sequence), 'entry' +
        (event.sequence === selectedSequence ? ' selected' : '') +
        (failed ? ' error' : '') + (['user_utter','bot_utter'].includes(event.type) ? ' message' : ''));
      const top = element('div', undefined, 'entry-top');
      top.append(element('span', '#' + event.sequence, 'entry-seq'),
        element('span', event.type, 'entry-label ' + tCls),
        element('span', s.status || (failed ? 'error' : ''), 'entry-status'));
      item.append(top);
      const sub = s.text || (s.tool
        ? s.tool + (s.skill && s.skill !== s.tool ? ' · ' + s.skill : '')
          + (s.resource_kind ? ' · ' + s.resource_kind + ': ' + (s.resource_skill || '') : '')
        : s.skill || s.purpose || s.error_type || '');
      if (sub) item.append(element('span', sub, 'entry-sub'));
      item.append(element('time', new Date(event.timestamp * 1000).toLocaleTimeString()));
      container.append(item);
    }
    $('more').hidden = events.length <= visibleCount;
  }
  async function poll() {
    clearTimeout(timer);
    let requestCompleted = false;
    if (!document.hidden && !paused && !busy) {
      await exclusive(async () => {
        let version = sessionVersion;
        let info = await api('info');
        if (version !== sessionVersion) return;
        multiSession = !!info.multi_session;
        $('session-controls').hidden = !multiSession;
        if (multiSession && !sessionsLoaded) {
          await loadSessions(); version = sessionVersion;
          info = await api('info');
          if (version !== sessionVersion) return;
        }
        const data = await api('events?after=' + cursor + '&limit=100');
        if (version !== sessionVersion) return;
        for (const header of data.events) { if (!byID.has(header.event_id)) { headers.push(header); byID.set(header.event_id, header); } }
        cursor = data.after_sequence;
        $('bot-name').textContent = info.bot; $('session').textContent = info.session_id || '暂无会话';
        $('cursor').textContent = `已读取至 #${cursor} / 已提交 #${info.metadata?.last_sequence || 0}`;
        $('connection').textContent = paused ? '已暂停 · 可继续查详情' : '已连接 · 增量刷新'; $('connection-dot').classList.toggle('off', paused);
        if (data.events.length) { renderEvents(); }
        if (activeTab === 'requests' && selectedRequest && requestRecord?.status === 'running') {
          // Poll small headers while waiting, not multi-megabyte prompt bodies.
          const records = await api('model-debug');
          if (version !== sessionVersion) return;
          const row = records.records.find(r => r.request_id === selectedRequest);
          requestCompleted = !!row && row.status !== 'running';
          if (!requestCompleted && requestStatusNode) requestStatusNode.textContent = modelRequestSummary(requestRecord);
        }
      }, false);
    }
    if (activeTab === 'requests' && !paused && !busy && !document.hidden && (!selectedRequest || requestCompleted))
      selectModelDebug(selectedRequest);
    clearTimeout(timer); timer = setTimeout(poll, 1000);
  }
  $('pause').addEventListener('click', () => {
    paused = !paused; $('pause').textContent = paused ? '继续刷新' : '暂停刷新';
    $('connection').textContent = paused ? '已暂停 · 可继续查详情' : '正在连接';
    $('connection-dot').classList.toggle('off', paused); if (!paused) poll();
  });
  $('search').addEventListener('input', renderEvents);
  $('session-select').addEventListener('change', () => {
    const id = $('session-select').value;
    // Identity changes cannot compete with replaceable detail requests.
    // In-flight reads keep their old URL but their results are discarded.
    resetSession(id);
  });
  $('session-refresh').addEventListener('click', () => exclusive(() => loadSessions()));
  $('session-next').addEventListener('click', () => exclusive(() => loadSessions(sessionCursor)));
  $('more').addEventListener('click', () => { visibleCount += 100; renderEvents(); });
  function selectTab(tab) {
    activeTab = tab; ++detailVersion;
    expandDetail(false);
    setDetail(tab === 'events' ? 'Event details' : tab, null);
    $('detail-body').append(notice('加载中…'));
    document.querySelector('.workspace').classList.toggle('single-view', tab !== 'events');
    for (const name of ['events', 'skills', 'requests', 'dst']) {
      const node = $('tab-' + name), selected = name === tab;
      node.classList.toggle('selected', selected);
      node.setAttribute('aria-selected', String(selected));
      node.tabIndex = selected ? 0 : -1;
    }
    $('detail-panel').setAttribute('aria-label', tab === 'events' ? 'Event details' : tab);
    if (tab === 'events') {
      if (selectedSequence !== null) selectEvent(selectedSequence);
      else { setDetail('Event details', null); $('detail-body').append(notice('选择事件查看完整 JSON。')); }
    } else if (tab === 'skills') selectRunMetadata();
    else if (tab === 'requests') selectModelDebug();
    else if (tab === 'dst') selectState();
  }
  const tabs = ['events', 'skills', 'requests', 'dst'];
  for (const [index, tab] of tabs.entries()) {
    $('tab-' + tab).addEventListener('click', () => selectTab(tab));
    $('tab-' + tab).addEventListener('keydown', event => {
      if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
        : (index + (event.key === 'ArrowDown' ? 1 : -1) + tabs.length) % tabs.length;
      $('tab-' + tabs[next]).focus(); selectTab(tabs[next]);
    });
  }
  function expandDetail(expanded) {
    document.querySelector('.workspace').classList.toggle('detail-expanded', expanded);
    $('expand-detail').textContent = expanded ? '还原布局' : '放大详情';
    $('expand-detail').setAttribute('aria-expanded', String(expanded));
  }
  $('expand-detail').addEventListener('click', () => {
    expandDetail(!document.querySelector('.workspace').classList.contains('detail-expanded'));
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') expandDetail(false); });
  $('copy').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(JSON.stringify(copyValue, null, 2)); $('copy').textContent = '已复制'; setTimeout(() => { $('copy').textContent = '复制 JSON'; }, 1200); }
    catch { error('浏览器未允许复制，请在原始 JSON 中选取文本。'); }
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
  selectTab('events'); renderEvents(); poll();
}
if (typeof document !== 'undefined') boot();
