import { defineConfig, devices } from '@playwright/test';

// Demo mode only: fixtures, no keys or quotas, so failures mean our code broke. Live APIs are checked by hand.
const python = process.env.PYTHON ?? '.venv/bin/python';

export default defineConfig({
  testDir: 'e2e',
  timeout: process.env.CI ? 60_000 : 30_000, // CI runners have no GPU, so the Plasma shaders render in software
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: { baseURL: 'http://localhost:5173', trace: 'retain-on-failure', timezoneId: 'America/New_York', reducedMotion: 'reduce',
    // No WebGL: Plasma uses its CSS fallback instead of slow software shaders on GPU-less CI runners.
    launchOptions: { args: ['--disable-webgl', '--disable-webgl2'] } },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `${python} -m uvicorn app.main:app --app-dir backend --port 8000`,
      url: 'http://localhost:8000/api/health',
      env: { APP_MODE: 'demo', CACHE_DB: 'test-results/e2e-cache.sqlite3' },
      reuseExistingServer: false, // never reuse a dev API that might be in live mode
    },
    // The production build (vite preview reuses server.proxy for /api), not the on-the-fly dev server.
    { command: 'npx vite build && npx vite preview --port 5173 --strictPort', url: 'http://localhost:5173', timeout: 120_000, reuseExistingServer: !process.env.CI },
  ],
});
