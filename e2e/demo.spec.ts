import { expect, test, type Page } from '@playwright/test';

// Follows the doc 05 demo script against demo fixtures: 5 open, in-budget places within walking range, plus 3 reached by the T
// (Red Line to Harvard, Green Line D to Fenway, Orange Line to Assembly) until their demo last trains around 12:40 AM.
const cards = (page: Page) => page.locator('article.venue-card');
const walkCards = (page: Page) => cards(page).filter({ hasNot: page.locator('.transit-row') });
const tCards = (page: Page) => cards(page).filter({ has: page.locator('.transit-row') });

// The API only accepts the next 24 hours, so use the next Boston occurrence of a wall-clock time (at least 15 s away, so it is never past or more than 24 h out),
// never a fixed date. The browser timezone is pinned to America/New_York in playwright.config.ts.
function nextBoston(hhmm: string): string {
  const fmt = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  const wall = (d: Date) => { const p = Object.fromEntries(fmt.formatToParts(d).map((x) => [x.type, x.value])); return { day: `${p.year}-${p.month}-${p.day}`, time: `${p.hour}:${p.minute}` }; };
  const now = Date.now();
  const soon = wall(new Date(now + 15_000));
  const today = wall(new Date(now));
  if (`${today.day}T${hhmm}` > `${soon.day}T${soon.time}`) return `${today.day}T${hhmm}`;
  return `${wall(new Date(now + 24 * 3600_000)).day}T${hhmm}`;
}

async function searchAt(page: Page, hhmm: string) {
  await page.locator('input[type=datetime-local]').fill(nextBoston(hhmm));
  await page.getByRole('button', { name: /Find my night/ }).click();
}

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await expect(cards(page).first()).toBeVisible(); // the page searches on load
});

test('loads demo results with sources labeled demo', async ({ page }) => {
  await expect(walkCards(page)).toHaveCount(5); // the T places depend on the time of day, so they are tested below
  const sources = page.locator('.source-items');
  for (const name of ['Google Places', 'MBTA', 'Boston Open Data']) await expect(sources).toContainText(name);
  await expect(sources.locator('small', { hasText: 'demo' }).first()).toBeVisible();
  await expect(cards(page).first().locator('.score strong')).toHaveText(/^\d+$/);
});

test('Why this? shows the full score breakdown, including unused parts', async ({ page }) => {
  const first = cards(page).first();
  await first.getByRole('button', { name: /Why this/ }).click();
  const breakdown = first.locator('.breakdown');
  for (const part of ['momentum', 'quality', 'reach', 'events', 'weather']) await expect(breakdown).toContainText(part);
  await expect(breakdown).toContainText('× 0.'); // each part shows its weight
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
  await page.getByRole('button', { name: '$', exact: true }).click();
  await page.locator('input[type=range]').fill('5');
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

test('Walk + T adds places by train with the line and the last train home', async ({ page }) => {
  await searchAt(page, '20:00');
  await expect(tCards(page)).toHaveCount(3);
  const harvard = cards(page).filter({ has: page.getByRole('heading', { name: "Pinocchio's Pizza & Subs" }) });
  await expect(harvard.locator('.line-pill')).toHaveText('Red Line');
  await expect(harvard).toContainText('22 min by T');
  await expect(harvard.locator('.last-train')).toContainText('Last train back 12:47 AM');
});

test('Walk only hides the T places', async ({ page }) => {
  await page.getByRole('button', { name: 'Walk only' }).click();
  await searchAt(page, '20:00');
  await expect(page.getByRole('button', { name: 'Walk only' })).toHaveAttribute('aria-pressed', 'true');
  await expect(tCards(page)).toHaveCount(0);
  await expect(cards(page)).toHaveCount(5);
});

test('after the last train, far places drop out', async ({ page }) => {
  await searchAt(page, '23:50');
  await expect(tCards(page)).toHaveCount(0);
});

test('a nearby game shows on the card and lifts its events score', async ({ page }) => {
  await searchAt(page, '20:00'); // demo Bruins game at TD Garden, 7 pm; Regina Pizzeria is in the North End
  const regina = cards(page).filter({ has: page.getByRole('heading', { name: 'Regina Pizzeria' }) });
  await expect(regina.locator('.event-row')).toContainText('Bruins vs Demo Rivals (demo) at TD Garden, 7:00 PM');
  await expect(cards(page).filter({ has: page.getByRole('heading', { name: 'Boston Public Garden' }) }).locator('.event-row')).toHaveCount(0);
});
