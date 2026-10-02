import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // The backend only allows the CORS origins http://localhost:5173 and
    // http://127.0.0.1:5173. Vite's default behaviour is to silently fall back
    // to 5174 when 5173 is busy, which would fail CORS and show up as a
    // confusing network error. strictPort makes the dev server fail loudly
    // instead, so the port can be freed and the mismatch avoided.
    port: 5173,
    strictPort: true,
  },
})