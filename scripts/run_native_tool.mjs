import { spawn } from 'node:child_process';
import { homedir } from 'node:os';
import { delimiter, join, resolve } from 'node:path';

const [tool, ...args] = process.argv.slice(2);
if (!['cargo', 'tauri'].includes(tool)) {
  console.error('Usage: node scripts/run_native_tool.mjs <cargo|tauri> [...args]');
  process.exit(2);
}

const env = { ...process.env };
const pathKey = Object.keys(env).find(key => key.toLowerCase() === 'path') || 'PATH';
const currentPath = env[pathKey] || '';
const cargoHome = env.CARGO_HOME || join(homedir(), '.cargo');
env[pathKey] = [join(cargoHome, 'bin'), currentPath].filter(Boolean).join(delimiter);

const command = tool === 'tauri' ? process.execPath : process.platform === 'win32' ? 'cargo.exe' : 'cargo';
const commandArgs = tool === 'tauri'
  ? [resolve('node_modules', '@tauri-apps', 'cli', 'tauri.js'), ...args]
  : args;

const child = spawn(command, commandArgs, { env, stdio: 'inherit', windowsHide: true });
child.once('error', error => {
  console.error(`${tool} could not start: ${error.message}`);
  console.error('Install Rust from https://rustup.rs/ and reopen your terminal.');
  process.exit(1);
});
child.once('exit', (code, signal) => {
  if (signal) {
    console.error(`${tool} stopped by ${signal}`);
    process.exit(1);
  }
  process.exit(code ?? 1);
});
