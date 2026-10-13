import { defineConfig, devices } from "@playwright/test";

// Browser journeys (Step 09.7), run by scripts/run_step09_e2e.sh against a web app, API and worker started on the
// journey database with the real environment. Serial: the journeys build on one another (decide, generate, approve,
// publish, correct).
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3100",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 } } },
  ],
});
