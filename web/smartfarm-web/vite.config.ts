import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

// The portal is served as static assets from nginx in production (see Dockerfile).
// `config.json` is intentionally NOT bundled: it lives in `public/` and is read at
// runtime so the NUC stream endpoint can be swapped per-environment without rebuild.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: true,
    port: 5173,
  },
  preview: {
    host: true,
    port: 4173,
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
});
