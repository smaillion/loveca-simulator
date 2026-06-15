var _a, _b;
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
var env = (_a = globalThis.process) === null || _a === void 0 ? void 0 : _a.env;
export default defineConfig({
    base: (_b = env === null || env === void 0 ? void 0 : env.VITE_BASE_PATH) !== null && _b !== void 0 ? _b : "/",
    plugins: [react()],
    server: {
        port: 5173,
        proxy: {
            "/api": "http://127.0.0.1:8765",
        },
    },
});
