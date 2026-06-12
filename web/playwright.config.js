var _a, _b;
import { defineConfig } from "@playwright/test";
var environment = (_a = globalThis.process) === null || _a === void 0 ? void 0 : _a.env;
export default defineConfig({
    testDir: "./e2e",
    use: {
        baseURL: (_b = environment === null || environment === void 0 ? void 0 : environment.PLAYWRIGHT_BASE_URL) !== null && _b !== void 0 ? _b : "http://127.0.0.1:8765",
        screenshot: "only-on-failure",
    },
});
