const state = { history: [], mode: 'fast', profiles: {}, supervisor: {}, recoveryJobs: [], currentView: 'chat', running: false, runtimeReady: false, activeJobId: null, activeRunCard: null, queuedDirections: [], steering: false, terminalRun: null, terminalHistory: [], terminalHistoryIndex: 0, terminalTranscript: '', project: null, threadId: null, threadProjectId: null, pendingAttachments: [] };
const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const messages = $('#messages');
const prompt = $('#prompt');
const intro = $('#intro');
const modeNames = { fast: 'Fast', balanced: 'Balanced', deep: 'Deep' };

function showNotice(text, kind = 'error') {
  const notice = $('#app-notice'); if (!notice) return;
  notice.hidden = false; notice.className = `app-notice ${kind}`; notice.textContent = text;
  clearTimeout(showNotice.timer); showNotice.timer = setTimeout(() => { notice.hidden = true; }, 7000);
}

function renderMode() {
  const label = modeNames[state.mode] || modeNames.fast;
  const context = Number(state.profiles?.[state.mode]?.num_ctx || ({ fast: 32768, balanced: 65536, deep: 131072 }[state.mode]));
  $('#mode').textContent = `${label} · ${Math.round(context / 1024)}K`;
  $('#settings-mode').textContent = label;
  $('#settings-profile-context').textContent = `${context.toLocaleString()} tokens`;
}

function showView(view) {
  state.currentView = view;
  $$('.view').forEach(item => item.classList.toggle('active', item.id === `${view}-view`));
  $$('.nav-link[data-view]').forEach(item => item.classList.toggle('active', item.dataset.view === view));
  $('#breadcrumb').textContent = view === 'mcps' ? 'MCP connections' : view === 'workspace' ? 'Projects' : view[0].toUpperCase() + view.slice(1);
  if (view === 'mcps') refreshMcps();
  if (view === 'workspace') refreshProjects();
}

function setConnected(connected, label = connected ? 'Local runtime ready' : 'Local runtime offline', status = connected ? 'ready' : 'offline') {
  $('#connection').textContent = label;
  $('#connection-dot').className = status;
}

function updateComposerAvailability() {
  const send = $('#send');
  if (!send || state.running) return;
  send.disabled = !state.runtimeReady;
  send.title = state.runtimeReady ? '' : 'Waiting for Ollama and the selected model';
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
    state.profiles = data.profiles || state.profiles;
    state.supervisor = data.supervisor || state.supervisor;
    renderMode();
    renderSupervisor();
    $('#active-project-name').textContent = data.project?.name || 'No project';
    $('#settings-capabilities').textContent = (data.runtime?.capabilities || []).join(', ') || 'Not reported';
    $('#settings-native-context').textContent = data.runtime?.nativeContext ? `${Number(data.runtime.nativeContext).toLocaleString()} tokens` : 'Not reported';
    state.runtimeReady = Boolean(data.runtime?.available);
    const runtimeState = data.runtime?.state || (state.runtimeReady ? 'ready' : 'offline');
    const runtimeLabel = state.runtimeReady ? 'Local runtime ready' : runtimeState === 'model-missing' ? 'Model not installed' : 'Starting Ollama…';
    $('#settings-runtime').textContent = state.runtimeReady ? 'Connected' : runtimeState === 'model-missing' ? 'Model missing' : 'Starting…';
    setConnected(state.runtimeReady, runtimeLabel, state.runtimeReady ? 'ready' : runtimeState === 'model-missing' ? 'offline' : 'starting');
    updateComposerAvailability();
    if (!state.runtimeReady && !loadStatus.runtimeNoticeShown) {
      showNotice(runtimeState === 'model-missing' ? `${data.model} is not installed. Pick an installed model in Settings, or run “ollama pull ${data.model}” once, then Qwen Studio will connect automatically.` : `Starting Ollama for ${data.model}. The app will become ready automatically when the model is available.`, 'error');
      loadStatus.runtimeNoticeShown = true;
    }
    if (state.runtimeReady) loadStatus.runtimeNoticeShown = false;
    refreshRecoveryJobs();
  } catch { state.runtimeReady = false; setConnected(false, 'Starting local backend…', 'starting'); updateComposerAvailability(); }
}

function fillModelSelect(select, installed, selected, fallback) {
  if (!select) return;
  select.textContent = '';
  const names = [...new Set([...installed, selected, fallback].filter(Boolean))];
  for (const name of names) {
    const option = document.createElement('option');
    option.value = name;
    const installedHere = installed.includes(name);
    option.textContent = installedHere ? name : name === fallback ? `${name} (environment default — not installed)` : `${name} (not installed)`;
    select.append(option);
  }
  if (selected) select.value = selected;
}

async function loadModelPicker() {
  const mainSelect = $('#model-select'); const fastSelect = $('#fast-model-select');
  if (!mainSelect || !fastSelect) return;
  try {
    const data = await fetch('/api/models').then(r => r.json());
    const installed = data.installed || [];
    fillModelSelect(mainSelect, installed, data.selected?.main, data.defaults?.main);
    fillModelSelect(fastSelect, installed, data.selected?.fast, data.defaults?.fast);
    const unavailable = Boolean(data.error) && !installed.length;
    mainSelect.disabled = unavailable; fastSelect.disabled = unavailable;
  } catch { /* backend still starting; the next status pass will retry */ }
}

async function applyModelSelection(changes) {
  try {
    const response = await fetch('/api/models', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(changes) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'The model selection could not be saved.');
    showNotice(`Models updated: Balanced/Deep use ${result.selected.main}; Fast uses ${result.selected.fast}.`, 'success');
    await loadStatus();
  } catch (error) {
    showNotice(error.message);
    await loadModelPicker();
  }
}

function ensureResourceControls() {
  const list = $('.settings-list');
  if (!list || $('#idle-only')) return;
  const group = document.createElement('div'); group.className = 'settings-group';
  const title = document.createElement('span'); title.textContent = 'Idle-only continuation';
  const toggle = document.createElement('input'); toggle.id = 'idle-only'; toggle.type = 'checkbox'; toggle.addEventListener('change', async event => { try { await setSupervisorSettings({ idleOnly: event.currentTarget.checked }); } catch (error) { event.currentTarget.checked = !event.currentTarget.checked; showNotice(error.message); } });
  const hint = document.createElement('small'); hint.textContent = 'Optionally wait while configured game/heavy-process names are running.';
  const processes = document.createElement('input'); processes.id = 'busy-processes'; processes.placeholder = 'Busy process names, comma-separated'; processes.addEventListener('change', async event => { try { await setSupervisorSettings({ busyProcesses: event.currentTarget.value }); } catch (error) { showNotice(error.message); } });
  group.append(title, toggle, processes, hint); list.append(group);
}

function renderSupervisor() {
  ensureResourceControls();
  const data = state.supervisor || {};
  const enabled = Boolean(data.enabled);
  const available = Boolean(data.available);
  const checkbox = $('#supervisor-enabled');
  if (checkbox) { checkbox.checked = enabled; checkbox.disabled = !available; }
  const label = $('#supervisor-toggle-label'); if (label) label.textContent = enabled ? 'Autopilot on' : 'Autopilot off';
  $('#supervisor-toggle')?.classList.toggle('active', enabled);
  const status = $('#supervisor-status');
  if (status) {
    const usage = data.effectiveMethod === 'api' ? ` · ${Number(data.usageRuns || 0)} reviews today · ~$${Number(data.usageEstimatedUsd || 0).toFixed(2)} estimated` : '';
    status.textContent = available ? `${data.effectiveMethod === 'api' ? 'API-key mode (metered)' : 'Codex login'} · ${enabled ? 'enabled' : 'ready to enable'} · ${Number(data.maxRunsPerJob || 0)} reviews/job${usage}` : 'Codex CLI unavailable; install/login before enabling.';
  }
  const mode = $('#supervisor-mode'); if (mode && data.mode) mode.value = data.mode;
  const budget = $('#supervisor-budget'); if (budget && data.dailyBudgetUsd != null) budget.value = data.dailyBudgetUsd;
  const permission = $('#permission-profile'); if (permission && data.permissionProfile) permission.value = data.permissionProfile;
  const lowResource = $('#low-resource'); if (lowResource) lowResource.checked = Boolean(data.lowResource);
  const outputTokens = $('#output-tokens'); if (outputTokens && data.outputTokens != null) outputTokens.value = data.outputTokens;
  const idleOnly = $('#idle-only'); if (idleOnly) idleOnly.checked = Boolean(data.idleOnly);
  const busyProcesses = $('#busy-processes'); if (busyProcesses && data.busyProcesses != null) busyProcesses.value = data.busyProcesses;
}

async function setSupervisorSettings(changes) {
  const response = await fetch('/api/supervisor', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(changes) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Supervisor settings could not be saved.');
  state.supervisor = data.status || state.supervisor; renderSupervisor();
}

async function refreshRecoveryJobs() {
  const banner = $('#recovery-banner'); if (!banner) return;
  try {
    const data = await fetch('/api/jobs').then(response => response.json());
    const jobs = (data.items || []).filter(job => !job.dismissed && ['interrupted', 'error', 'stopped', 'blocked'].includes(job.status)).slice(0, 5);
    state.recoveryJobs = jobs; banner.hidden = !jobs.length; banner.innerHTML = '';
    if (!jobs.length) return;
    const heading = document.createElement('strong'); heading.textContent = 'Work that can be resumed'; banner.append(heading);
    const copy = document.createElement('p'); copy.textContent = 'Qwen Studio saved these jobs. Resume from the latest checkpoint and current files.'; banner.append(copy);
    jobs.forEach(job => {
      const row = document.createElement('div'); row.className = 'recovery-row';
      const text = document.createElement('span'); text.textContent = `${job.activity || 'Previous job'} · ${job.status}`;
      const actions = document.createElement('div'); actions.className = 'recovery-actions';
      const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Resume'; button.addEventListener('click', () => resumeJob(job));
      const dismiss = document.createElement('button'); dismiss.type = 'button'; dismiss.className = 'text-button'; dismiss.textContent = 'Dismiss'; dismiss.addEventListener('click', async () => { await fetch(`/api/jobs/${job.id}/dismiss`, { method: 'POST' }); refreshRecoveryJobs(); });
      actions.append(button, dismiss); row.append(text, actions); banner.append(row);
    });
  } catch { banner.hidden = true; }
}

async function resumeJob(job) {
  if (state.running) return;
  if (job.threadId) await openThread(job.threadId);
  state.running = true; state.activeJobId = job.id; $('#send').disabled = false; $('#send').textContent = 'Steer'; $('#mode').disabled = true;
  const card = addRunStatus(); state.activeRunCard = card;
  try {
    const response = await fetch(`/api/jobs/${job.id}/resume`, { method: 'POST' }); const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'The job could not be resumed.');
    await watchJob(data.jobId || job.id, card); await refreshThreads();
  } catch (error) { finishRunCard(card, 'Stopped', true); addMessage('assistant', `Resume error: ${error.message}`); }
  finally { state.running = false; state.activeJobId = null; state.activeRunCard = null; $('#send').disabled = false; $('#send').textContent = 'Send'; $('#mode').disabled = false; renderSupervisor(); refreshRecoveryJobs(); }
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
  state.threadProjectId = thread.projectId || null;
  state.mode = thread.mode || state.mode;
  renderMode();
  state.history = (thread.messages || []).map(item => ({ role: item.role, content: item.content, attachments: (item.attachments || []).map(id => attachmentMap.get(id)).filter(Boolean) }));
  clearThreadSurface();
  intro.hidden = state.history.length > 0;
  state.history.forEach(item => addMessage(item.role, item.content, item.attachments));
  $$('.thread-row').forEach(item => item.classList.toggle('active', item.querySelector('.thread-item')?.dataset.threadId === thread.id));
  showView('chat');
  $('#active-project-name').textContent = thread.projectId ? (state.project?.name || 'Project chat') : 'General chat';
  prompt.focus();
}

async function activateProject(projectId, openLatest = true) {
  if (state.running) return false;
  const response = await fetch(`/api/projects/${projectId}/activate`, { method: 'POST' });
  if (!response.ok) return false;
  state.threadId = null; state.threadProjectId = null; state.history = []; clearThreadSurface(); intro.hidden = false;
  await loadStatus();
  if (state.currentView === 'workspace') refreshProjects();
  await refreshThreads(openLatest);
  return true;
}

async function openProjectThread(projectId, threadId) {
  if (state.running) return;
  if (state.project?.id !== projectId && !(await activateProject(projectId, false))) return;
  await openThread(threadId);
  await refreshThreads();
}

async function refreshThreads(openLatest = false) {
  const list = $('#thread-list');
  try {
    const [projects, data] = await Promise.all([fetch('/api/projects').then(response => response.json()), fetch('/api/threads').then(response => response.json())]);
    list.innerHTML = '';
    const generalThreads = data.items.filter(thread => !thread.projectId);
    if (generalThreads.length) {
      const general = document.createElement('section'); general.className = 'general-thread-group';
      const heading = document.createElement('div'); heading.className = 'general-thread-heading'; heading.textContent = 'GENERAL CHATS'; general.append(heading);
      const chats = document.createElement('div'); chats.className = 'project-chat-list';
      generalThreads.forEach(thread => appendThreadRow(chats, thread));
      general.append(chats); list.append(general);
    }
    if (!projects.items.length && !generalThreads.length) { list.innerHTML = '<p>No chats yet. Start a general chat or create a project.</p>'; return; }
    projects.items.forEach(project => {
      const projectThreads = data.items.filter(thread => thread.projectId === project.id);
      const group = document.createElement('section'); group.className = `project-thread-group ${project.id === projects.active ? 'active' : ''}`;
      const head = document.createElement('div'); head.className = 'project-thread-head';
      const projectButton = document.createElement('button'); projectButton.type = 'button'; projectButton.className = 'project-tree-button'; projectButton.dataset.projectId = project.id;
      const icon = document.createElement('span'); icon.dataset.icon = 'folder'; const name = document.createElement('span'); name.textContent = project.name;
      const count = document.createElement('small'); count.textContent = String(projectThreads.length); projectButton.append(icon, name, count);
      projectButton.addEventListener('click', () => activateProject(project.id, true));
      const add = document.createElement('button'); add.type = 'button'; add.className = 'project-chat-add'; add.title = `New chat in ${project.name}`; add.dataset.icon = 'plus';
      add.addEventListener('click', async () => { if (state.project?.id !== project.id && !(await activateProject(project.id, false))) return; await createChat(project.id); });
      head.append(projectButton, add); group.append(head);
      const chats = document.createElement('div'); chats.className = 'project-chat-list';
      if (!projectThreads.length) { const empty = document.createElement('p'); empty.textContent = 'No chats yet'; chats.append(empty); }
      projectThreads.forEach(thread => {
        appendThreadRow(chats, thread, project.id);
      });
      group.append(chats); list.append(group); window.renderQwenIcons(group);
    });
    const activeThreads = data.items.filter(thread => thread.projectId === projects.active);
    if (openLatest && activeThreads.length) await openThread(activeThreads[0].id);
  } catch { list.innerHTML = '<p>Projects and chats could not be loaded.</p>'; }
}

function appendThreadRow(container, thread, projectId = null) {
  const row = document.createElement('div'); row.className = `thread-row ${thread.id === state.threadId ? 'active' : ''}`;
  const button = document.createElement('button'); button.type = 'button'; button.className = 'thread-item'; button.dataset.threadId = thread.id;
  const title = document.createElement('span'); title.textContent = thread.title || 'New chat';
  const meta = document.createElement('small'); meta.textContent = `${thread.messageCount || 0} messages`;
  button.append(title, meta); button.addEventListener('click', () => projectId ? openProjectThread(projectId, thread.id) : openThread(thread.id));
  const actions = document.createElement('div'); actions.className = 'thread-actions';
  const rename = document.createElement('button'); rename.type = 'button'; rename.title = 'Rename chat'; rename.dataset.icon = 'edit';
  rename.addEventListener('click', async () => { const next = window.prompt('Rename chat', thread.title || 'New chat'); if (!next?.trim()) return; await fetch(`/api/threads/${thread.id}/rename`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: next.trim() }) }); refreshThreads(); });
  const archive = document.createElement('button'); archive.type = 'button'; archive.title = 'Archive chat'; archive.dataset.icon = 'archive';
  archive.addEventListener('click', async () => { await fetch(`/api/threads/${thread.id}/archive`, { method: 'POST' }); if (state.threadId === thread.id) await createChat(); else refreshThreads(); });
  const pin = document.createElement('button'); pin.type = 'button'; pin.title = thread.pinned ? 'Unpin chat' : 'Pin chat'; pin.dataset.icon = 'pin';
  pin.addEventListener('click', async () => { await fetch(`/api/threads/${thread.id}/pin`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pinned: !thread.pinned }) }); refreshThreads(); });
  const remove = document.createElement('button'); remove.type = 'button'; remove.title = 'Delete chat'; remove.dataset.icon = 'trash';
  remove.addEventListener('click', async () => { if (!window.confirm('Delete this chat permanently?')) return; await fetch(`/api/threads/${thread.id}`, { method: 'DELETE' }); if (state.threadId === thread.id) await createChat(); else refreshThreads(); });
  actions.append(rename, pin, archive, remove); row.append(button, actions); container.append(row); window.renderQwenIcons(row);
}

async function createChat(projectId = state.threadProjectId) {
  if (state.running) return null;
  const response = await fetch('/api/threads', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ projectId, mode: state.mode }) });
  if (!response.ok) return null;
  const thread = await response.json();
  state.threadId = thread.id; state.threadProjectId = projectId; state.history = []; state.pendingAttachments = []; renderAttachmentTray(); clearThreadSurface(); intro.hidden = false; showView('chat');
  $('#active-project-name').textContent = projectId ? (state.project?.name || 'Project chat') : 'General chat';
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
    const preview = document.createElement('img'); preview.alt = ''; item.append(preview);
    fetch(`/api/attachments/${attachment.id}/content`).then(response => {
      if (!response.ok) throw new Error('Attachment preview unavailable.');
      return response.blob();
    }).then(blob => { preview.src = URL.createObjectURL(blob); }).catch(() => { preview.hidden = true; });
  } else {
    const mark = document.createElement('span'); mark.className = 'attachment-kind'; mark.textContent = attachment.kind === 'text' ? 'TXT' : 'FILE'; item.append(mark);
  }
  const info = document.createElement('div'); const name = document.createElement('strong'); name.textContent = attachment.name;
  const meta = document.createElement('small'); meta.textContent = attachment.guidance || (attachment.kind === 'video' ? `${attachment.frameCount || 0} sampled frames · ${formatBytes(attachment.size)}` : `${attachment.kind} · ${formatBytes(attachment.size)}`);
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

function addMessage(role, text, attachments = [], statusText = '') {
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
  if (statusText) { const status = document.createElement('span'); status.className = 'message-status'; status.textContent = statusText; message.append(status); }
  messages.append(message);
  message.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  return message;
}

function addRunStatus() {
  const card = document.createElement('section');
  card.className = 'run-status';
  card.innerHTML = '<div class="run-status-head"><span class="run-spinner"></span><strong>Qwen is working</strong><span class="run-elapsed">0:00</span><span class="run-state">Starting</span><button class="run-pause" type="button">Pause</button><button class="run-stop" type="button">Stop</button></div><div class="run-live" role="status" aria-live="polite"><span class="live-pulse"></span><div><strong>Starting the local agent</strong><small>Preparing your request…</small></div></div><div class="run-approval" hidden><strong>Qwen needs your approval</strong><p></p><small></small><div><button class="approve" type="button">Approve once</button><button class="deny" type="button">Deny</button></div></div><pre class="run-draft" aria-label="Live response preview" hidden></pre><div class="run-events"></div>';
  const artifacts = document.createElement('div'); artifacts.className = 'run-artifacts'; artifacts.hidden = true; card.querySelector('.run-events').before(artifacts);
  messages.append(card);
  card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  return card;
}

function finishRunCard(card, stateLabel, failed = false) {
  card.querySelector('.run-spinner').classList.add(failed ? 'failed' : 'done');
  card.querySelector('.run-state').textContent = stateLabel;
  card.querySelector('.run-live')?.classList.add(failed ? 'failed' : 'finished');
  card.querySelector('.run-pause')?.remove();
}

function updateRunActivity(card, job) {
  const live = card.querySelector('.run-live');
  if (!live) return;
  const approval = card.querySelector('.run-approval');
  if (approval) {
    const pending = job.pendingApproval;
    approval.hidden = !pending;
    if (pending) {
      approval.querySelector('p').textContent = pending.request?.reason || 'This action needs your approval.';
      const detail = pending.request?.command || pending.request?.target || pending.request?.tool || '';
      approval.querySelector('small').textContent = detail;
      approval.querySelector('.approve').onclick = () => respondToApproval(job.id, true, approval);
      approval.querySelector('.deny').onclick = () => respondToApproval(job.id, false, approval);
    }
  }
  const labels = { queued: 'Queued', setup: 'Preparing your workspace', waiting: 'Waiting for idle time', model: 'Loading the request into Qwen', generating: 'Qwen is generating', tool: 'Using a computer tool', approval: 'Waiting for your approval', paused: 'Paused safely', blocked: 'Blocked safely', supervisor: 'Codex is reviewing the evidence', verifying: 'Checking the result', complete: 'Finished', complete_with_warnings: 'Finished with warnings' };
  live.querySelector('strong').textContent = labels[job.phase] || 'Qwen is working';
  const metrics = job.metrics || {};
  const contextSummary = metrics.estimatedContextTokens ? `Context: ${Number(metrics.estimatedContextTokens).toLocaleString()} / ${Number(metrics.contextLimit || 0).toLocaleString()} tokens (${Number(metrics.contextUtilization || 0).toFixed(1)}%)` : '';
  const draft = card.querySelector('.run-draft');
  if (metrics.responsePreview) { draft.hidden = false; draft.textContent = metrics.responsePreview; }
  const generated = metrics.totalGeneratedTokens ? ` · ${Number(metrics.totalGeneratedTokens).toLocaleString()} generated tokens total` : metrics.generatedCharacters ? ` · ${Number(metrics.generatedCharacters).toLocaleString()} characters generated` : '';
  const staleSeconds = Math.max(0, Math.floor(Date.now() / 1000 - (job.updatedAt || Date.now() / 1000)));
  if (['model', 'generating'].includes(job.phase) && staleSeconds >= 10) {
    live.querySelector('strong').textContent = job.phase === 'model' ? 'Ollama is processing the conversation' : 'Waiting for more model output';
    live.querySelector('small').textContent = `Ollama is still processing this agent step. No new token for ${staleSeconds}s · this run has no automatic time limit. Use Stop only if you want to end it.${generated}`;
  } else {
    live.querySelector('small').textContent = `${job.activity || 'Waiting for the next update…'}${generated}`;
  }
  renderRunArtifacts(card, job);
  if (contextSummary) live.querySelector('small').textContent += ` · ${contextSummary}`;
  const elapsed = Math.max(0, Math.floor(Date.now() / 1000 - (job.createdAt || Date.now() / 1000)));
  card.querySelector('.run-elapsed').textContent = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')}`;
  const pause = card.querySelector('.run-pause');
  if (pause) { pause.textContent = job.pauseRequested ? 'Resume' : 'Pause'; pause.disabled = Boolean(job.pendingApproval); pause.onclick = () => respondToPause(job.id, !job.pauseRequested, pause); }
  card.querySelector('.run-state').textContent = job.phase === 'paused' ? 'Paused' : job.phase === 'blocked' ? 'Blocked' : job.phase === 'generating' ? 'Generating' : job.phase === 'tool' ? 'Using tool' : job.phase === 'supervisor' ? 'Supervising' : job.phase === 'verifying' ? 'Verifying' : 'Running';
}

function renderRunArtifacts(card, job) {
  const container = card.querySelector('.run-artifacts');
  if (!container) return;
  container.textContent = '';
  const artifacts = [...new Set((job.artifacts || []).filter(path => path && !String(path).startsWith('Files created by')))].slice(0, 24);
  if (!artifacts.length) { container.hidden = true; return; }
  container.hidden = false;
  const heading = document.createElement('strong'); heading.textContent = 'Files Qwen changed'; container.append(heading);
  const list = document.createElement('div'); list.className = 'run-artifact-list';
  artifacts.forEach(path => {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'run-artifact'; button.textContent = String(path); button.title = 'Open a read-only file review';
    button.addEventListener('click', () => { showView('workspace'); reviewProjectFile(String(path)); });
    list.append(button);
  });
  container.append(list);
}

async function respondToPause(jobId, paused, button) {
  button.disabled = true;
  try {
    const response = await fetch(`/api/jobs/${jobId}/pause`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ paused }) });
    if (!response.ok) throw new Error((await response.json()).error || 'Pause state could not be changed.');
  } catch (error) { showNotice(error.message); button.disabled = false; }
}

async function respondToApproval(jobId, approved, panel) {
  panel.querySelectorAll('button').forEach(button => { button.disabled = true; });
  try {
    const response = await fetch(`/api/jobs/${jobId}/approve`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ approved }) });
    if (!response.ok) throw new Error((await response.json()).error || 'Approval response could not be saved.');
    panel.querySelector('strong').textContent = approved ? 'Approval sent' : 'Denial sent';
  } catch (error) {
    panel.querySelector('small').textContent = error.message;
    panel.querySelectorAll('button').forEach(button => { button.disabled = false; });
  }
}

function appendRunEvent(card, event) {
  const item = document.createElement('div');
  item.className = `run-event ${event.kind}`;
  const title = document.createElement('div');
  title.className = 'run-event-title';
  title.textContent = event.text;
  item.append(title);
  if (event.detail && Object.keys(event.detail).length) {
    const details = document.createElement('div'); details.className = 'run-event-detail';
    const fields = document.createElement('dl');
    Object.entries(event.detail).forEach(([label, value]) => {
      const term = document.createElement('dt');
      const description = document.createElement('dd');
      term.textContent = label;
      description.textContent = String(value);
      if (/command|path|input|output|error/i.test(label)) description.className = 'technical-value';
      fields.append(term, description);
    });
    details.append(fields);
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
    if (job.status === 'complete' || job.status === 'complete_with_warnings') {
      finishRunCard(card, job.status === 'complete_with_warnings' ? 'Complete with warnings' : 'Complete', job.status === 'complete_with_warnings');
      const answer = job.message?.content || 'Qwen returned an empty response.';
      state.history.push({ role: 'assistant', content: answer });
      addMessage('assistant', answer);
      return;
    }
    if (job.status === 'blocked') {
      finishRunCard(card, 'Blocked', true);
      const reason = job.blockedReason || job.error || 'Repeated recovery failures stopped this run safely.';
      addMessage('assistant', `Qwen is blocked: ${reason}\n\nThe files were left in place. Fix the blocker, then resume this job or send a new instruction.`);
      return;
    }
    if (job.status === 'error' || job.status === 'stopped') {
      if (job.status === 'stopped' && state.steering) { finishRunCard(card, 'Steered'); return { steered: true }; }
      finishRunCard(card, 'Stopped', true);
      throw new Error(job.error || 'Qwen could not complete that request.');
    }
  }
}

async function newChat() { await createChat(null); }

async function queueDirection(text) {
  if (!text.trim() && !state.pendingAttachments.length) return;
  const attachments = [...state.pendingAttachments]; state.pendingAttachments = []; renderAttachmentTray();
  const content = text.trim() || 'Review the attached file and incorporate it into the current task.';
  const element = addMessage('user', content, attachments, 'Queued to steer the active run');
  state.queuedDirections.push({ text: content, attachments, element });
  if (state.activeRunCard) appendRunEvent(state.activeRunCard, { kind: 'steer', text: `New direction received: ${content}`, detail: { Queue: `${state.queuedDirections.length} message${state.queuedDirections.length === 1 ? '' : 's'} waiting`, Action: 'Stopping the current model turn, then continuing with this direction' } });
  $('#send').textContent = 'Queued';
  if (!state.steering && state.activeJobId) {
    state.steering = true;
    await fetch(`/api/jobs/${state.activeJobId}`, { method: 'DELETE' });
  }
}

async function drainDirections() {
  if (state.running || !state.queuedDirections.length) return;
  const next = state.queuedDirections.shift();
  const status = next.element?.querySelector('.message-status'); if (status) status.textContent = 'Steering Qwen now';
  await sendMessage(next.text, { attachments: next.attachments, alreadyRendered: true, messageElement: next.element });
}

async function sendMessage(text, options = {}) {
  if (state.running) { await queueDirection(text); return; }
  if (!state.runtimeReady) { showNotice('Ollama is still starting. Qwen will be available when the local runtime indicator turns green.'); return; }
  const availableAttachments = options.attachments || state.pendingAttachments;
  if (!text.trim() && !availableAttachments.length) return;
  if (!state.threadId && !(await createChat())) return;
  const outgoingAttachments = [...availableAttachments];
  const outgoingText = text.trim() || 'Review the attached file and help me with it.';
  state.steering = false;
  state.running = true;
  intro.hidden = true;
  state.history.push({ role: 'user', content: outgoingText, attachments: outgoingAttachments });
  if (!options.alreadyRendered) addMessage('user', outgoingText, outgoingAttachments);
  $('#send').disabled = false;
  $('#send').textContent = 'Steer';
  $('#mode').disabled = true;
  const runCard = addRunStatus();
  state.activeRunCard = runCard;
  try {
    let response; let data;
    for (let attempt = 0; attempt < 12; attempt += 1) {
      response = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ threadId: state.threadId, message: outgoingText, attachments: outgoingAttachments.map(item => item.id), mode: state.mode, supervisor: Boolean(state.supervisor?.enabled) }) });
      data = await response.json();
      if (response.status !== 409 || !options.alreadyRendered) break;
      await new Promise(resolve => setTimeout(resolve, 250));
    }
    if (!response.ok) throw new Error(data.error || 'Qwen could not start that request.');
    const queuedStatus = options.messageElement?.querySelector('.message-status'); if (queuedStatus) queuedStatus.textContent = 'Direction sent to Qwen';
    state.threadId = data.threadId || state.threadId;
    if (!options.attachments) { state.pendingAttachments = []; renderAttachmentTray(); }
    state.activeJobId = data.jobId;
    if (state.queuedDirections.length && !state.steering) { state.steering = true; await fetch(`/api/jobs/${state.activeJobId}`, { method: 'DELETE' }); }
    await watchJob(data.jobId, runCard);
    await refreshThreads();
    setConnected(true);
  } catch (error) {
    if (!state.steering) {
      finishRunCard(runCard, 'Stopped', true);
      const live = runCard.querySelector('.run-live');
      live.querySelector('strong').textContent = 'The run stopped';
      live.querySelector('small').textContent = error.message;
      addMessage('assistant', `Error: ${error.message}`);
    }
  }
  finally {
    state.running = false; state.activeJobId = null; state.activeRunCard = null;
    $('#send').disabled = false; $('#send').textContent = state.queuedDirections.length ? 'Queued' : 'Send'; $('#mode').disabled = false; updateComposerAvailability(); prompt.focus();
    if (state.queuedDirections.length) setTimeout(drainDirections, 0);
  }
}

function argsToLines(args = []) { return args.join('\n'); }
function libraryItem(item) {
  const element = document.createElement('article');
  element.className = 'library-item';
  const name = document.createElement('strong'); name.textContent = item.name;
  const description = document.createElement('p'); description.textContent = item.description;
  const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Use template';
  element.append(name, description, button);
  button.addEventListener('click', () => {
    $('#mcp-form').hidden = false;
    const form = $('#mcp-form');
    form.name.value = item.name;
    form.transport.value = item.transport || 'stdio';
    form.command.value = item.command || '';
    form.url.value = item.url || '';
    if (form.authMode) form.authMode.value = item.authMode || 'none';
    form.args.value = argsToLines(item.args);
    form.env.value = '';
    form.headers.value = '';
    form.transport.dispatchEvent(new Event('change'));
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
      const target = connection.transport === 'streamable-http' ? connection.url : `${connection.command || ''} ${(connection.args || []).join(' ')}`;
      const letter = document.createElement('div'); letter.className = 'mcp-letter'; letter.textContent = (connection.name || 'M')[0].toUpperCase();
      const main = document.createElement('div'); main.className = 'mcp-main';
      const title = document.createElement('strong'); title.textContent = connection.name;
      const endpoint = document.createElement('span'); endpoint.textContent = `${connection.transport === 'streamable-http' ? 'Streamable HTTP · ' : ''}${target}`;
      main.append(title, endpoint);
      const actions = document.createElement('div'); actions.className = 'mcp-actions';
      const toggle = document.createElement('button'); toggle.className = 'outline toggle'; toggle.textContent = connection.enabled === false ? 'Enable' : 'Disable';
      const test = document.createElement('button'); test.className = 'outline test'; test.textContent = 'Test';
      const remove = document.createElement('button'); remove.className = 'outline danger remove'; remove.textContent = 'Remove';
      actions.append(toggle, test, remove); card.append(letter, main, actions);
      toggle.addEventListener('click', async () => { toggle.disabled = true; try { const result = await fetch(`/api/mcps/${encodeURIComponent(connection.id)}/toggle`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: connection.enabled === false }) }).then(r => r.json()); if (result.enabled !== undefined) { connection.enabled = result.enabled; toggle.textContent = result.enabled ? 'Disable' : 'Enable'; } } finally { toggle.disabled = false; } });
  card.querySelector('.test').addEventListener('click', async () => { const button = card.querySelector('.test'); button.textContent = 'Testing'; try { const response = await fetch(`/api/mcps/${encodeURIComponent(connection.id)}/test`, { method: 'POST' }); const result = await response.json(); if (!response.ok) throw new Error(result.error || result.message || 'Connection diagnostics failed.'); button.textContent = `${(result.tools || []).length} tools`; showNotice(`MCP connection is healthy · ${(result.tools || []).length} tools found.`, 'success'); } catch (error) { button.textContent = 'Failed'; showNotice(error.message); } });
      card.querySelector('.remove').addEventListener('click', async () => { await fetch(`/api/mcps/${encodeURIComponent(connection.id)}`, { method: 'DELETE' }); refreshMcps(); loadStatus(); });
      list.append(card);
    });
    const libraryList = $('#library-list'); libraryList.innerHTML = ''; library.items.forEach(item => libraryList.append(libraryItem(item)));
  } catch { $('#mcp-list').innerHTML = '<p class="muted">Unable to load MCP connections.</p>'; }
}

async function refreshProjects() {
  try {
    const [projects, tree, threads] = await Promise.all([fetch('/api/projects').then(r => r.json()), fetch('/api/project/files').then(r => r.json()), fetch('/api/threads').then(r => r.json())]);
    const list = $('#project-list'); list.innerHTML = '';
    if (!projects.items.length) list.innerHTML = '<p class="muted">No project folders linked yet. Link a folder to give Qwen a dedicated workspace.</p>';
    projects.items.forEach(project => {
      const card = document.createElement('article');
      const active = projects.active === project.id;
      card.className = `project-card ${active ? 'active' : ''}`;
      const projectHead = document.createElement('div'); projectHead.className = 'project-card-head';
      const projectIcon = document.createElement('span'); projectIcon.className = 'project-icon'; projectIcon.dataset.icon = 'folder';
      const projectMain = document.createElement('div'); projectMain.className = 'project-main';
      const projectName = document.createElement('strong'); projectName.textContent = project.name;
      const projectPath = document.createElement('span'); projectPath.textContent = project.path;
      projectMain.append(projectName, projectPath);
      const projectActions = document.createElement('div'); projectActions.className = 'project-actions';
      if (active) { const activeLabel = document.createElement('span'); activeLabel.className = 'active-project'; activeLabel.textContent = 'Active'; projectActions.append(activeLabel); }
      else { const activate = document.createElement('button'); activate.className = 'outline activate'; activate.textContent = 'Open'; projectActions.append(activate); }
      const projectPermission = document.createElement('select'); projectPermission.className = 'project-permission'; projectPermission.title = 'Permission profile for this project';
      [['project-write', 'Write'], ['read-only', 'Read'], ['full-access', 'Full']].forEach(([value, label]) => { const option = document.createElement('option'); option.value = value; option.textContent = label; projectPermission.append(option); });
      projectPermission.value = project.permissionProfile || state.supervisor?.permissionProfile || 'project-write';
      projectPermission.addEventListener('change', async () => { const response = await fetch(`/api/projects/${project.id}/permissions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ permissionProfile: projectPermission.value }) }); if (!response.ok) showNotice('The project permission profile could not be saved.'); else { project.permissionProfile = projectPermission.value; showNotice(`Project permissions set to ${projectPermission.options[projectPermission.selectedIndex].text}.`, 'success'); } });
      projectActions.append(projectPermission);
      const removeProject = document.createElement('button'); removeProject.className = 'icon-only remove-project'; removeProject.title = 'Unlink project'; removeProject.dataset.icon = 'trash'; projectActions.append(removeProject);
      projectHead.append(projectIcon, projectMain, projectActions); card.append(projectHead);
      card.querySelector('.activate')?.addEventListener('click', async () => { await activateProject(project.id, true); });
      card.querySelector('.remove-project').addEventListener('click', async () => { await fetch(`/api/projects/${project.id}`, { method: 'DELETE' }); await Promise.all([refreshProjects(), loadStatus()]); });
      const chatArea = document.createElement('div'); chatArea.className = 'project-card-chats';
      const chatHead = document.createElement('div'); chatHead.className = 'project-card-chats-head'; const chatLabel = document.createElement('span'); chatLabel.textContent = 'Chats';
      const addChat = document.createElement('button'); addChat.type = 'button'; addChat.textContent = 'New chat';
      addChat.addEventListener('click', async () => { if (state.project?.id !== project.id && !(await activateProject(project.id, false))) return; await createChat(project.id); });
      chatHead.append(chatLabel, addChat); chatArea.append(chatHead);
      const projectThreads = threads.items.filter(thread => thread.projectId === project.id);
      if (!projectThreads.length) { const empty = document.createElement('p'); empty.textContent = 'No chats in this project yet.'; chatArea.append(empty); }
      projectThreads.slice(0, 8).forEach(thread => {
        const chat = document.createElement('button'); chat.type = 'button'; chat.className = `project-card-chat ${thread.id === state.threadId ? 'active' : ''}`;
        const title = document.createElement('span'); title.textContent = thread.title || 'New chat'; const count = document.createElement('small'); count.textContent = `${thread.messageCount || 0} messages`;
        chat.append(title, count); chat.addEventListener('click', () => openProjectThread(project.id, thread.id)); chatArea.append(chat);
      });
      card.append(chatArea);
      list.append(card); window.renderQwenIcons(card);
    });
    $('#workspace-path').textContent = tree.path;
    const files = $('#project-file-list'); files.innerHTML = '';
    if (!tree.files.length) files.innerHTML = '<p class="muted">This folder is empty.</p>';
    tree.files.forEach(file => {
      const row = document.createElement('div'); row.className = 'file-row';
      const icon = document.createElement('span'); icon.dataset.icon = file.type === 'folder' ? 'folder' : 'file';
      const name = document.createElement('span'); name.textContent = file.name;
      const kind = document.createElement('small'); kind.textContent = file.type;
      row.append(icon, name, kind);
      if (file.type === 'file') { row.tabIndex = 0; row.title = 'Review this file'; row.addEventListener('click', () => reviewProjectFile(file.name)); row.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); reviewProjectFile(file.name); } }); }
      files.append(row); window.renderQwenIcons(row);
    });
    await refreshGitReview();
  } catch { $('#project-list').innerHTML = '<p class="muted">Unable to load projects.</p>'; }
}

async function reviewProjectFile(path) {
  const label = $('#file-review-path'); const content = $('#file-review-content');
  if (!label || !content) return;
  label.textContent = path; content.textContent = 'Reading the current file…';
  try {
    const response = await fetch(`/api/git/file?path=${encodeURIComponent(path)}`); const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'File review failed.');
    content.textContent = data.content || '(empty file)';
  } catch (error) { content.textContent = `File review unavailable: ${error.message}`; }
}

async function refreshGitReview() {
  const summary = $('#git-summary');
  const diff = $('#git-diff-stat');
  if (!summary || !diff) return;
  summary.textContent = 'Checking repository state…';
  diff.textContent = '';
  try {
    const response = await fetch('/api/git');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Git status unavailable');
    if (!data.isRepository) {
      summary.textContent = 'This project folder is not a Git repository.';
      return;
    }
    const branch = data.branch ? ` on ${data.branch}` : '';
    const changes = Array.isArray(data.status) ? data.status.length : 0;
    summary.textContent = changes ? `${changes} uncommitted file${changes === 1 ? '' : 's'}${branch}` : `Working tree clean${branch}`;
    diff.textContent = data.diffStat || 'No diff summary available.';
  } catch (error) {
    summary.textContent = `Git review unavailable: ${error.message}`;
    diff.textContent = '';
  }
}

async function linkProject() {
  if (!window.qwenDesktop?.chooseProjectFolder) { showNotice('Folder selection is available in the desktop app.'); return; }
  const path = await window.qwenDesktop.chooseProjectFolder();
  if (!path) return;
  const response = await fetch('/api/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }) });
  if (!response.ok) { const error = await response.json(); showNotice(error.error || 'Could not link this folder.'); return; }
  await Promise.all([refreshProjects(), loadStatus()]);
  state.threadId = null; state.history = []; clearThreadSurface(); intro.hidden = false; await refreshThreads(true);
}

async function createProject() {
  if (!window.qwenDesktop?.chooseProjectParent) { showNotice('Project creation is available in the desktop app.'); return; }
  const name = window.prompt('Project name');
  if (!name?.trim()) return;
  const parent = await window.qwenDesktop.chooseProjectParent();
  if (!parent) return;
  const response = await fetch('/api/projects/create', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ parent, name: name.trim() }) });
  const data = await response.json();
  if (!response.ok) { showNotice(data.error || 'Could not create this project.'); return; }
  state.threadId = null; state.history = []; clearThreadSurface(); intro.hidden = false;
  await Promise.all([refreshProjects(), loadStatus()]);
  await createChat(state.project?.id || null);
}

$$('[data-view]').forEach(button => button.addEventListener('click', () => showView(button.dataset.view)));
$('#new-chat').addEventListener('click', newChat);
$('#sidebar-new-chat').addEventListener('click', newChat);
$('#link-project').addEventListener('click', linkProject);
$('#create-project').addEventListener('click', createProject);
$('#refresh-git')?.addEventListener('click', refreshGitReview);
$('#mode').addEventListener('click', () => { const modes = ['fast', 'balanced', 'deep']; state.mode = modes[(modes.indexOf(state.mode) + 1) % modes.length]; renderMode(); loadStatus(); });
$('#settings-mode').addEventListener('click', () => $('#mode').click());
$('#supervisor-toggle').addEventListener('click', async () => { try { await setSupervisorSettings({ enabled: !state.supervisor?.enabled }); } catch (error) { $('#supervisor-status').textContent = error.message; } });
$('#supervisor-enabled').addEventListener('change', async event => { try { await setSupervisorSettings({ enabled: event.currentTarget.checked }); } catch (error) { event.currentTarget.checked = !event.currentTarget.checked; $('#supervisor-status').textContent = error.message; } });
$('#supervisor-mode').addEventListener('change', async event => { try { await setSupervisorSettings({ mode: event.currentTarget.value }); } catch (error) { $('#supervisor-status').textContent = error.message; } });
$('#supervisor-budget').addEventListener('change', async event => { try { await setSupervisorSettings({ dailyBudgetUsd: Number(event.currentTarget.value) }); } catch (error) { $('#supervisor-status').textContent = error.message; } });
$('#permission-profile').addEventListener('change', async event => { try { await setSupervisorSettings({ permissionProfile: event.currentTarget.value }); } catch (error) { $('#supervisor-status').textContent = error.message; } });
$('#model-select')?.addEventListener('change', event => applyModelSelection({ model: event.currentTarget.value }));
$('#fast-model-select')?.addEventListener('change', event => applyModelSelection({ fastModel: event.currentTarget.value }));
$('#low-resource').addEventListener('change', async event => { try { await setSupervisorSettings({ lowResource: event.currentTarget.checked }); } catch (error) { event.currentTarget.checked = !event.currentTarget.checked; $('#supervisor-status').textContent = error.message; } });
$('#output-tokens').addEventListener('change', async event => { try { const value = Number(event.currentTarget.value); if (!Number.isInteger(value) || value < -1) throw new Error('Use -1 for unlimited or a positive whole-number token cap.'); await setSupervisorSettings({ outputTokens: value }); } catch (error) { $('#supervisor-status').textContent = error.message; loadStatus(); } });
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
window.qwenDesktop?.onFileDrop?.(paths => ingestAttachmentPaths(paths)).catch(error => showNotice(`File drop is unavailable: ${error.message}`));
$('#composer').addEventListener('submit', event => { event.preventDefault(); const text = prompt.value; prompt.value = ''; sendMessage(text); });
prompt.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('#composer').requestSubmit(); } });
$$('.starter').forEach(button => button.addEventListener('click', () => { prompt.value = button.textContent; prompt.focus(); }));
$('#show-add').addEventListener('click', () => $('#mcp-form').hidden = false);
$('#close-add').addEventListener('click', () => $('#mcp-form').hidden = true);
$('#cancel-add').addEventListener('click', () => $('#mcp-form').hidden = true);
$('#mcp-form [name="transport"]').addEventListener('change', event => { const http = event.currentTarget.value === 'streamable-http'; $$('.mcp-stdio-field').forEach(item => item.hidden = http); $$('.mcp-http-field').forEach(item => item.hidden = !http); });
$('#mcp-form').addEventListener('submit', async event => {
  event.preventDefault(); const form = event.currentTarget;
  let env = {}; let headers = {}; try { env = form.env.value.trim() ? JSON.parse(form.env.value) : {}; headers = form.headers.value.trim() ? JSON.parse(form.headers.value) : {}; } catch { showNotice('Environment or headers JSON is not valid.'); return; }
  const body = { name: form.name.value, transport: form.transport.value, authMode: form.authMode?.value || 'none', command: form.command.value, url: form.url.value, args: form.args.value.split('\n').map(item => item.trim()).filter(Boolean), env, headers };
  const response = await fetch('/api/mcps', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!response.ok) { const error = await response.json(); showNotice(error.error || 'Could not save this connection.'); return; }
  form.reset(); form.hidden = true; refreshMcps(); loadStatus();
});
document.addEventListener('keydown', event => {
  if (event.ctrlKey && event.key.toLowerCase() === 'k') { event.preventDefault(); newChat(); }
  if (event.ctrlKey && event.key === '`') { event.preventDefault(); toggleTerminal(); }
});
loadStatus().then(() => { refreshThreads(true); loadModelPicker(); });
setInterval(loadStatus, 5000);
