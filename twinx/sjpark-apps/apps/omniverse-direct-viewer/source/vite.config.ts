import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    assetsDir: '',
    chunkSizeWarningLimit: 800,
  },
  server: {
    host: '0.0.0.0',
    port: 5174,
  },
  preview: {
    host: '0.0.0.0',
    port: 4174,
  },
});
