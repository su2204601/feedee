import { resolve } from "path";
import { defineConfig } from "vite";

export default defineConfig({
  root: resolve(__dirname, "frontend"),
  base: "/static/",
  build: {
    manifest: "manifest.json",
    outDir: resolve(__dirname, "static/dist"),
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: resolve(__dirname, "frontend/js/main.js"),
      },
    },
  },
  server: {
    port: 5173,
    origin: "http://localhost:5173",
  },
});
