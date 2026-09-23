import { writeFileSync } from 'node:fs';
import { createHmac, randomUUID } from 'node:crypto';
import { test, expect, type BrowserContext, type Page } from '@playwright/test';
import { audit, keyboardActivate } from './accessibility';
const url = process.env.SIERX_TEST_URL;
const session = process.env.SIERX_TEST_SESSION;
if (!url || !session)
  throw new Error(
    'Run make gate-browser: an isolated real API/database fixture is required.',
  );
async function authenticate(context: BrowserContext) {
  await context.addCookies([
    {
      name: '__Host-sierx_session',
      value: session!,
      url: url!,
      secure: true,
      httpOnly: true,
      sameSite: 'Lax',
    },
  ]);
}
async function create(
  context: BrowserContext,
  title: string,
  type = 'story',
  extra = {},
) {
  const response = await context.request.post('/api/v1/items', {
    data: {
      project: 'SRX',
      type,
      title: title + ' ' + randomUUID().slice(0, 8),
      ...extra,
    },
  });
  expect(response.status()).toBe(201);
  return response.json();
}
test.beforeEach(async ({ context }) => authenticate(context));
test('login supports keyboard, passwords and expired sessions', async ({
  page,
  context,
}) => {
  await context.clearCookies();
  await page.goto('/login');
  await audit(page);
  await expect(page.getByLabel('Password', { exact: true })).toHaveAttribute(
    'autocomplete',
    'current-password',
  );
  await expect(
    page.getByLabel('Authenticator or recovery code'),
  ).toHaveAttribute('autocomplete', 'one-time-code');
  await page.getByLabel('Email', { exact: true }).fill('browser@example.test');
  await page.getByLabel('Password', { exact: true }).fill('incorrect-password');
  await keyboardActivate(page, 'Sign in');
  await expect(page.getByRole('alert')).toContainText('Check your email');
  await page
    .getByLabel('Password', { exact: true })
    .fill('browser-test-password-12345');
  await keyboardActivate(page, 'Sign in');
  await expect(
    page.getByRole('heading', { name: 'Your backlog', exact: true }),
  ).toBeVisible();
  await context.clearCookies();
  await page.reload();
  await expect(page).toHaveURL(/\/login$/);
});
for (const theme of ['system', 'light', 'dark', 'light-hc', 'dark-hc'])
  test(`theme ${theme}: first frame, persistence and accessible pages`, async ({
    page,
    context,
  }) => {
    expect(
      (
        await context.request.patch('/api/v1/me', {
          data: { theme, reduced_motion: null },
        })
      ).ok(),
    ).toBe(true);
    const response = await page.goto('/');
    expect(await response!.text()).toContain(`data-theme="${theme}"`);
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
    await audit(page);
    await page
      .getByRole('combobox', { name: 'Theme', exact: true })
      .selectOption(theme === 'light' ? 'dark' : 'light');
    await expect(page.locator('html')).toHaveAttribute(
      'data-theme',
      theme === 'light' ? 'dark' : 'light',
    );
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute(
      'data-theme',
      theme === 'light' ? 'dark' : 'light',
    );
    await keyboardActivate(page, 'Create item');
    await expect(page.getByRole('dialog')).toBeVisible();
    await expect(
      page.getByRole('combobox', { name: 'Type', exact: true }),
    ).toBeVisible();
    await audit(page);
    await page.keyboard.press('Escape');
    await expect(
      page.getByRole('button', { name: 'Create item', exact: true }),
    ).toBeFocused();
    const item = await create(context, 'Theme detail ' + theme);
    await page.goto('/' + item.key);
    await audit(page);
  });
test('initial list, query and deep link need no client data waterfall', async ({
  page,
  context,
}, info) => {
  const trace: { document: string; apiRequests: string[] }[] = [];
  const item = await create(context, 'Initial content <script>safe</script>');
  for (const path of [
    '/',
    '/?q=' + encodeURIComponent('project = SRX'),
    '/' + item.key,
  ]) {
    const requests: string[] = [];
    const handler = (r: { url: () => string }) => {
      if (r.url().includes('/api/v1/')) requests.push(r.url());
    };
    page.on('request', handler);
    await page.route('**/api/v1/**', (route) => route.abort());
    await page.goto(path);
    await expect(
      page.getByText(item.title, { exact: true }).first(),
    ).toBeVisible();
    expect(requests).toEqual([]);
    trace.push({
      document: path,
      apiRequests: requests.map((u) => new URL(u).pathname),
    });
    page.off('request', handler);
    await page.unroute('**/api/v1/**');
  }
  writeFileSync(
    info.outputPath('bootstrap-network.json'),
    JSON.stringify(trace, null, 2),
  );
  const response = await page.goto('/' + item.key.toLowerCase() + '/');
  expect(response!.request().redirectedFrom()).not.toBeNull();
  await expect(page).toHaveURL(new RegExp('/' + item.key + '$'));
});
test('keyboard-only create, transition, reparent, reorder and comment', async ({
  page,
  context,
}) => {
  const parent = await create(context, 'Parent epic', 'epic');
  const sibling = await create(context, 'Preceding story', 'story', {
    parent: parent.key,
  });
  const me = await (await context.request.get('/api/v1/me')).json();
  await page.addInitScript(() => {
    (window as unknown as { mouseEvents: number }).mouseEvents = 0;
    for (const name of ['pointerdown', 'mousedown', 'mouseup'])
      document.addEventListener(
        name,
        () => {
          (window as unknown as { mouseEvents: number }).mouseEvents++;
        },
        true,
      );
  });
  await page.goto('/');
  await keyboardActivate(page, 'Create item');
  await page.getByRole('combobox', { name: 'Type', exact: true }).focus();
  await page.keyboard.press('s');
  await page.keyboard.press('Tab');
  await page.keyboard.type('Keyboard acceptance story');
  await page.keyboard.press('Tab');
  await page.keyboard.type('**Safe** description');
  await keyboardActivate(page, 'Create item');
  await expect(
    page.getByRole('heading', { name: 'Keyboard acceptance story' }),
  ).toBeVisible();
  await keyboardActivate(page, 'Change status');
  await page
    .getByRole('combobox', { name: 'New status', exact: true })
    .selectOption('doing');
  await expect(
    page.getByRole('combobox', { name: 'Assign to', exact: true }),
  ).toHaveValue(me.id);
  await keyboardActivate(page, 'Change status');
  await expect(page.getByRole('status')).toContainText('completed');
  await page.keyboard.press('Escape');
  await keyboardActivate(page, 'Move or reorder');
  await page.getByLabel('Parent item key').fill(parent.key);
  await page.getByLabel('Place after item key').fill(sibling.key);
  await keyboardActivate(page, 'Move item');
  await expect(page.getByRole('status')).toContainText('completed');
  await page.keyboard.press('Escape');
  await page.getByLabel('New comment').focus();
  await page.keyboard.type('Keyboard-only comment');
  await keyboardActivate(page, 'Add comment');
  await expect(
    page.getByText('Keyboard-only comment', { exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => (window as unknown as { mouseEvents: number }).mouseEvents,
    ),
  ).toBe(0);
  // Keyboard-generated click events are expected; native pointer events are
  // disallowed by this test's use of keyboard/focus rather than pointer APIs.
  await audit(page);
});
test('parent displays sibling order and destination can remove a link', async ({
  page,
  context,
}) => {
  const parent = await create(context, 'Ordered parent', 'epic');
  const first = await create(context, 'First child', 'story', {
    parent: parent.key,
  });
  const second = await create(context, 'Second child', 'story', {
    parent: parent.key,
  });
  await page.goto('/' + second.key);
  await page.getByRole('button', { name: 'Move or reorder' }).click();
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Move item' })
    .click();
  await expect(page.getByRole('status')).toContainText('completed');
  await page.goto('/' + parent.key);
  const children = page.getByRole('list', { name: 'Direct children, in order' });
  await expect(children.getByRole('listitem')).toHaveCount(2);
  await expect(children.getByRole('listitem').nth(0)).toContainText(second.key);
  await expect(children.getByRole('listitem').nth(1)).toContainText(first.key);

  const current = await (
    await context.request.get('/api/v1/items/' + first.key)
  ).json();
  const linked = await context.request.post(
    '/api/v1/items/' + first.key + '/links',
    {
      headers: { 'If-Match': `"${current.version}"` },
      data: { to: second.key, kind: 'relates' },
    },
  );
  expect(linked.status()).toBe(201);
  await page.goto('/' + second.key);
  await page.getByRole('button', { name: 'Remove link' }).first().click();
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Remove link' })
    .click();
  await expect(page.getByRole('status')).toContainText('completed');
  const remaining = await (
    await context.request.get('/api/v1/items/' + second.key + '/links')
  ).json();
  expect(remaining.data).toHaveLength(0);
});
test('two real sessions retain conflicts and deliberately retry', async ({
  page,
  context,
  browser,
}) => {
  const item = await create(context, 'Conflict original');
  const second = await browser.newContext({
    baseURL: url,
    ignoreHTTPSErrors: true,
  });
  await authenticate(second);
  const other = await second.newPage();
  await page.goto('/' + item.key);
  await other.goto('/' + item.key);
  await keyboardActivate(page, 'Edit item');
  await page.getByLabel('Title', { exact: true }).fill('My retained draft');
  await keyboardActivate(other, 'Edit item');
  await other.getByLabel('Title', { exact: true }).fill('Their committed edit');
  await keyboardActivate(other, 'Save changes');
  await expect(other.getByRole('status')).toContainText('completed');
  await keyboardActivate(page, 'Save changes');
  await expect(page.getByRole('alert')).toContainText('Someone else changed');
  await expect(
    page.getByRole('cell', { name: '"Their committed edit"', exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue(
    'My retained draft',
  );
  await audit(page);
  await keyboardActivate(page, 'Cancel retry');
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue(
    'My retained draft',
  );
  await keyboardActivate(page, 'Save changes');
  await expect(page.getByRole('status')).toContainText('completed');
  await page.keyboard.press('Escape');
  await expect(
    page.getByRole('heading', { name: 'My retained draft' }),
  ).toBeVisible();
  await second.close();
});
test('deleted item has a dated banner and no mutation controls', async ({
  page,
  context,
}) => {
  const item = await create(context, 'Deleted fixture');
  expect(
    (
      await context.request.delete('/api/v1/items/' + item.key, {
        headers: { 'If-Match': `"${item.version}"` },
      })
    ).ok(),
  ).toBe(true);
  const response = await page.goto('/' + item.key);
  expect(response?.status()).toBe(200);
  await expect(page.getByRole('status')).toContainText('Deleted on');
  await expect(
    page.getByRole('button', { name: 'Edit item', exact: true }),
  ).toHaveCount(0);
  await expect(page.getByLabel('New comment')).toHaveCount(0);
  await audit(page);
});
test('query errors, copied URLs, reload and history navigation', async ({
  page,
  context,
}) => {
  const item = await create(context, 'Query target');
  await page.goto('/?q=' + encodeURIComponent('project = SRX'));
  await expect(
    page.getByRole('link', { name: item.title, exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('Search with SXQ')).toHaveValue('project = SRX');
  await page.getByLabel('Search with SXQ').fill('nonsense = foo');
  await keyboardActivate(page, 'Search');
  await expect(page.getByRole('alert')).toBeVisible();
  await audit(page);
  await page.goBack();
  await expect(page.getByLabel('Search with SXQ')).toHaveValue('project = SRX');
});
test('200 percent text, spacing overrides and reduced motion remain usable', async ({
  page,
}) => {
  await page.emulateMedia({
    reducedMotion: 'reduce',
    colorScheme: 'dark',
    contrast: 'more',
  });
  await page.goto('/');
  await page.addStyleTag({
    content:
      'html {font-size:200%} * {line-height:1.5!important;letter-spacing:.12em!important;word-spacing:.16em!important} p {margin-bottom:2em!important}',
  });
  await audit(page);
  await keyboardActivate(page, 'Create item');
  await expect(page.getByLabel('Title', { exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
});

test('authenticator and one-use recovery codes work through the login form', async ({
  page,
  context,
}, info) => {
  const fixture = JSON.parse(process.env.SIERX_TEST_MFA!)[info.project.name];
  await context.clearCookies();
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(fixture.email);
  await page
    .getByLabel('Password', { exact: true })
    .fill('browser-test-password-12345');
  await keyboardActivate(page, 'Sign in');
  await expect(page.getByRole('alert')).toBeVisible();
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '';
  for (const char of fixture.secret)
    bits += alphabet.indexOf(char).toString(2).padStart(5, '0');
  const secret = Buffer.from(
    bits.match(/.{8}/g)!.map((byte: string) => parseInt(byte, 2)),
  );
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const digest = createHmac('sha1', secret).update(counter).digest();
  const code = ((digest.readUInt32BE(digest[19] & 15) & 0x7fffffff) % 1000000)
    .toString()
    .padStart(6, '0');
  await page.getByLabel('Authenticator or recovery code').fill(code);
  await keyboardActivate(page, 'Sign in');
  await expect(
    page.getByRole('heading', { name: 'Your backlog', exact: true }),
  ).toBeVisible();
  await keyboardActivate(page, 'Sign out');
  await page.getByLabel('Email', { exact: true }).fill(fixture.email);
  await page
    .getByLabel('Password', { exact: true })
    .fill('browser-test-password-12345');
  await page
    .getByLabel('Authenticator or recovery code')
    .fill(fixture.recovery);
  await keyboardActivate(page, 'Sign in');
  await expect(
    page.getByRole('heading', { name: 'Your backlog', exact: true }),
  ).toBeVisible();
  await keyboardActivate(page, 'Sign out');
  await page.getByLabel('Email', { exact: true }).fill(fixture.email);
  await page
    .getByLabel('Password', { exact: true })
    .fill('browser-test-password-12345');
  await page
    .getByLabel('Authenticator or recovery code')
    .fill(fixture.recovery);
  await keyboardActivate(page, 'Sign in');
  await expect(page.getByRole('alert')).toBeVisible();
});

test('accessibility negative controls reject unnamed controls and invalid structure', async ({
  page,
}) => {
  await page.setContent(
    '<html lang="en"><body><button></button><input id="duplicate"><input id="duplicate"><img src="invalid"></body></html>',
  );
  await expect(audit(page)).rejects.toThrow();
});

test('explicit conflict retry applies only the retained draft', async ({
  page,
  context,
}) => {
  const item = await create(context, 'Explicit retry');
  await page.goto('/' + item.key);
  await keyboardActivate(page, 'Edit item');
  await page
    .getByLabel('Title', { exact: true })
    .fill('Explicitly accepted draft');
  expect(
    (
      await context.request.patch('/api/v1/items/' + item.key, {
        headers: { 'If-Match': `"${item.version}"` },
        data: { title: 'Concurrent value' },
      })
    ).ok(),
  ).toBe(true);
  await keyboardActivate(page, 'Save changes');
  await expect(page.getByRole('alert')).toContainText('Someone else changed');
  await keyboardActivate(page, 'Retry my changes');
  await expect(page.getByRole('status')).toContainText('completed');
  await page.keyboard.press('Escape');
  await expect(
    page.getByRole('heading', { name: 'Explicitly accepted draft' }),
  ).toBeVisible();
});

test('visual review fixture', async ({ page, context }, info) => {
  const item = await create(context, 'Prepare the next release', 'story', {
    body: '## Ready for review\n\nA focused backlog for the work ahead.\n\n- Complete the browser walkthrough\n- Verify the restored workspace\n- Record the release decision',
  });
  await context.request.patch('/api/v1/me', {
    data: { theme: 'light', reduced_motion: true },
  });
  await page.goto('/' + item.key);
  await expect(
    page.getByRole('heading', { name: item.title, exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: info.outputPath('detail-light.png'),
    fullPage: true,
  });
  await page.goto('/');
  await expect(
    page.getByRole('heading', { name: 'Your backlog', exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: info.outputPath('backlog-light.png'),
    fullPage: true,
  });
});

test('an expired session preserves the open dialog draft through reauthentication', async ({
  page,
  context,
}) => {
  const item = await create(context, 'Session recovery');
  await page.goto('/' + item.key);
  await keyboardActivate(page, 'Edit item');
  await page.getByLabel('Title', { exact: true }).fill('Draft after sign-in');
  await context.clearCookies();
  await keyboardActivate(page, 'Save changes');
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText(
    'preserve your draft',
  );
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue(
    'Draft after sign-in',
  );
  await authenticate(context);
  await keyboardActivate(page, 'Save changes');
  await expect(page.getByRole('status')).toContainText('completed');
  await page.keyboard.press('Escape');
  await expect(
    page.getByRole('heading', { name: 'Draft after sign-in' }),
  ).toBeVisible();
});

test('deleting through the dialog returns focus to the preserved item heading', async ({
  page,
  context,
}) => {
  const item = await create(context, 'Delete by keyboard');
  await page.goto('/' + item.key);
  await keyboardActivate(page, 'Delete item');
  await keyboardActivate(page, 'Delete item');
  await expect(page.getByRole('status')).toContainText('Deleted on');
  await expect(
    page.getByRole('heading', { name: item.title, exact: true }),
  ).toBeFocused();
  await expect(page.getByRole('dialog')).toHaveCount(0);
});
