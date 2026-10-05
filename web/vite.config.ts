import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The API server: `poetry run quant-web serve` (default port 8765).
const api = process.env.QUANT_WEB_API ?? 'http://127.0.0.1:8765';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': { target: api, changeOrigin: true } },
  },
  build: {
    chunkSizeWarningLimit: 2500,
  },
});
