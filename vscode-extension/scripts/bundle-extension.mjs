import { rm } from 'node:fs/promises';
import { build } from 'esbuild';

await rm('out/node_modules', { recursive: true, force: true });

await build({
  entryPoints: ['src/extension.ts'],
  bundle: true,
  minify: true,
  platform: 'node',
  format: 'cjs',
  target: 'node18',
  external: ['vscode'],
  outfile: 'out/extension.js',
  sourcemap: true
});

// Ajv embeds these module names in validators compiled at runtime, so esbuild
// cannot discover them from the static import graph. Keep tiny bundled shims at
// the paths Node resolves relative to out/extension.js.
await build({
  entryPoints: [
    'node_modules/ajv/dist/runtime/validation_error.js',
    'node_modules/ajv/dist/runtime/uri.js',
    'node_modules/ajv/dist/runtime/ucs2length.js',
    'node_modules/ajv/dist/runtime/equal.js',
    'node_modules/ajv-formats/dist/formats.js'
  ],
  bundle: true,
  minify: true,
  platform: 'node',
  format: 'cjs',
  target: 'node18',
  outbase: 'node_modules',
  outdir: 'out/node_modules'
});
