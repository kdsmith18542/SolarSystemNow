import { defineConfig } from '@playwright/test';

/**
 * Browser smoke tests for the built web bundle.
 *
 * Uses the system Chrome channel (installed by default on GitHub runners and
 * most desktops) so no Playwright browser download is required.
 * The FastAPI server is started automatically with an isolated data directory
 * so first-run seeding gives the UI deterministic content.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: 'http://127.0.0.1:8199',
    channel: 'chrome',
    headless: true,
  },
  webServer: {
    command: 'python3 -m ssnow_web.server --port 8199',
    url: 'http://127.0.0.1:8199/api/health',
    reuseExistingServer: !process.env.CI,
    timeout: 90_000,
    env: {
      SSNOW_DATA_DIR: process.env.SSNOW_E2E_DATA_DIR ?? '/tmp/ssnow-e2e-data',
      SSNOW_CONFIG_DIR: process.env.SSNOW_E2E_CONFIG_DIR ?? '/tmp/ssnow-e2e-config',
      SSNOW_CACHE_DIR: process.env.SSNOW_E2E_CACHE_DIR ?? '/tmp/ssnow-e2e-cache',
      // Exercise the browser write-token flow; public upstream GETs stay open.
      SSNOW_API_TOKEN: process.env.SSNOW_E2E_TOKEN ?? 'e2e-token',
    },
  },
});
