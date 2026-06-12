import { defineConfig } from "@playwright/test";

const environment = (
  globalThis as typeof globalThis & {
    process?: { env?: Record<string, string | undefined> };
  }
).process?.env;

export default defineConfig({
  testDir: "./e2e",
  use: {
    baseURL: environment?.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:8765",
    screenshot: "only-on-failure",
  },
});
