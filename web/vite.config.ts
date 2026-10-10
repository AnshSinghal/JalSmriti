import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the local stack (backend/scripts/local_stack.py) serves the API, public data and local sign-in.
const target = process.env.JALSMRITI_API ?? "http://127.0.0.1:8787";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/v1": target,
      "/pub": target,
      "/local-auth": target,
      "/local-upload": target,
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks: {
          map: ["maplibre-gl"],
          react: ["react", "react-dom", "react-router-dom"],
          motion: ["framer-motion"],
        },
      },
    },
  },
});
