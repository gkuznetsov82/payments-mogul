import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

// Build output is placed inside engine/world_builder/ui/ so the FastAPI
// service (engine.world_builder.service) serves the SPA directly. Spec 74
// §Architecture: standalone World Builder app surface.
//
// `base: "/ui/"` aligns asset URLs with the StaticFiles mount in
// engine/world_builder/service.py (`app.mount("/ui", ...)`). Without it the
// built index.html references /assets/* which 404s because the asset
// directory is only exposed under /ui/.
export default defineConfig({
  base: "/ui/",
  plugins: [react()],
  build: {
    outDir: resolve(__dirname, "..", "engine", "world_builder", "ui"),
    emptyOutDir: true,
  },
  server: {
    port: 5174,
    proxy: {
      "/validate": "http://127.0.0.1:8090",
      "/normalize": "http://127.0.0.1:8090",
      "/analyze": "http://127.0.0.1:8090",
      "/health": "http://127.0.0.1:8090",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/__tests__/setup.ts"],
    css: false,
  },
});
