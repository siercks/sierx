import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  globalTimeout: 600000,
  testDir: 'test/browser',
  fullyParallel: false,
  workers: 1,
  timeout: 60000,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: process.env.SIERX_TEST_URL,
    ignoreHTTPSErrors: true,
    launchOptions: { timeout: 20000 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    ...(process.env.SIERX_CHROMIUM_ONLY === '1'
      ? []
      : [{ name: 'firefox', use: { ...devices['Desktop Firefox'] } }]),
    ...(process.env.SIERX_WEBKIT === '1'
      ? [{ name: 'webkit', use: { ...devices['Desktop Safari'] } }]
      : []),
  ],
});
