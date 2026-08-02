import { cp, mkdir, rm, stat } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const extensionRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const source = resolve(extensionRoot, 'webview-dist');
const target = resolve(extensionRoot, '..', 'tapl', 'taplctl', '_viewer');
const required = [
  resolve(source, 'src', 'webview', 'index.html'),
  resolve(source, 'assets', 'index.js'),
  resolve(source, 'assets', 'index.css')
];

for (const file of required) {
  const info = await stat(file);
  if (!info.isFile()) {
    throw new Error(`Viewer build output is missing: ${file}`);
  }
}

await mkdir(dirname(target), { recursive: true });
await rm(target, { recursive: true, force: true });
await cp(source, target, { recursive: true });

process.stdout.write(`Synced browser viewer assets to ${target}\n`);
