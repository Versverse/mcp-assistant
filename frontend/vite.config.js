import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const backend = process.env.MCP_BACKEND_URL || 'http://127.0.0.1:8000'
const proxy = { '/health': backend, '/chat': backend }

export default defineConfig({
  plugins: [vue()],
  server: { proxy },
  preview: { proxy },
  optimizeDeps: {
    include: ['markdown-it']
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    },
  },
})
