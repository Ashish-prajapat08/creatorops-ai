import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  timeout: 90000,
  expect: { timeout: 20000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:3001",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "../backend/.venv/bin/python ../scripts/e2e_server.py",
      url: "http://127.0.0.1:8001/health/ready",
      gracefulShutdown: { signal: "SIGTERM", timeout: 30000 },
      reuseExistingServer: false,
      timeout: 60000,
    },
    {
      command: "npm run dev -- --port 3001",
      url: "http://127.0.0.1:3001/login",
      reuseExistingServer: false,
      timeout: 90000,
      env: {
        NEXT_PUBLIC_API_URL: "http://127.0.0.1:8001",
        NEXT_PUBLIC_TEST_MODE: "true",
      },
    },
  ],
});
