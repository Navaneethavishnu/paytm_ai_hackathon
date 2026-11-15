import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The browser only ever talks to Vite; /api/* is forwarded to FastAPI.
// Same origin => no CORS setup needed, and phones on the LAN work too.
const backend = process.env.API_TARGET || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // reachable at http://<laptop-LAN-IP>:5173
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") },
    },
  },
});
