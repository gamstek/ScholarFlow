import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/search': 'http://localhost:8000',
      '/review': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/stats': 'http://localhost:8000',
      '/papers': 'http://localhost:8000',
      '/ask': 'http://localhost:8000',
      '/chunks': 'http://localhost:8000',
      '/rag': 'http://localhost:8000',
      '/pipeline': 'http://localhost:8000',
    },
  },
});
