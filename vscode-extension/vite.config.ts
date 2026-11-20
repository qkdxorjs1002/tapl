import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

export default defineConfig(async () => ({
  // The Tailwind plugin is ESM-only; keep this package's extension host in CommonJS.
  plugins: [
    react(),
    (await import('@tailwindcss/vite')).default(),
    {
      name: 'tapl-driver-license',
      generateBundle() {
        this.emitFile({
          type: 'asset',
          fileName: 'assets/driver-license.txt',
          source: readFileSync(resolve(__dirname, 'node_modules/driver.js/license'))
        });
      }
    }
  ],
  build: {
    outDir: 'webview-dist',
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      input: 'src/webview/index.html',
      output: {
        entryFileNames: 'assets/index.js',
        chunkFileNames: 'assets/[name].js',
        assetFileNames: 'assets/[name][extname]'
      }
    }
  }
}));
