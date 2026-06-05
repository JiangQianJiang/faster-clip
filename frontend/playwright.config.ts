import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:3002",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "edge",
      use: { ...devices["Desktop Edge"], channel: "msedge" },
    },
  ],
  webServer: {
    command: "npm run preview -- --host 127.0.0.1 --port 3002",
    url: "http://127.0.0.1:3002",
    reuseExistingServer: !process.env.CI,
  },
});
