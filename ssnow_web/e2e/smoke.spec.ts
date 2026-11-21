import { expect, test } from '@playwright/test';

// ?nosse=1 keeps a long-lived SSE connection from holding the page busy under
// test; the stream itself is covered by the API unit tests.

test('dashboard renders hero, nav and seeded events', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (err) => errors.push(String(err)));

  await page.goto('/?nosse=1');
  await expect(page.getByText('Solar System Now')).toBeVisible();
  await expect(page.getByText('COMPOSITE THREAT')).toBeVisible();
  await expect(page.getByText('RECENT EVENTS')).toBeVisible();
  // First-run seeding guarantees real fixture events in a fresh data dir.
  await expect(page.getByText(/earthquake/i).first()).toBeVisible({ timeout: 15_000 });

  expect(errors, `uncaught page errors: ${errors.join('; ')}`).toEqual([]);
});

test('tabs navigate to Events and Sun views', async ({ page }) => {
  await page.goto('/?nosse=1');
  await page.getByRole('button', { name: /Events/ }).click();
  await expect(page.getByRole('button', { name: 'Export CSV' })).toBeVisible();

  await page.getByRole('button', { name: /^Sun$/ }).click();
  await expect(page.getByText('Kp Trend (last 200 points)')).toBeVisible();
});

test('OBS stream overlay renders without app chrome', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (err) => errors.push(String(err)));

  await page.goto('/stream?nosse=1');
  await expect(page.getByText('SOLAR SYSTEM NOW')).toBeVisible();
  await expect(page.getByText('COMPOSITE THREAT')).toBeVisible();
  await expect(page.getByText('UTC', { exact: true })).toBeVisible();
  // Overlay must not contain the dashboard sidebar.
  await expect(page.getByText('Refresh')).toHaveCount(0);

  expect(errors, `uncaught page errors: ${errors.join('; ')}`).toEqual([]);
});
