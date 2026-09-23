import { test, expect } from '@playwright/test';
test('10k real items keep bounded DOM and keyboard focus while scrolling', async ({
  page,
  context,
}) => {
  test.setTimeout(240000);
  if (process.env.SIERX_BROWSER_SCALE !== '1')
    throw new Error(
      'Run make gate-virtualization for the distinct 10k database fixture',
    );
  await context.addCookies([
    {
      name: '__Host-sierx_session',
      value: process.env.SIERX_TEST_SESSION!,
      url: process.env.SIERX_TEST_URL!,
      secure: true,
      httpOnly: true,
      sameSite: 'Lax',
    },
  ]);
  await page.goto('/');
  for (let i = 1; i < 100; i++) {
    await page
      .getByRole('button', { name: 'Load more items', exact: true })
      .click();
    await expect(page.getByRole('status')).toContainText(
      `${(i + 1) * 100} items loaded`,
    );
    expect(await page.getByRole('listitem').count()).toBeLessThan(50);
  }
  await expect(page.getByRole('status')).toContainText('10000 items loaded');
  const first = page.getByRole('listitem').first().getByRole('link');
  await first.focus();
  const href = await first.getAttribute('href');
  await page.getByRole('region', { name: 'Backlog items' }).evaluate((e) => {
    e.scrollTop = e.scrollHeight;
  });
  expect(await page.getByRole('listitem').count()).toBeLessThan(50);
  await expect(page.locator(`a[href="${href}"]`)).toBeFocused();
  await page.keyboard.press('Tab');
  expect(await page.locator('body *').count()).toBeLessThan(700);
});
