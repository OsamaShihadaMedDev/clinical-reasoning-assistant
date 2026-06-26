import path from "path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    // Proxy the FastAPI backend so the frontend is developed same-origin — mirrors
    // how demo.html is served by FastAPI directly (no CORS). The SSE route
    // (/api/triage/stream) must NOT be buffered, so disable proxy buffering and
    // keep the connection alive for the long-lived event stream.
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
})
