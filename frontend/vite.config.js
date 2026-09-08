import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    // Allow access through tunnels like ngrok (e.g. https://xxxx.ngrok-free.app)
    allowedHosts: true,
    // One public URL serves everything: the dev server proxies API + WebSocket
    // traffic to the FastAPI backend, so tunneling port 3000 exposes the whole app.
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        ws: true, // proxies /api/ws/notifications WebSocket upgrades too
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
