import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

declare const process: { env: Record<string, string | undefined> };

export default defineConfig({
  plugins: [react()],
  build: {
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: { manualChunks: { fluent: ["@fluentui/react-components"], icons: ["@fluentui/react-icons"], react: ["react", "react-dom", "react-router-dom", "@tanstack/react-query"] } },
    },
  },
  server: {
    // Preview hosts reach the app through one origin; /entra proxies the local mock Entra ID for that case.
    // In Codespaces listen on all interfaces so the forwarded port is detected and opened.
    host: process.env.CODESPACES ? true : undefined,
    allowedHosts: ["localhost", ".devinapps.com", ".app.github.dev"],
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: false, xfwd: true },
      "/entra": { target: "http://localhost:8081", changeOrigin: true },
    },
  },
});
