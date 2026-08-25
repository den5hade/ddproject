import { defineConfig } from "@playwright/test";

/*
 * E2E suite lives in tests/e2e (populated in M7).
 * Requires the full dev stack: API on :8000, web preview/dev on :5173.
 */
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
  },
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
