import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 8082,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:8083',
      '/mcp': 'http://127.0.0.1:8083',
    },
  },
});
