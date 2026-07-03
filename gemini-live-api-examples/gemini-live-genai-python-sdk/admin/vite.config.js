import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Served by FastAPI under /admin/ (StaticFiles + SPA fallback). In dev, proxy
// the API to the running FastAPI (uvicorn on :8000).
export default defineConfig({
  base: '/admin/',
  plugins: [react()],
  build: { outDir: 'dist', emptyOutDir: true },
  server: {
    port: 5174,
    proxy: { '/api': 'http://localhost:8000' },
  },
})
