import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const env = (globalThis as unknown as {
  process?: { env?: Record<string, string | undefined> };
}).process?.env;

export default defineConfig({
  base: env?.VITE_BASE_PATH ?? "/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8765",
    },
  },
});
