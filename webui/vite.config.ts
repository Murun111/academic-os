import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Set VITE_API_MODE=real to talk to the FastAPI backend; requests are
// proxied so the SPA and backend share an origin in dev, matching prod
// where FastAPI serves the built SPA at /.
//
// `build` outputs to webui/dist (its OWN dir) with assets under `_app`. The
// FastAPI backend serves this dir directly (see FRONTEND_BUILD in backend/app.py),
// decoupled from the SvelteKit build in frontend/build so `bin/start.sh --build`
// / reboots can't overwrite the React UI. HashRouter keeps routing client-side.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: 'dist',
    assetsDir: '_app',
    emptyOutDir: true,
  },
  server: {
    port: Number(process.env.PORT) || 5173,
    proxy: {
      '/api': { target: 'http://localhost:7878', changeOrigin: true },
      '/ws': { target: 'ws://localhost:7878', ws: true },
    },
  },
})
