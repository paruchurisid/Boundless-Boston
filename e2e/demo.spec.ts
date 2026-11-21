import { expect, test, type Page } from '@playwright/test';

// Follows the doc 05 demo script against demo fixtures: by default (Walk + T, 30 min door to door, $$) 8 places qualify,
// 3 of them by T only (Pinocchio's via Red, Eventide via Green-D, Earls via Orange).
const cards = (page: Page) => page.locator('article.venue-card');

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await expect(cards(page).first()).toBeVisible(); // the page searches on load
});

test('loads demo results with sources labeled demo', async ({ page }) => {
  await expect(cards(page)).toHaveCount(8);
  const sources = page.locator('.source-items');
  for (const name of ['Google Places', 'MBTA', 'Boston Open Data']) await expect(sources).toContainText(name);
  await expect(sources.locator('small', { hasText: 'demo' }).first()).toBeVisible();
  await expect(cards(page).first().locator('.score strong')).toHaveText(/^\d+$/);
  // T-only places show their line pill (e.g. Red to Harvard).
  await expect(cards(page).filter({ hasText: "Pinocchio's" }).locator('.line-pill')).toHaveText(/Red/);
});

test('Why this? shows the full score breakdown, including unused parts', async ({ page }) => {
  const first = cards(page).first();
  await first.getByRole('button', { name: /Why this/ }).click();
  const breakdown = first.locator('.breakdown');
  for (const part of ['momentum', 'quality', 'reach', 'events', 'weather']) await expect(breakdown).toContainText(part);
  await expect(breakdown).toContainText('not used (event data unavailable)');
});

test('rain lowers the outdoor park and lifts indoor places', async ({ page }) => {
  // Weather is ~11% of the score, so rain shifts scores without necessarily flipping the order.
  const fit = (name: string) => cards(page).filter({ has: page.getByRole('heading', { name }) }).locator('.score strong');
  const parkBefore = Number(await fit('Boston Public Garden').textContent());
  const phoBefore = Number(await fit('Pho Pasteur').textContent());
  await page.getByRole('button', { name: /Clear skies/ }).click();
  await page.getByRole('button', { name: /Find my night/ }).click();
  await expect(page.getByRole('button', { name: /Rain check/ })).toBeVisible();
  await expect.poll(async () => Number(await fit('Boston Public Garden').textContent())).toBeLessThan(parkBefore);
  await expect.poll(async () => Number(await fit('Pho Pasteur').textContent())).toBeGreaterThan(phoBefore);
});

test('a too-strict search shows the exact empty state', async ({ page }) => {
  // The only $ pizza place (Pinocchio's) is T-only, so walk-only + 10 min leaves nothing.
  await page.getByPlaceholder(/cheap ramen/).fill('pizza');
  await page.getByRole('button', { name: '$', exact: true }).click();
  await page.getByRole('button', { name: 'Walk only' }).click();
  await page.locator('input[type=range]').fill('10');
  await page.getByRole('button', { name: /Find my night/ }).click();
  await expect(page.getByText('Nothing open and reachable at that time. Try an earlier hour or a higher budget.')).toBeVisible();
  await expect(cards(page)).toHaveCount(0);
});

test('neighborhood notes open with 311 data', async ({ page }) => {
  await page.getByRole('button', { name: /Neighborhood notes/ }).click();
  const modal = page.locator('.modal');
  await expect(modal).toContainText('NEIGHBORHOOD SNAPSHOT');
  await expect(modal).toContainText('311 requests');
  await modal.locator('.modal-close').click();
  await expect(modal).toHaveCount(0);
});
