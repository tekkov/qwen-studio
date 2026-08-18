import { copyFileSync, mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const output = join(root, 'frontend-dist');
const files = [
  'index.html', 'bootstrap.js', 'app.js', 'icons.js', 'tauri-bridge.js',
  'style.css', 'run-status.css', 'projects.css', 'project-tree.css',
  'terminal.css', 'product-shell.css'
];

rmSync(output, { recursive: true, force: true });
mkdirSync(output, { recursive: true });
for (const file of files) copyFileSync(join(root, file), join(output, file));
console.log(`Prepared ${files.length} frontend assets in frontend-dist.`);
