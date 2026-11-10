import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(async () => ({
  // The Tailwind plugin is ESM-only; keep this package's extension host in CommonJS.
  plugins: [react(), (await import('@tailwindcss/vite')).default()],
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
