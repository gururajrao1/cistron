import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  optimizeDeps: {
    include: ['3dmol/build/3Dmol.js'],
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
      '/presets': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
      '/simulate': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
      // Same paths as production FastAPI proxies (CORS bypass).
      '/proxy/reactome': {
        target: 'https://reactome.org',
        changeOrigin: true,
        secure: true,
        rewrite: (path) => path.replace(/^\/proxy\/reactome/, ''),
      },
      '/proxy/string-db': {
        target: 'https://string-db.org',
        changeOrigin: true,
        secure: true,
        rewrite: (path) => path.replace(/^\/proxy\/string-db/, ''),
      },
      '/reactome': {
        target: 'https://reactome.org',
        changeOrigin: true,
        secure: true,
        rewrite: (path) => path.replace(/^\/reactome/, ''),
      },
      '/string-db': {
        target: 'https://string-db.org',
        changeOrigin: true,
        secure: true,
        rewrite: (path) => path.replace(/^\/string-db/, ''),
      },
    },
  },
})
