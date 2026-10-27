import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Built into the FastAPI static dir and served at /app. In dev, API calls go to uvicorn on :8000.
const api = ['/me', '/cases', '/models', '/provider', '/synthetic', '/health']
export default defineConfig({
  base: '/app/',
  plugins: [react(), tailwindcss()],
  build: { outDir: '../app/static/web', emptyOutDir: true },
  server: { proxy: Object.fromEntries(api.map((p) => [p, 'http://127.0.0.1:8000'])) },
})
