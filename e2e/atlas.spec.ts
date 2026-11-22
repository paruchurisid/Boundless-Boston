import { expect, test } from '@playwright/test';

test('atlas remains searchable without WebGL and restores the planner', async ({ page }) => {
  await page.goto('/#atlas');
  await expect(page.getByRole('heading', { name: 'Boston, mapped.', exact: true })).toBeVisible();
  await expect(page.getByRole('status').filter({ hasText: 'Interactive map unavailable' })).toBeVisible();
  await expect(page.locator('#campus option')).toHaveCount(20);
  await page.getByLabel('Search campuses').fill('boston');
  await expect(page.locator('#campus option')).toHaveCount(4);
  await page.getByLabel('Fly to a university').selectOption({ label: 'Boston University' });
  await expect(page.locator('#selection')).toContainText('Boston University');
  await page.getByLabel('Search campuses').fill('not-a-campus');
  await expect(page.locator('#matches')).toContainText('No campuses found');
  await page.getByRole('button', { name: 'River view' }).click();
  await expect(page.locator('#campus option')).toHaveCount(20);
  await expect(page.getByRole('button', { name: '2D view' })).toBeDisabled();
  await page.getByRole('link', { name: 'Plan', exact: true }).click();
  await expect(page.getByRole('button', { name: /Find my night/ })).toBeVisible();
  await expect(page.locator('#campus')).toHaveCount(0);
  await page.getByRole('link', { name: 'Map', exact: true }).click();
  await expect(page.locator('#campus option')).toHaveCount(20);
});

test('atlas controls fit a narrow viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/#atlas');
  await expect(page.getByLabel('Search campuses')).toBeVisible();
  await page.getByLabel('Fly to a university').selectOption({ label: 'MIT' });
  await expect(page.locator('#selection')).toContainText('MIT');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
