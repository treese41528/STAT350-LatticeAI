import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { mockApiPlugin } from "./mock/plugin";

/**
 * Dev modes:
 *   npm run dev          -> vite --mode mock   (in-process mock API, no backend needed)
 *   npm run dev:backend  -> vite               (proxies /api to the FastAPI backend on :8100)
 *   VITE_MOCK=1 vite     -> also enables the mock, regardless of mode
 *
 * Build emits straight into the backend's static dir so FastAPI can serve the SPA.
 */
export default defineConfig(({ mode }) => {
  const useMock = mode === "mock" || process.env.VITE_MOCK === "1";
  return {
    plugins: [react(), ...(useMock ? [mockApiPlugin()] : [])],
    server: {
      proxy: useMock
        ? undefined
        : {
            "/api": {
              target: "http://localhost:8100",
              changeOrigin: true,
            },
          },
    },
    build: {
      outDir: "../backend/app_static",
      emptyOutDir: true,
      rollupOptions: {
        output: {
          manualChunks: {
            katex: ["katex", "rehype-katex"],
          },
        },
      },
    },
  };
});
