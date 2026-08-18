const { app, BrowserWindow, dialog, shell, ipcMain } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');
const net = require('net');
const fs = require('fs');

let serverProcess;
let mainWindow;
let restartTimer;
let quitting = false;
let port;
let logPath;
let ollamaProcess;
function log(message) { try { if (logPath) fs.appendFileSync(logPath, `${new Date().toISOString()} ${message}\n`); } catch (_) {} }

function runtimeRoot() {
  return app.isPackaged ? path.join(process.resourcesPath, 'app.asar.unpacked') : __dirname;
}

function pythonRuntime() {
  const configured = process.env.QWEN_PYTHON;
  if (configured) return { command: configured, prefix: [] };
  if (process.platform === 'win32') {
    const launcher = path.join(process.env.SystemRoot || 'C:\\Windows', 'py.exe');
    if (fs.existsSync(launcher)) return { command: launcher, prefix: ['-3'] };
    return { command: 'python', prefix: [] };
  }
  return { command: 'python3', prefix: [] };
}

function localEnvironment() {
  const values = {};
  const candidates = [path.join(runtimeRoot(), '.env'), path.join(app.getPath('userData'), '.env')];
  for (const candidate of candidates) {
    try {
      for (const line of fs.readFileSync(candidate, 'utf8').split(/\r?\n/)) {
        const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
        if (!match || match[1] in values) continue;
        values[match[1]] = match[2].replace(/^(['"])(.*)\1$/, '$2');
      }
    } catch (_) {}
  }
  return values;
}

function ollamaCommand() {
  const configured = process.env.OLLAMA_COMMAND;
  if (configured && fs.existsSync(configured)) return configured;
  const candidates = [
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Ollama', 'ollama.exe'),
    path.join(process.env.ProgramFiles || '', 'Ollama', 'ollama.exe'),
    'ollama'
  ];
  return candidates.find(candidate => candidate === 'ollama' || fs.existsSync(candidate)) || null;
}

function ollamaRequest(pathname, payload = null, timeout = 5000) {
  return new Promise((resolve, reject) => {
    const body = payload == null ? null : Buffer.from(JSON.stringify(payload));
    const request = http.request({ hostname: '127.0.0.1', port: 11434, path: pathname, method: body ? 'POST' : 'GET', timeout, headers: body ? { 'Content-Type': 'application/json', 'Content-Length': body.length } : {} }, response => {
      const chunks = [];
      response.on('data', chunk => chunks.push(chunk));
      response.on('end', () => {
        if (response.statusCode < 200 || response.statusCode >= 300) { reject(new Error(`Ollama returned HTTP ${response.statusCode}`)); return; }
        try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}')); } catch { resolve({}); }
      });
    });
    request.on('timeout', () => request.destroy(new Error('Ollama startup timed out.')));
    request.on('error', reject);
    if (body) request.write(body);
    request.end();
  });
}

async function ensureOllamaRuntime() {
  const environment = localEnvironment();
  const model = environment.QWEN_MODEL || process.env.QWEN_MODEL || 'qwen3.8:27b';
  try {
    await ollamaRequest('/api/tags');
  } catch {
    const command = ollamaCommand();
    if (!command) { log('Ollama was not found. Install Ollama or set OLLAMA_COMMAND.'); return; }
    log(`starting Ollama from ${command}`);
    try {
      ollamaProcess = spawn(command, ['serve'], { windowsHide: true, detached: true, stdio: 'ignore', env: { ...environment, ...process.env } });
      ollamaProcess.unref();
    } catch (error) { log(`Ollama startup failed: ${error.message}`); return; }
    for (let attempt = 0; attempt < 60; attempt++) {
      try { await ollamaRequest('/api/tags', null, 1500); break; } catch { await new Promise(resolve => setTimeout(resolve, 500)); }
    }
  }
  try {
    const tags = await ollamaRequest('/api/tags');
    const installed = (tags.models || []).some(item => item.name === model || item.model === model);
    if (!installed) { log(`Ollama is ready, but model ${model} is not installed.`); return; }
    log(`warming Ollama model ${model}`);
    await ollamaRequest('/api/generate', { model, prompt: 'Ready.', stream: false, keep_alive: '30m', options: { num_predict: 1 } }, 180000);
    log(`Ollama model ${model} is warm`);
  } catch (error) { log(`Ollama model preflight skipped: ${error.message}`); }
}

function isReady() {
  return new Promise(resolve => {
    if (!port) { resolve(false); return; }
    const request = http.get(`http://127.0.0.1:${port}/api/status`, response => {
      response.resume();
      resolve(response.statusCode === 200);
    });
    request.on('error', () => resolve(false));
    request.setTimeout(500, () => { request.destroy(); resolve(false); });
  });
}

function choosePort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.unref();
    probe.on('error', reject);
    probe.listen(0, '127.0.0.1', () => {
      const selected = probe.address().port;
      probe.close(() => resolve(selected));
    });
  });
}

async function startServer() {
  log('starting local server');
  if (serverProcess && await isReady()) return;
  port = await choosePort();
  const python = pythonRuntime();
  const root = runtimeRoot();
  serverProcess = spawn(python.command, [...python.prefix, path.join(root, 'server.py')], {
    cwd: root,
    env: { ...localEnvironment(), ...process.env, QWEN_PORT: String(port) },
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe']
  });
  serverProcess.stdout.on('data', data => log(`python: ${String(data).trim()}`));
  serverProcess.stderr.on('data', data => log(`python stderr: ${String(data).trim()}`));
  serverProcess.on('error', error => log(`python error: ${error.message}`));
  serverProcess.on('exit', (code, signal) => {
    log(`python exit: code=${code} signal=${signal}`);
    serverProcess = null;
    if (!quitting) scheduleServerRestart();
  });
  for (let attempt = 0; attempt < 30; attempt++) {
    if (await isReady()) return;
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  throw new Error('The local Qwen server did not start. Make sure Python and Ollama are installed.');
}

function scheduleServerRestart() {
  if (restartTimer || quitting) return;
  log('scheduling local server restart');
  restartTimer = setTimeout(async () => {
    restartTimer = null;
    try {
      await startServer();
      log('local server restarted');
      if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.reload();
    } catch (error) {
      log(`restart failure: ${error.message}`);
      scheduleServerRestart();
    }
  }, 1500);
}

async function createWindow() {
  logPath = path.join(app.getPath('userData'), 'qwen-startup.log');
  log('desktop app ready');
  try {
    await ensureOllamaRuntime();
    await startServer();
  } catch (error) {
    log(`startup failure: ${error.stack || error.message}`);
    dialog.showErrorBox('Qwen Local Agent', error.message);
    app.quit();
    return;
  }
  mainWindow = new BrowserWindow({
    width: 1220,
    height: 860,
    minWidth: 760,
    minHeight: 620,
    backgroundColor: '#0b0c0a',
    title: 'Qwen Studio',
    icon: path.join(__dirname, 'qwen-studio-icon.png'),
    webPreferences: { contextIsolation: true, sandbox: true, preload: path.join(__dirname, 'preload.js') }
  });
  mainWindow.loadURL(`http://127.0.0.1:${port}`);
  mainWindow.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' }; });
}

app.whenReady().then(() => {
  ipcMain.handle('choose-project-folder', async () => {
    const result = await dialog.showOpenDialog(mainWindow, { title: 'Link a project folder', properties: ['openDirectory', 'createDirectory'] });
    return result.canceled ? null : result.filePaths[0];
  });
  ipcMain.handle('choose-project-parent', async () => {
    const result = await dialog.showOpenDialog(mainWindow, { title: 'Choose where to create the project', properties: ['openDirectory', 'createDirectory'] });
    return result.canceled ? null : result.filePaths[0];
  });
  ipcMain.handle('choose-attachments', async () => {
    const result = await dialog.showOpenDialog(mainWindow, {
      title: 'Attach files to Qwen',
      properties: ['openFile', 'multiSelections'],
      filters: [
        { name: 'Images and videos', extensions: ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'mp4', 'mov', 'mkv', 'webm', 'avi', 'm4v'] },
        { name: 'Code and text', extensions: ['txt', 'md', 'json', 'csv', 'py', 'js', 'ts', 'tsx', 'jsx', 'html', 'css', 'xml', 'yaml', 'yml', 'toml', 'sql', 'ps1'] },
        { name: 'All files', extensions: ['*'] }
      ]
    });
    return result.canceled ? [] : result.filePaths;
  });
  return createWindow();
});
app.on('window-all-closed', () => { quitting = true; if (restartTimer) clearTimeout(restartTimer); if (serverProcess) serverProcess.kill(); if (process.platform !== 'darwin') app.quit(); });
app.on('before-quit', () => { quitting = true; if (restartTimer) clearTimeout(restartTimer); if (serverProcess) serverProcess.kill(); });
