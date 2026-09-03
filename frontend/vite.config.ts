import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
// Цель прокси /api переопределяется переменной VITE_PROXY_TARGET —
// удобно, когда бэкенд поднят не на 8000 (второй стенд, отладка).
const apiTarget = process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': apiTarget,
    },
  },
})
