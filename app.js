const state = { history: [], mode: 'fast', currentView: 'chat', running: false, terminalRun: null, terminalHistory: [], terminalHistoryIndex: 0, terminalTranscript: '', project: null, threadId: null, pendingAttachments: [] };
const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const messages = $('#messages');
const prompt = $('#prompt');
const intro = $('#intro');
const modeNames = { fast: 'Fast', balanced: 'Balanced', deep: 'Deep' };

function renderMode() {
  const label = modeNames[state.mode] || modeNames.fast;
  $('#mode').textContent = label;
  $('#settings-mode').textContent = label;
}

function showView(view) {
  state.currentView = view;
  $$('.view').forEach(item => item.classList.toggle('active', item.id === `${view}-view`));
  $$('.nav-link[data-view]').forEach(item => item.classList.toggle('active', item.dataset.view === view));
  $('#breadcrumb').textContent = view === 'mcps' ? 'MCP connections' : view === 'workspace' ? 'Projects' : view[0].toUpperCase() + view.slice(1);
  if (view === 'mcps') refreshMcps();
  if (view === 'workspace') refreshProjects();
}

function setConnected(connected) {
  $('#connection').textContent = connected ? 'Local runtime ready' : 'Local runtime offline';
  $('#connection-dot').className = connected ? 'ready' : 'offline';
}

async function loadStatus() {
  try {
    const data = await fetch('/api/status').then(r => r.json());
    $('#model').textContent = data.model;
    $('#settings-model').textContent = data.model;
    $('#workspace-path').textContent = data.workspace;
    $('#terminal-path').textContent = data.workspace;
    $('#mcp-badge').textContent = data.mcpCount;
    state.project = data.project || null;
    $('#active-project-name').textContent = data.project?.name || 'No project';
    $('#settings-runtime').textContent = data.runtime?.available ? 'Connected' : 'Offline';
    $('#settings-capabilities').textContent = (data.runtime?.capabilities || []).join(', ') || 'Not reported';
    $('#settings-native-context').textContent = data.runtime?.nativeContext ? `${Number(data.runtime.nativeContext).toLocaleString()} tokens` : 'Not reported';
    $('#settings-profile-context').textContent = `${Number(data.profiles?.[state.mode]?.num_ctx || 8192).toLocaleString()} tokens`;
    setConnected(true);
  } catch { setConnected(false); }
}

function clearThreadSurface() {
  messages.querySelectorAll('.message,.run-status').forEach(item => item.remove());
}

async function openThread(threadId) {
  if (state.running) return;
  const response = await fetch(`/api/threads/${threadId}`);
  if (!response.ok) return;
  const thread = await response.json();
  const attachmentData = await fetch(`/api/attachments?threadId=${encodeURIComponent(thread.id)}`).then(item => item.json()).catch(() => ({ items: [] }));
  const attachmentMap = new Map((attachmentData.items || []).map(item => [item.id, item]));
  state.threadId = thread.id;
  state.mode = thread.mode || state.mode;
  renderMode();
  state.history = (thread.messages || []).map(item => ({ role: item.role, content: item.content, attachments: (item.attachments || []).map(id => attachmentMap.get(id)).filter(Boolean) }));
  clearThreadSurface();
  intro.hidden = state.history.length > 0;
  state.history.forEach(item => addMessage(item.role, item.content, item.attachments));
  $$('.thread-row').forEach(item => item.classList.toggle('active', item.querySelector('.thread-item')?.dataset.threadId === thread.id));
  showView('chat');
  prompt.focus();
}

async function refreshThreads(openLatest = false) {
  const list = $('#thread-list');
  if (!state.project) { list.innerHTML = '<p>Link a project to keep chats together.</p>'; return; }
  try {
    const data = await fetch(`/api/threads?projectId=${encodeURIComponent(state.project.id)}`).then(response => response.json());
    list.innerHTML = '';
    if (!data.items.length) list.innerHTML = '<p>No chats in this project yet.</p>';
    data.items.forEach(thread => {
      const row = document.createElement('div'); row.className = `thread-row ${thread.id === state.threadId ? 'active' : ''}`;
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'thread-item'; button.dataset.threadId = thread.id;
      const title = document.createElement('span'); title.textContent = thread.title || 'New chat';
      const meta = document.createElement('small'); meta.textContent = `${thread.messageCount || 0} messages`;
      button.append(title, meta); button.addEventListener('click', () => openThread(thread.id));
      const actions = document.createElement('div'); actions.className = 'thread-actions';
      const rename = document.createElement('button'); rename.type = 'button'; rename.title = 'Rename chat'; rename.dataset.icon = 'edit';
      rename.addEventListener('click', async () => { const next = window.prompt('Rename chat', thread.title || 'New chat'); if (!next?.trim()) return; await fetch(`/api/threads/${thread.id}/rename`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: next.trim() }) }); refreshThreads(); });
      const archive = document.createElement('button'); archive.type = 'button'; archive.title = 'Archive chat'; archive.dataset.icon = 'archive';
      archive.addEventListener('click', async () => { await fetch(`/api/threads/${thread.id}/archive`, { method: 'POST' }); if (state.threadId === thread.id) await createChat(); else refreshThreads(); });
      actions.append(rename, archive); row.append(button, actions); list.append(row); window.renderQwenIcons(row);
    });
    if (openLatest && data.items.length) await openThread(data.items[0].id);
  } catch { list.innerHTML = '<p>Chats could not be loaded.</p>'; }
}

async function createChat() {
  if (state.running) return null;
  const response = await fetch('/api/threads', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ projectId: state.project?.id || null, mode: state.mode }) });
  if (!response.ok) return null;
  const thread = await response.json();
  state.threadId = thread.id; state.history = []; state.pendingAttachments = []; renderAttachmentTray(); clearThreadSurface(); intro.hidden = false; showView('chat');
  await refreshThreads(); prompt.focus(); return thread;
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function attachmentVisual(attachment, removable = false) {
  const item = document.createElement('div'); item.className = `attachment-chip ${attachment.kind}`;
  if (attachment.kind === 'image' || attachment.kind === 'video') {
    const preview = document.createElement('img'); preview.src = `/api/attachments/${attachment.id}/content`; preview.alt = ''; item.append(preview);
  } else {
    const mark = document.createElement('span'); mark.className = 'attachment-kind'; mark.textContent = attachment.kind === 'text' ? 'TXT' : 'FILE'; item.append(mark);
  }
  const info = document.createElement('div'); const name = document.createElement('strong'); name.textContent = attachment.name;
  const meta = document.createElement('small'); meta.textContent = attachment.kind === 'video' ? `${attachment.frameCount || 0} sampled frames · ${formatBytes(attachment.size)}` : `${attachment.kind} · ${formatBytes(attachment.size)}`;
  info.append(name, meta); item.append(info);
  if (removable) {
    const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '×'; remove.setAttribute('aria-label', `Remove ${attachment.name}`);
    remove.addEventListener('click', async () => { await fetch(`/api/attachments/${attachment.id}`, { method: 'DELETE' }); state.pendingAttachments = state.pendingAttachments.filter(entry => entry.id !== attachment.id); renderAttachmentTray(); }); item.append(remove);
  }
  return item;
}

function renderAttachmentTray() {
  const tray = $('#attachment-tray'); tray.innerHTML = ''; tray.hidden = !state.pendingAttachments.length;
  state.pendingAttachments.forEach(item => tray.append(attachmentVisual(item, true)));
}

async function ingestAttachmentPaths(paths) {
  if (!paths?.length) return;
  if (!state.threadId && !(await createChat())) return;
  const button = $('#attach-files'); button.disabled = true; button.lastChild.textContent = ' Processing';
  try {
    const response = await fetch('/api/attachments', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ paths, threadId: state.threadId }) });
    const data = await response.json();
    state.pendingAttachments.push(...(data.items || [])); renderAttachmentTray();
    if (data.errors?.length) {
      const error = document.createElement('div'); error.className = 'attachment-error'; error.textContent = data.errors.map(item => item.error).join(' '); $('#attachment-tray').append(error); $('#attachment-tray').hidden = false;
    }
  } finally { button.disabled = false; button.lastChild.textContent = 'Attach'; }
}

async function chooseAttachments() {
  const paths = await window.qwenDesktop?.chooseAttachments?.();
  await ingestAttachmentPaths(paths || []);
}

function toggleTerminal(force) {
  const panel = $('#terminal-panel');
  const open = typeof force === 'boolean' ? force : panel.hidden;
  panel.hidden = !open;
  $('.surface').classList.toggle('terminal-open', open);
  $('#terminal-toggle').setAttribute('aria-expanded', String(open));
  if (open) $('#terminal-input').focus();
}

function setTerminalRunning(running) {
  $('#terminal-input').disabled = running;
  $('#terminal-form button').disabled = running;
  $('#terminal-stop').hidden = !running;
  $('#terminal-status').textContent = running ? 'Running' : 'Ready';
  $('#terminal-status').classList.toggle('running', running);
}

async function watchTerminal(runId, command) {
  const output = $('#terminal-output');
  while (state.terminalRun === runId) {
    await new Promise(resolve => setTimeout(resolve, 450));
    let response;
    try { response = await fetch(`/api/terminal/${runId}`); }
    catch { $('#terminal-status').textContent = 'Reconnecting'; continue; }
    if (!response.ok) throw new Error('The terminal process could not be loaded.');
    const run = await response.json();
    const current = `PS ${run.workspace}> ${command}\n${run.output || ''}`;
    output.textContent = state.terminalTranscript + current;
    output.scrollTop = output.scrollHeight;
    if (run.status !== 'running') {
      const label = run.status === 'stopped' ? 'Stopped' : run.status === 'error' ? 'Failed' : `Exited ${run.exitCode}`;
      state.terminalTranscript += `${current}\n[${label}]\n`;
      output.textContent = state.terminalTranscript;
      state.terminalRun = null;
      setTerminalRunning(false);
      $('#terminal-status').textContent = label;
      $('#terminal-input').focus();
      return;
    }
  }
}

async function runTerminalCommand(command) {
  if (!command.trim() || state.terminalRun) return;
  toggleTerminal(true);
  state.terminalHistory.push(command.trim());
  state.terminalHistoryIndex = state.terminalHistory.length;
  setTerminalRunning(true);
  $('#terminal-output').textContent = `${state.terminalTranscript}PS> ${command.trim()}\n`;
  try {
    const response = await fetch('/api/terminal', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ command: command.trim() }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'The command could not start.');
    state.terminalRun = data.id;
    await watchTerminal(data.id, command.trim());
  } catch (error) {
    state.terminalRun = null;
    setTerminalRunning(false);
    $('#terminal-status').textContent = 'Failed';
    state.terminalTranscript += `PS> ${command.trim()}\nTerminal error: ${error.message}\n`;
    $('#terminal-output').textContent = state.terminalTranscript;
  }
}

function renderAssistantContent(container, text) {
  const pattern = /```([\w.+-]*)\r?\n([\s\S]*?)```/g;
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > cursor) {
      const prose = document.createElement('div'); prose.className = 'message-prose'; prose.textContent = text.slice(cursor, match.index); container.append(prose);
    }
    const block = document.createElement('section'); block.className = 'code-block';
    const head = document.createElement('header'); const language = document.createElement('span'); language.textContent = match[1] || 'code';
    const copy = document.createElement('button'); copy.type = 'button'; copy.textContent = 'Copy';
    copy.addEventListener('click', async () => { await navigator.clipboard.writeText(match[2]); copy.textContent = 'Copied'; setTimeout(() => { copy.textContent = 'Copy'; }, 1400); });
    const pre = document.createElement('pre'); const code = document.createElement('code'); code.textContent = match[2].replace(/\s+$/, ''); pre.append(code);
    head.append(language, copy); block.append(head, pre); container.append(block); cursor = match.index + match[0].length;
  }
  if (cursor < text.length || !container.children.length) {
    const prose = document.createElement('div'); prose.className = 'message-prose'; prose.textContent = text.slice(cursor); container.append(prose);
  }
}

function addMessage(role, text, attachments = []) {
  const message = document.createElement('article');
  message.className = `message ${role}`;
  const label = document.createElement('span');
  label.className = 'message-label';
  label.textContent = role === 'user' ? 'You' : 'Qwen';
  message.append(label);
  if (role === 'assistant') renderAssistantContent(message, text);
  else message.append(document.createTextNode(text));
  if (attachments?.length) {
    const media = document.createElement('div'); media.className = 'message-attachments'; attachments.forEach(item => media.append(attachmentVisual(item))); message.append(media);
  }
  messages.append(message);
  message.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function addRunStatus() {
  const card = document.createElement('section');
  card.className = 'run-status';
  card.innerHTML = '<div class="run-status-head"><span class="run-spinner"></span><strong>Qwen is working</strong><span class="run-elapsed">0:00</span><span class="run-state">Starting</span><button class="run-stop" type="button">Stop</button></div><div class="run-live" role="status" aria-live="polite"><span class="live-pulse"></span><div><strong>Starting the local agent</strong><small>Preparing your request…</small></div></div><div class="run-events"></div>';
  messages.append(card);
  card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  return card;
}

function finishRunCard(card, stateLabel, failed = false) {
  card.querySelector('.run-spinner').classList.add(failed ? 'failed' : 'done');
  card.querySelector('.run-state').textContent = stateLabel;
  card.querySelector('.run-live')?.classList.add(failed ? 'failed' : 'finished');
}

function updateRunActivity(card, job) {
  const live = card.querySelector('.run-live');
  if (!live) return;
  const labels = { queued: 'Queued', setup: 'Preparing your workspace', model: 'Loading the request into Qwen', generating: 'Qwen is generating', tool: 'Using a computer tool', complete: 'Finished' };
  live.querySelector('strong').textContent = labels[job.phase] || 'Qwen is working';
  const metrics = job.metrics || {};
  const generated = metrics.generatedCharacters ? ` · ${Number(metrics.generatedCharacters).toLocaleString()} characters generated` : '';
  const staleSeconds = Math.max(0, Math.floor(Date.now() / 1000 - (job.updatedAt || Date.now() / 1000)));
  if (job.phase === 'generating' && staleSeconds >= 10) {
    live.querySelector('strong').textContent = 'Waiting for more model output';
    live.querySelector('small').textContent = `Qwen has produced no new output for ${staleSeconds} seconds. The app will stop the run if this reaches 45 seconds.${generated}`;
  } else {
    live.querySelector('small').textContent = `${job.activity || 'Waiting for the next update…'}${generated}`;
  }
  const elapsed = Math.max(0, Math.floor(Date.now() / 1000 - (job.createdAt || Date.now() / 1000)));
  card.querySelector('.run-elapsed').textContent = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')}`;
  card.querySelector('.run-state').textContent = job.phase === 'generating' ? 'Generating' : job.phase === 'tool' ? 'Using tool' : 'Running';
}

function appendRunEvent(card, event) {
  const item = document.createElement('div');
  item.className = `run-event ${event.kind}`;
  const title = document.createElement('div');
  title.className = 'run-event-title';
  title.textContent = event.text;
  item.append(title);
  if (event.detail && Object.keys(event.detail).length) {
    const details = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = 'How this works';
    const fields = document.createElement('dl');
    Object.entries(event.detail).forEach(([label, value]) => {
      const term = document.createElement('dt');
      const description = document.createElement('dd');
      term.textContent = label;
      description.textContent = String(value);
      if (/command|path|input|output|error/i.test(label)) description.className = 'technical-value';
      fields.append(term, description);
    });
    details.append(summary, fields);
    item.append(details);
  }
  card.querySelector('.run-events').append(item);
  item.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

async function watchJob(jobId, card) {
  let eventCount = 0;
  let connectionFailures = 0;
  card.querySelector('.run-stop').addEventListener('click', async () => {
    card.querySelector('.run-stop').disabled = true;
    card.querySelector('.run-stop').textContent = 'Stopping';
    await fetch(`/api/jobs/${jobId}`, { method: 'DELETE' });
  });
  while (true) {
    await new Promise(resolve => setTimeout(resolve, 800));
    let response;
    try {
      response = await fetch(`/api/jobs/${jobId}`);
      connectionFailures = 0;
      setConnected(true);
    } catch {
      connectionFailures += 1;
      setConnected(false);
      card.querySelector('.run-state').textContent = 'Reconnecting';
      if (connectionFailures < 20) continue;
      throw new Error('The local agent backend disconnected and could not restart.');
    }
    if (response.status === 404) throw new Error('The agent restarted during this task. Please send the prompt again.');
    if (!response.ok) throw new Error('The agent job could not be loaded.');
    const job = await response.json();
    updateRunActivity(card, job);
    (job.events || []).slice(eventCount).forEach(event => appendRunEvent(card, event));
    eventCount = (job.events || []).length;
    if (job.status === 'complete') {
      finishRunCard(card, 'Complete');
      const answer = job.message?.content || 'Qwen returned an empty response.';
      state.history.push({ role: 'assistant', content: answer });
      addMessage('assistant', answer);
      return;
    }
    if (job.status === 'error' || job.status === 'stopped') {
      finishRunCard(card, 'Stopped', true);
      throw new Error(job.error || 'Qwen could not complete that request.');
    }
  }
}

async function newChat() { await createChat(); }

async function sendMessage(text) {
  if ((!text.trim() && !state.pendingAttachments.length) || state.running) return;
  if (!state.threadId && !(await createChat())) return;
  const outgoingAttachments = [...state.pendingAttachments];
  const outgoingText = text.trim() || 'Review the attached file and help me with it.';
  state.running = true;
  intro.hidden = true;
  state.history.push({ role: 'user', content: outgoingText, attachments: outgoingAttachments });
  addMessage('user', outgoingText, outgoingAttachments);
  $('#send').disabled = true;
  $('#send').textContent = 'Working';
  const runCard = addRunStatus();
  try {
    const response = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ threadId: state.threadId, message: outgoingText, attachments: outgoingAttachments.map(item => item.id), mode: state.mode }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Qwen could not start that request.');
    state.threadId = data.threadId || state.threadId;
    state.pendingAttachments = []; renderAttachmentTray();
    await watchJob(data.jobId, runCard);
    await refreshThreads();
    setConnected(true);
  } catch (error) {
    finishRunCard(runCard, 'Stopped', true);
    const live = runCard.querySelector('.run-live');
    live.querySelector('strong').textContent = 'The run stopped';
    live.querySelector('small').textContent = error.message;
    addMessage('assistant', `Error: ${error.message}`);
  }
  finally { state.running = false; $('#send').disabled = false; $('#send').textContent = 'Send'; prompt.focus(); }
}

function argsToLines(args = []) { return args.join('\n'); }
function libraryItem(item) {
  const element = document.createElement('article');
  element.className = 'library-item';
  element.innerHTML = `<strong>${item.name}</strong><p>${item.description}</p><button type="button">Use template</button>`;
  element.querySelector('button').addEventListener('click', () => {
    $('#mcp-form').hidden = false;
    const form = $('#mcp-form');
    form.name.value = item.name;
    form.command.value = item.command;
    form.args.value = argsToLines(item.args);
    form.env.value = '';
  });
  return element;
}

async function refreshMcps() {
  try {
    const [connections, library] = await Promise.all([fetch('/api/mcps').then(r => r.json()), fetch('/api/mcp-library').then(r => r.json())]);
    const list = $('#mcp-list'); list.innerHTML = '';
    if (!connections.connections.length) list.innerHTML = '<p class="muted">No MCP connections yet.</p>';
    connections.connections.forEach(connection => {
      const card = document.createElement('article'); card.className = 'mcp-card';
      card.innerHTML = `<div class="mcp-letter">${connection.name[0].toUpperCase()}</div><div class="mcp-main"><strong>${connection.name}</strong><span>${connection.command} ${(connection.args || []).join(' ')}</span></div><div class="mcp-actions"><button class="outline test">Test</button><button class="outline danger remove">Remove</button></div>`;
      card.querySelector('.test').addEventListener('click', async () => { const button = card.querySelector('.test'); button.textContent = 'Testing'; try { const result = await fetch(`/api/mcps/${encodeURIComponent(connection.id)}/test`, { method: 'POST' }).then(r => r.json()); button.textContent = `${(result.tools || []).length} tools`; } catch { button.textContent = 'Failed'; } });
      card.querySelector('.remove').addEventListener('click', async () => { await fetch(`/api/mcps/${encodeURIComponent(connection.id)}`, { method: 'DELETE' }); refreshMcps(); loadStatus(); });
      list.append(card);
    });
    const libraryList = $('#library-list'); libraryList.innerHTML = ''; library.items.forEach(item => libraryList.append(libraryItem(item)));
  } catch { $('#mcp-list').innerHTML = '<p class="muted">Unable to load MCP connections.</p>'; }
}

async function refreshProjects() {
  try {
    const [projects, tree] = await Promise.all([fetch('/api/projects').then(r => r.json()), fetch('/api/project/files').then(r => r.json())]);
    const list = $('#project-list'); list.innerHTML = '';
    if (!projects.items.length) list.innerHTML = '<p class="muted">No project folders linked yet. Link a folder to give Qwen a dedicated workspace.</p>';
    projects.items.forEach(project => {
      const card = document.createElement('article');
      const active = projects.active === project.id;
      card.className = `project-card ${active ? 'active' : ''}`;
      card.innerHTML = `<span class="project-icon" data-icon="folder"></span><div class="project-main"><strong>${project.name}</strong><span>${project.path}</span></div><div class="project-actions">${active ? '<span class="active-project"><span data-icon="check"></span>Active</span>' : '<button class="outline activate">Open</button>'}<button class="icon-only remove-project" title="Unlink project" data-icon="trash"></button></div>`;
      card.querySelector('.activate')?.addEventListener('click', async () => { await fetch(`/api/projects/${project.id}/activate`, { method: 'POST' }); state.threadId = null; state.history = []; clearThreadSurface(); intro.hidden = false; await Promise.all([refreshProjects(), loadStatus()]); await refreshThreads(true); });
      card.querySelector('.remove-project').addEventListener('click', async () => { await fetch(`/api/projects/${project.id}`, { method: 'DELETE' }); await Promise.all([refreshProjects(), loadStatus()]); });
      list.append(card); window.renderQwenIcons(card);
    });
    $('#workspace-path').textContent = tree.path;
    const files = $('#project-file-list'); files.innerHTML = '';
    if (!tree.files.length) files.innerHTML = '<p class="muted">This folder is empty.</p>';
    tree.files.forEach(file => {
      const row = document.createElement('div'); row.className = 'file-row';
      row.innerHTML = `<span data-icon="${file.type === 'folder' ? 'folder' : 'file'}"></span><span>${file.name}</span><small>${file.type}</small>`;
      files.append(row); window.renderQwenIcons(row);
    });
  } catch { $('#project-list').innerHTML = '<p class="muted">Unable to load projects.</p>'; }
}

async function linkProject() {
  if (!window.qwenDesktop?.chooseProjectFolder) { alert('Folder selection is available in the desktop app.'); return; }
  const path = await window.qwenDesktop.chooseProjectFolder();
  if (!path) return;
  const response = await fetch('/api/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }) });
  if (!response.ok) { const error = await response.json(); alert(error.error || 'Could not link this folder.'); return; }
  await Promise.all([refreshProjects(), loadStatus()]);
  state.threadId = null; state.history = []; clearThreadSurface(); intro.hidden = false; await refreshThreads(true);
}

async function createProject() {
  if (!window.qwenDesktop?.chooseProjectParent) { alert('Project creation is available in the desktop app.'); return; }
  const name = window.prompt('Project name');
  if (!name?.trim()) return;
  const parent = await window.qwenDesktop.chooseProjectParent();
  if (!parent) return;
  const response = await fetch('/api/projects/create', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ parent, name: name.trim() }) });
  const data = await response.json();
  if (!response.ok) { alert(data.error || 'Could not create this project.'); return; }
  state.threadId = null; state.history = []; clearThreadSurface(); intro.hidden = false;
  await Promise.all([refreshProjects(), loadStatus()]);
  await createChat();
}

$$('[data-view]').forEach(button => button.addEventListener('click', () => showView(button.dataset.view)));
$('#new-chat').addEventListener('click', newChat);
$('#sidebar-new-chat').addEventListener('click', newChat);
$('#link-project').addEventListener('click', linkProject);
$('#create-project').addEventListener('click', createProject);
$('#mode').addEventListener('click', () => { const modes = ['fast', 'balanced', 'deep']; state.mode = modes[(modes.indexOf(state.mode) + 1) % modes.length]; renderMode(); loadStatus(); });
$('#settings-mode').addEventListener('click', () => $('#mode').click());
$('#terminal-toggle').addEventListener('click', () => toggleTerminal());
$('#attach-files').addEventListener('click', chooseAttachments);
$('#terminal-close').addEventListener('click', () => toggleTerminal(false));
$('#terminal-clear').addEventListener('click', () => { state.terminalTranscript = ''; $('#terminal-output').textContent = ''; });
$('#terminal-stop').addEventListener('click', async () => { if (state.terminalRun) await fetch(`/api/terminal/${state.terminalRun}`, { method: 'DELETE' }); });
$('#terminal-form').addEventListener('submit', event => { event.preventDefault(); const input = $('#terminal-input'); const command = input.value; input.value = ''; runTerminalCommand(command); });
$('#terminal-input').addEventListener('keydown', event => {
  if (!['ArrowUp', 'ArrowDown'].includes(event.key) || !state.terminalHistory.length) return;
  event.preventDefault();
  state.terminalHistoryIndex = event.key === 'ArrowUp' ? Math.max(0, state.terminalHistoryIndex - 1) : Math.min(state.terminalHistory.length, state.terminalHistoryIndex + 1);
  event.currentTarget.value = state.terminalHistory[state.terminalHistoryIndex] || '';
});
$('#composer').addEventListener('dragover', event => { event.preventDefault(); event.currentTarget.classList.add('dragging'); });
$('#composer').addEventListener('dragleave', event => { if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.classList.remove('dragging'); });
$('#composer').addEventListener('drop', event => { event.preventDefault(); event.currentTarget.classList.remove('dragging'); const paths = [...event.dataTransfer.files].map(file => window.qwenDesktop?.filePath?.(file)).filter(Boolean); ingestAttachmentPaths(paths); });
$('#composer').addEventListener('submit', event => { event.preventDefault(); const text = prompt.value; prompt.value = ''; sendMessage(text); });
prompt.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('#composer').requestSubmit(); } });
$$('.starter').forEach(button => button.addEventListener('click', () => { prompt.value = button.textContent; prompt.focus(); }));
$('#show-add').addEventListener('click', () => $('#mcp-form').hidden = false);
$('#close-add').addEventListener('click', () => $('#mcp-form').hidden = true);
$('#cancel-add').addEventListener('click', () => $('#mcp-form').hidden = true);
$('#mcp-form').addEventListener('submit', async event => {
  event.preventDefault(); const form = event.currentTarget;
  let env = {}; try { env = form.env.value.trim() ? JSON.parse(form.env.value) : {}; } catch { alert('Environment JSON is not valid.'); return; }
  const body = { name: form.name.value, command: form.command.value, args: form.args.value.split('\n').map(item => item.trim()).filter(Boolean), env };
  const response = await fetch('/api/mcps', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!response.ok) { const error = await response.json(); alert(error.error || 'Could not save this connection.'); return; }
  form.reset(); form.hidden = true; refreshMcps(); loadStatus();
});
document.addEventListener('keydown', event => {
  if (event.ctrlKey && event.key.toLowerCase() === 'k') { event.preventDefault(); newChat(); }
  if (event.ctrlKey && event.key === '`') { event.preventDefault(); toggleTerminal(); }
});
loadStatus().then(() => refreshThreads(true));
setInterval(loadStatus, 5000);
