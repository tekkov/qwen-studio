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
