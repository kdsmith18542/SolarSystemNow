import { expect, test } from '@playwright/test';

// ?nosse=1 keeps a long-lived SSE connection from holding the page busy under
// test; the stream transport is covered by tests/test_remote_e2e.py.

test('dashboard renders hero, nav and seeded events', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (err) => errors.push(String(err)));

  await page.goto('/?nosse=1');
  await expect(page.getByText('Solar System Now')).toBeVisible();
  await expect(page.getByText('COMPOSITE THREAT')).toBeVisible();
  await expect(page.getByText('RECENT EVENTS')).toBeVisible();
  await expect(page.getByText('Tide level')).toHaveCount(0);
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
  await expect(page.getByText('Magnetic Pole Drift')).toBeVisible();
  await expect(page.getByText('Geomagnetic Disturbance Reports')).toBeVisible();
});

test('OBS transparent mode clears the body background', async ({ page }) => {
  await page.goto('/stream?nosse=1&bg=transparent');
  const bodyBackground = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(bodyBackground).toMatch(/rgba?\(0, 0, 0, 0\)|transparent/);
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

test('settings manages locations and sources show health', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('ssnow_write_token', 'e2e-token'));
  await page.goto('/?nosse=1');

  await page.getByRole('button', { name: 'Settings' }).click();
  await page.getByPlaceholder('Name', { exact: true }).fill('Testville');
  await page.getByPlaceholder('Lat').fill('10');
  await page.getByPlaceholder('Lon').fill('20');
  await page.getByRole('button', { name: 'Add', exact: true }).first().click();
  await expect(page.getByText('Testville')).toBeVisible();
  await page.getByRole('button', { name: 'Remove' }).first().click();
  await expect(page.getByText('Testville')).toHaveCount(0);

  await page.getByRole('button', { name: 'Sources' }).click();
  await expect(page.getByText('Sources enabled')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Ingest all due' })).toBeVisible();
  await expect(page.getByText(/sources healthy/)).toBeVisible();
  await expect(page.getByText('0/0 sources healthy')).toHaveCount(0);
  await expect(page.getByText(/never run/i).first()).toBeVisible();
});


test('map tab loads a local style, renders a canvas and toggles radar', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (err) => errors.push(String(err)));
  // Deterministic MapLibre load: no CDN dependency, no external radar tiles.
  await page.route('https://demotiles.maplibre.org/style.json', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ version: 8, name: 'e2e', sources: {}, layers: [] }),
    }),
  );
  await page.route('https://mesonet.agron.iastate.edu/**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'image/png',
      body: Buffer.from(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
        'base64',
      ),
    }),
  );

  await page.goto('/?nosse=1');
  await page.getByRole('button', { name: /Map/ }).click();
  await expect(page.getByText('Layers')).toBeVisible();
  await expect(page.locator('.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText('Loading map…')).toHaveCount(0);
  await expect(page.getByText(/Map style\/tiles unavailable/)).toHaveCount(0);

  const radar = page.locator('label', { hasText: 'Radar (IEM, US)' }).locator('input');
  await expect(radar).not.toBeChecked();
  await radar.check();
  await expect(radar).toBeChecked();
  await radar.uncheck();
  await expect(radar).not.toBeChecked();
  expect(errors, `uncaught page errors: ${errors.join('; ')}`).toEqual([]);
});

test('map falls back to the bundled basemap when the CDN is unavailable', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (err) => errors.push(String(err)));
  await page.route('https://demotiles.maplibre.org/**', (route) => route.abort());

  await page.goto('/?nosse=1');
  await page.getByRole('button', { name: /Map/ }).click();
  await expect(page.locator('.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText('Loading map…')).toHaveCount(0, { timeout: 15_000 });
  await expect(page.getByText(/Map style\/tiles unavailable/)).toHaveCount(0);
  expect(errors, `uncaught page errors: ${errors.join('; ')}`).toEqual([]);
});

test('SSE live badge connects', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('● LIVE')).toBeVisible({ timeout: 15_000 });
});

test('two SSE subscribers stay live simultaneously', async ({ browser }) => {
  const context = await browser.newContext();
  const first = await context.newPage();
  const second = await context.newPage();
  try {
    await Promise.all([first.goto('/'), second.goto('/')]);
    await expect(first.getByText('● LIVE')).toBeVisible({ timeout: 15_000 });
    await expect(second.getByText('● LIVE')).toBeVisible({ timeout: 15_000 });
  } finally {
    await context.close();
  }
});

test('token-gated Settings explains a missing write token', async ({ page }) => {
  await page.addInitScript(() => localStorage.removeItem('ssnow_write_token'));
  await page.goto('/?nosse=1');
  await page.getByRole('button', { name: 'Settings' }).click();
  await expect(page.getByText(/403|write token required/i).first()).toBeVisible({ timeout: 10_000 });
});
