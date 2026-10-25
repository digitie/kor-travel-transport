import { defineConfig, devices } from "@playwright/test";

// 운영 API를 사용하지 않는 공항 주차장 전체 조회 회귀다.
const touchFlows = /주차장 네 뷰.*375px|375px 달력/;
export default defineConfig({
  testDir: "./e2e",
  testMatch: "parking-admin.spec.ts",
  timeout: 60_000,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["json", { outputFile: "test-results/parking-ui.json" }]],
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:12305", timezoneId: "Asia/Seoul", trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "chromium-touch", grep: touchFlows, use: { ...devices["Pixel 7"] } },
    { name: "firefox-touch", grep: touchFlows, use: { ...devices["Desktop Firefox"], hasTouch: true, isMobile: false } },
  ],
});
