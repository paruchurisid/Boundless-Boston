import { expect, test } from '@playwright/test';
  test.use({ launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] } });
  test('initializes a map and switches perspective', async ({ page }) => {
    await page.route('https://tiles.openfreemap.org/styles/liberty', route => route.fulfill({ json: {
      version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#cadbdc' } }]
    } }));
    await page.goto('/#atlas');
    await expect(page.locator('#status')).toHaveText('Map loaded; building layer unavailable');
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible();
    await page.getByRole('button', { name: '2D view', exact: true }).click();
    await expect(page.getByRole('button', { name: '3D view', exact: true })).toBeVisible();
    await page.getByLabel('Fly to a university').selectOption({ label: 'Harvard' });
    await expect(page.locator('#selection')).toContainText('Harvard');
    await expect(page.getByRole('button', { name: '2D view', exact: true })).toBeVisible();
  });
