import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api/v1/chat": "http://127.0.0.1:8080",
      "/api/v1/incidents": "http://127.0.0.1:8080",
      "/api/v1/alerts": "http://127.0.0.1:8080",
      "/api/v1/remediations": "http://127.0.0.1:8081",
      "/api/v1/policy": "http://127.0.0.1:8081",
    },
  },
});
