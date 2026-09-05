import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Proxy `/api/*` to the local backend so the app is same-origin.
//
// Why this exists: `VITE_API_BASE_URL` is read via `import.meta.env` in
// src/api/client.js, and Vite substitutes that statically **at build
// time**. With an absolute URL baked in, sharing a demo over a tunnel
// meant rebuilding whenever the tunnel URL changed, and exposing two
// ports (frontend + backend) instead of one. With `VITE_API_BASE_URL=/api`
// and this proxy, requests stay same-origin: tunnel :5173 alone and the
// API rides along, with no rebuild and no CORS involvement.
//
// Configured for `preview` as well as `dev` on purpose -- `/api` is now
// the default in .env.example, so `npm run build && npm run preview`
// would 404 on every request without it. A plain static host (no proxy
// in front) would need an absolute VITE_API_BASE_URL instead; there is
// no such host any more (CLAUDE.md §7 -- runs locally only).
const apiProxy = {
  '/api': {
    target: 'http://localhost:8000',
    changeOrigin: true,
    rewrite: (path) => path.replace(/^\/api/, ''),
  },
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: { proxy: apiProxy },
  preview: { proxy: apiProxy },
})
