import { defineConfig } from "@playwright/test";
export default defineConfig({ testDir: "./e2e", timeout: 30000, workers: 1, use: { baseURL: "http://127.0.0.1:12861", headless: true }, webServer: { command: "node test-server.mjs", url: "http://127.0.0.1:12861", reuseExistingServer: false }, reporter: "list" });
