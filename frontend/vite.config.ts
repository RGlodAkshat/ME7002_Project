import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 8082,
    strictPort: true,
    proxy: {
      '/api': loadEnv(mode, '.', 'API_PROXY_').API_PROXY_TARGET || 'http://127.0.0.1:8083',
      '/mcp': loadEnv(mode, '.', 'API_PROXY_').API_PROXY_TARGET || 'http://127.0.0.1:8083',
    },
  },
}));
