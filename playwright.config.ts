import { defineConfig, devices } from '@playwright/test';

// Demo mode only: fixtures, no keys or quotas, so failures mean our code broke. Live APIs are checked by hand.
const python = process.env.PYTHON ?? '.venv/bin/python';

export default defineConfig({
  testDir: 'e2e',
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: { baseURL: 'http://localhost:5173', trace: 'retain-on-failure', timezoneId: 'America/New_York' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `${python} -m uvicorn app.main:app --app-dir backend --port 8000`,
      url: 'http://localhost:8000/api/health',
      env: { APP_MODE: 'demo', CACHE_DB: 'test-results/e2e-cache.sqlite3' },
      reuseExistingServer: false, // never reuse a dev API that might be in live mode
    },
    { command: 'npx vite --port 5173 --strictPort', url: 'http://localhost:5173', reuseExistingServer: !process.env.CI },
  ],
});
