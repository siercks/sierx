import { writeFileSync } from 'node:fs';
import { createHmac, randomUUID } from 'node:crypto';
import { test, expect, type BrowserContext, type Page } from '@playwright/test';
import { audit, keyboardActivate } from './accessibility';
import { appearanceThemes } from '../../src/themes/catalog';
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

async function navigationProjects(context: BrowserContext, count: number) {
  const navigationSessions = JSON.parse(process.env.SIERX_TEST_NAV_SESSIONS ?? '{}') as Record<string, string>;
  const token = navigationSessions[test.info().project.name];
  if (!token) throw new Error('The dedicated navigation workspace is required.');
  await context.clearCookies();
  await context.addCookies([{ name: '__Host-sierx_session', value: token, url: url!, secure: true, httpOnly: true, sameSite: 'Lax' }]);
  const group = 'NV' + randomUUID().slice(0, 4).toUpperCase();
  const projects: { key_prefix: string; name: string; title: string }[] = [];
  for (let index = 0; index < count; index++) {
    const prefix = group + index.toString(36).padStart(2, '0').toUpperCase();
    const name = `${group} navigation ${index}`;
    const response = await context.request.post('/api/v1/projects', { data: { key_prefix: prefix, name, kind: index % 2 ? 'discovery' : 'delivery' } });
    expect(response.status()).toBe(201);
    const title = `${group} item ${index}`;
    const item = await context.request.post('/api/v1/items', { data: { project: prefix, type: 'story', title } });
    expect(item.status()).toBe(201);
    projects.push({ key_prefix: prefix, name, title });
  }
  return { group, projects };
}

test('project navigation bounds retained contexts and restores warm back-forward views', async ({ page, context }, info) => {
  const { group, projects } = await navigationProjects(context, 6);
  const itemRequests: string[] = [];
  page.on('request', (request) => { const target = new URL(request.url()); if (target.pathname === '/api/v1/items') itemRequests.push(target.searchParams.get('project') ?? ''); });
  await page.goto('/?project=' + projects[0].key_prefix);
  const nav = page.getByRole('navigation', { name: 'Project navigation' });
  async function choose(index: number) {
    await nav.getByRole('searchbox', { name: 'Find a project' }).fill(group);
    await expect(nav.locator(`option[value="${projects[index].key_prefix}"]`)).toHaveCount(1);
    await nav.getByRole('combobox', { name: 'Project', exact: true }).selectOption(projects[index].key_prefix);
    await expect(page.getByRole('link', { name: projects[index].title, exact: true })).toBeVisible();
  }
  for (let index = 1; index < projects.length; index++) {
    const before = itemRequests.length;
    await choose(index);
    expect(itemRequests.slice(before)).toEqual([projects[index].key_prefix]);
  }
  const warmStart = itemRequests.length;
  const samples: number[] = [];
  await page.evaluate(() => {
    const timings = { samples: [] as number[], stop: () => {} };
    const changed = (event: Event) => {
      const select = event.target;
      if (!(select instanceof HTMLSelectElement) || !select.closest('nav[aria-label="Project navigation"]')) return;
      const prefix = select.value;
      const start = performance.now();
      const frame = () => {
        const link = document.querySelector<HTMLAnchorElement>(`a.item-title[href^="/${prefix}-"]`);
        if (link && link.getBoundingClientRect().height > 0) timings.samples.push(performance.now() - start);
        else requestAnimationFrame(frame);
      };
      requestAnimationFrame(frame);
    };
    document.addEventListener('change', changed);
    timings.stop = () => document.removeEventListener('change', changed);
    (window as unknown as { navigationTimings: typeof timings }).navigationTimings = timings;
  });
  for (let sample = 0; sample < 20; sample++) {
    const start = performance.now();
    await choose(sample % 2 ? 5 : 4);
    samples.push(performance.now() - start);
    await expect.poll(() => page.evaluate(() => (window as unknown as { navigationTimings: { samples: number[] } }).navigationTimings.samples.length)).toBe(sample + 1);
  }
  expect(itemRequests.length).toBe(warmStart);
  const frames = await page.evaluate(() => {
    const timings = (window as unknown as { navigationTimings: { samples: number[]; stop: () => void } }).navigationTimings;
    timings.stop();
    return timings.samples;
  });
  expect(frames).toHaveLength(20);
  // Revisiting the oldest context requires one page again; the whole navigation
  // history must not keep every previously visited list indefinitely.
  const freshTitle = group + ' created while the oldest context was evicted';
  expect((await context.request.post('/api/v1/items', { data: { project: projects[0].key_prefix, type: 'story', title: freshTitle } })).status()).toBe(201);
  await choose(0);
  await expect(page.getByRole('link', { name: freshTitle, exact: true })).toBeVisible();
  expect(itemRequests.slice(warmStart)).toEqual([projects[0].key_prefix]);
  await page.goBack();
  await expect(page.getByRole('link', { name: projects[5].title, exact: true })).toBeVisible();
  await page.goForward();
  await expect(page.getByRole('link', { name: projects[0].title, exact: true })).toBeVisible();
  expect(itemRequests.slice(warmStart)).toEqual([projects[0].key_prefix]);
  const sorted = [...samples].sort((a, b) => a - b);
  const orderedFrames = [...frames].sort((a,b) => a-b);
  await info.attach('warm-navigation-observation', { body: JSON.stringify({ samples: samples.length, p50Ms: sorted[Math.ceil(sorted.length * 0.5) - 1], p95Ms: sorted[Math.ceil(sorted.length * 0.95) - 1], maxMs: sorted.at(-1), includesAutomationOverhead: true, browserChangeToRenderFrame: { samples: frames.length, p50Ms: orderedFrames[9], p95Ms: orderedFrames[18], maxMs: orderedFrames.at(-1), excludesControllerAndProjectSearchOverhead: true, measuresRenderFrameNotPhysicalDisplayPaint: true }, platform: process.platform, architecture: process.arch, warmItemRequests: 0, evictedContextRefetches: 1 }), contentType: 'application/json' });
});

test('project navigation ignores obsolete responses during rapid switching', async ({ page, context }) => {
  const { group, projects } = await navigationProjects(context, 3);
  await page.goto('/?project=' + projects[0].key_prefix);
  let release!: () => void;
  let arrived!: () => void;
  let finished!: () => void;
  const blocked = new Promise<void>((resolve) => { release = resolve; });
  const intercepted = new Promise<void>((resolve) => { arrived = resolve; });
  const settled = new Promise<void>((resolve) => { finished = resolve; });
  await page.route('**/api/v1/items?*', async (route) => {
    if (new URL(route.request().url()).searchParams.get('project') !== projects[1].key_prefix) { await route.continue(); return; }
    try { const response = await route.fetch(); arrived(); await blocked; await route.fulfill({ response }); }
    catch { /* An obsolete fetch may be cancelled before its response is delivered. */ }
    finally { finished(); }
  });
  const nav = page.getByRole('navigation', { name: 'Project navigation' });
  for (const index of [1, 2]) {
    await nav.getByRole('searchbox', { name: 'Find a project' }).fill(group);
    await nav.getByRole('combobox', { name: 'Project', exact: true }).selectOption(projects[index].key_prefix);
    if (index === 1) { await intercepted; await expect(page.getByRole('status').filter({ hasText: 'Loading items' })).toBeVisible(); }
  }
  await expect(page.getByRole('link', { name: projects[2].title, exact: true })).toBeVisible();
  release();
  await settled;
  await expect(page.getByRole('combobox', { name: 'Project', exact: true })).toHaveValue(projects[2].key_prefix);
  await expect(page.getByRole('link', { name: projects[1].title, exact: true })).toHaveCount(0);
  await page.unroute('**/api/v1/items?*');
});

test('a project beyond the first page bootstraps directly and remains reachable through pagination', async ({ page, context }) => {
  test.setTimeout(120000);
  const { projects } = await navigationProjects(context, 102);
  const initial = await (await context.request.get('/api/v1/projects?limit=100')).json();
  const first = new Set(initial.data.map((project: { key_prefix: string }) => project.key_prefix));
  const outside = projects.filter((project) => !first.has(project.key_prefix));
  expect(outside.length).toBeGreaterThanOrEqual(2);
  const target = outside[0];
  const requests: string[] = [];
  await page.route('**/api/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/v1/items' || path.startsWith('/api/v1/projects')) { requests.push(path); return route.abort(); }
    return route.continue();
  });
  await page.goto('/?project=' + target.key_prefix);
  await expect(page.getByRole('heading', { name: target.name, exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: target.title, exact: true })).toBeVisible();
  expect(requests).toEqual([]);
  await page.unroute('**/api/v1/**');
  const nav = page.getByRole('navigation', { name: 'Project navigation' });
  for (let pageNumber = 0; pageNumber < 5 && await nav.locator(`option[value="${outside[1].key_prefix}"]`).count() === 0; pageNumber++) {
    const response = page.waitForResponse((entry) => new URL(entry.url()).pathname === '/api/v1/projects');
    await nav.getByRole('button', { name: 'More', exact: true }).click();
    expect((await response).ok()).toBe(true);
  }
  await expect(nav.locator(`option[value="${outside[1].key_prefix}"]`)).toHaveCount(1);
});

test('650ms response latency preserves a failed edit draft and shows pending feedback on retry', async ({ page, context }, info) => {
  const item = await create(context, 'Slow connection edit');
  await page.goto('/' + item.key);
  await page.getByRole('button', { name: 'Edit item', exact: true }).click();
  const title = 'Retained slow-link draft ' + randomUUID().slice(0, 8);
  await page.getByLabel('Title', { exact: true }).fill(title);
  let attempts = 0;
  await page.route('**/api/v1/items/' + item.key, async (route) => {
    if (route.request().method() !== 'PATCH') { await route.continue(); return; }
    attempts++;
    const response = attempts === 1 ? null : await route.fetch();
    await new Promise((resolve) => setTimeout(resolve, 650));
    if (response) await route.fulfill({ response });
    else await route.fulfill({ status: 503, contentType: 'application/problem+json', body: JSON.stringify({ status: 503, title: 'Temporary test outage', detail: 'Test connection interrupted. Your draft is retained.' }) });
  });
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(dialog.getByRole('button', { name: 'Saving…', exact: true })).toBeDisabled();
  await expect(dialog.getByRole('alert')).toContainText('Test connection interrupted');
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue(title);
  const started = performance.now();
  await dialog.getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(dialog.getByRole('button', { name: 'Saving…', exact: true })).toBeDisabled();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
  const elapsedMs = performance.now() - started;
  expect(elapsedMs).toBeGreaterThanOrEqual(650);
  expect(attempts).toBe(2);
  await info.attach('slow-link-observation', { body: JSON.stringify({ imposedResponseDelayMs: 650, successElapsedMs: elapsedMs, attempts, includesNetworkAndAutomation: true }), contentType: 'application/json' });
});

test('project creation and metadata editing refresh the selected dashboard', async ({ page }) => {
  const prefix='PM'+randomUUID().slice(0,6).toUpperCase();
  await page.goto('/');
  await page.getByRole('button',{name:'Create project',exact:true}).click();
  let dialog=page.getByRole('dialog');
  await dialog.getByLabel('Project name',{exact:true}).fill('Acceptance project '+prefix);
  await dialog.getByLabel('Key prefix',{exact:true}).fill(prefix);
  await dialog.getByRole('button',{name:'Create project',exact:true}).click();
  await expect(dialog).toBeHidden();
  await page.getByRole('button',{name:'Manage projects',exact:true}).click();
  await page.getByRole('button',{name:'Edit project',exact:true}).click();
  dialog=page.getByRole('dialog');
  await dialog.getByLabel('Project name',{exact:true}).fill('Edited acceptance project '+prefix);
  await dialog.getByRole('button',{name:'Save project',exact:true}).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole('heading',{name:'Edited acceptance project '+prefix,exact:true})).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading',{name:'Edited acceptance project '+prefix,exact:true})).toBeVisible();
});

test('usability: item titles align across status widths in every appearance', async ({ page, context }) => {
  const todo = await create(context, 'Aligned title');
  const doing = await create(context, 'Aligned title');
  const me = await (await context.request.get('/api/v1/me')).json();
  expect((await context.request.post(`/api/v1/items/${doing.key}/transition`, {
    headers: { 'If-Match': `"${doing.version}"` },
    data: { to_status: 'doing', fields: { assignee: me.id } },
  })).ok()).toBe(true);
  await page.goto('/?q=' + encodeURIComponent(`key in ("${todo.key}", "${doing.key}")`));
  for (const { id } of appearanceThemes) {
    await page.evaluate((theme) => { document.documentElement.dataset.theme = theme; }, id);
    await page.evaluate(() => document.fonts.ready);
    const a = page.locator(`.item-title[href="/${todo.key}"]`);
    const b = page.locator(`.item-title[href="/${doing.key}"]`);
    await expect(a).toBeVisible();
    await expect(b).toBeVisible();
    expect(Math.abs((await a.boundingBox())!.x - (await b.boundingBox())!.x), id).toBeLessThan(1);
  }
});

test('usability: footer links are centered and wrap within the viewport', async ({ page, context }) => {
  const item = await create(context, 'Footer alignment');
  for (const width of [1280, 320]) {
    await page.setViewportSize({ width, height: 900 });
    for (const path of ['/', '/' + item.key, '/login', '/privacy', '/copyright', '/third-party']) {
      await page.goto(path);
      const footer = page.locator('.legal-footer').last();
      await expect(footer).toBeVisible();
      const geometry = await footer.evaluate((element) => {
        const box = element.getBoundingClientRect();
        const children = Array.from(element.querySelectorAll('a')).map((a) => a.getBoundingClientRect());
        return { center: (box.left + box.right) / 2, left: Math.min(...children.map((b) => b.left)), right: Math.max(...children.map((b) => b.right)), viewport: innerWidth };
      });
      expect(Math.abs((geometry.left + geometry.right) / 2 - geometry.center), path).toBeLessThan(2);
      expect(geometry.left).toBeGreaterThanOrEqual(0);
      expect(geometry.right).toBeLessThanOrEqual(geometry.viewport);
    }
  }
});

test('usability: plain item detail uses workspace width', async ({ page, context }) => {
  const item = await create(context, 'Full width plain detail');
  await page.setViewportSize({ width: 1280, height: 900 });
  await context.request.patch('/api/v1/me', { data: { theme: 'plain' } });
  await page.goto('/' + item.key);
  const sizes = await page.locator('.item-document').evaluate((element) => {
    const main = element.parentElement!;
    const style = getComputedStyle(main);
    return { document: element.getBoundingClientRect().width, available: main.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) };
  });
  expect(sizes.document).toBeGreaterThanOrEqual(sizes.available - 2);
});

test('usability: platinum mobile keeps content inset and controls readable', async ({ page, context }, info) => {
  const item = await create(context, 'Mobile spacing and a long item title for wrapping');
  await context.request.patch('/api/v1/me', { data: { theme: 'platinum' } });
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 844 });
    for (const path of ['/', '/' + item.key]) {
      await page.goto(path);
      const geometry = await page.locator('.app-main').evaluate((element) => {
        const main = element.getBoundingClientRect();
        const content = element.querySelector('.page-heading, .breadcrumbs')!.getBoundingClientRect();
        return { left: content.left - main.left, right: main.right - content.right, scroll: document.documentElement.scrollWidth, viewport: innerWidth };
      });
      expect(geometry.left).toBeGreaterThanOrEqual(8);
      expect(geometry.right).toBeGreaterThanOrEqual(8);
      expect(geometry.scroll).toBeLessThanOrEqual(geometry.viewport);
      await page.screenshot({ path: info.outputPath(`platinum-${width}-${path === '/' ? 'list' : 'detail'}.png`), fullPage: true });
    }
    await keyboardActivate(page, 'Edit item');
    const title = page.getByLabel('Title', { exact: true });
    await expect(title).toBeVisible();
    const padding = await title.evaluate((element) => {
      const style = getComputedStyle(element);
      return { left: parseFloat(style.paddingLeft), top: parseFloat(style.paddingTop), height: element.clientHeight, font: parseFloat(style.fontSize) };
    });
    expect(padding.left).toBeGreaterThanOrEqual(8);
    expect(padding.top).toBeGreaterThanOrEqual(6);
    expect(padding.height).toBeGreaterThan(padding.font * 1.5);
    await page.keyboard.press('Escape');
  }
});

test('usability: item save closes only on success and returns focus', async ({ page, context }) => {
  const item = await create(context, 'Save and close');
  await page.goto('/' + item.key);
  await keyboardActivate(page, 'Edit item');
  await page.getByLabel('Title', { exact: true }).fill('Saved without another click');
  await page.route('**/api/v1/items/' + item.key, (route) => route.request().method() === 'PATCH'
    ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ title: 'Temporarily unavailable' }) })
    : route.continue());
  await keyboardActivate(page, 'Save changes');
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('Temporarily unavailable');
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Saved without another click');
  await page.unroute('**/api/v1/items/' + item.key);
  await keyboardActivate(page, 'Save changes');
  await expect(page.getByRole('dialog')).toBeHidden();
  await expect(page.getByRole('heading', { name: 'Saved without another click' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Edit item', exact: true })).toBeFocused();
});
test('priorities: Details edits change only assignee or the selected date', async ({ page, context }) => {
  const item = await create(context, 'Quick field edits', 'story', { body: 'Keep this description' });
  const me = await (await context.request.get('/api/v1/me')).json();
  await page.goto('/' + item.key);
  await page.getByRole('button', { name: 'Edit assignee', exact: true }).click();
  await page.getByRole('combobox', { name: 'Assignee', exact: true }).selectOption(me.id);
  await page.getByRole('button', { name: 'Save assignee', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeHidden();
  for (const [label, field, value] of [['Start date', 'start_date', '2026-11-01'], ['Due date', 'due_date', '2026-11-08']]) {
    await page.getByRole('button', { name: `Edit ${label.toLowerCase()}`, exact: true }).click();
    await page.getByLabel(label, { exact: true }).fill(value);
    await page.getByRole('button', { name: `Save ${label.toLowerCase()}`, exact: true }).click();
    await expect(page.getByRole('dialog')).toBeHidden();
    const saved = await (await context.request.get('/api/v1/items/' + item.key)).json();
    expect(saved[field]).toBe(value); expect(saved.body).toBe('Keep this description'); expect(saved.title).toBe(item.title);
  }
  await page.getByRole('button', { name: 'Edit due date', exact: true }).click();
  await page.getByRole('button', { name: 'Clear date', exact: true }).click();
  await page.getByRole('button', { name: 'Save due date', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeHidden();
  const saved = await (await context.request.get('/api/v1/items/' + item.key)).json();
  expect(saved.assignee.id).toBe(me.id); expect(saved.start_date).toBe('2026-11-01'); expect(saved.due_date).toBeNull();
  await audit(page);
});

test('priorities: Markdown toolbar and preview preserve source and clear submitted comments', async ({ page, context }) => {
  const item = await create(context, 'Markdown editing');
  await page.goto('/' + item.key);
  await page.getByRole('button', { name: 'Edit item', exact: true }).click();
  const dialog = page.getByRole('dialog');
  const description = dialog.getByLabel('Description', { exact: true });
  await description.fill('Selected words');
  await description.selectText();
  await dialog.getByRole('button', { name: 'Bold', exact: true }).click();
  await expect(description).toHaveValue('**Selected words**');
  await dialog.getByRole('button', { name: 'Preview', exact: true }).click();
  await expect(dialog.getByRole('region', { name: 'Description preview' }).locator('strong')).toHaveText('Selected words');
  await audit(page);
  await dialog.getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page.locator('.description-card strong')).toHaveText('Selected words');
  const comment = page.getByLabel('New comment', { exact: true });
  await comment.fill('Comment draft');
  await page.getByRole('button', { name: 'Add comment', exact: true }).click();
  await expect(comment).toHaveValue('');
  await expect(page.locator('.comment-body')).toContainText('Comment draft');
});

test('priorities: project creation and admin settings publish a usable custom workflow', async ({ page, context }, info) => {
  const prefix = 'UX' + randomUUID().slice(0, 6).toUpperCase();
  await page.goto('/');
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Project name', { exact: true }).fill('Custom workflow project ' + prefix);
  await dialog.getByLabel('Key prefix', { exact: true }).fill(prefix);
  await audit(page);
  await dialog.getByRole('button', { name: 'Create project', exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole('navigation', { name: 'Project navigation' }).getByRole('button', { name: 'Create project', exact: true })).toBeFocused();
  await expect(page.getByRole('combobox', { name: 'Project', exact: true })).toHaveValue(prefix);
  await page.getByRole('link', { name: 'Settings', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Workspace settings', exact: true })).toBeVisible();
  await page.getByLabel('Workspace name', { exact: true }).fill('Team workspace');
  await page.getByRole('button', { name: 'Save workspace', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Workspace details saved');
  await page.reload();
  await expect(page.getByLabel('Workspace name', { exact: true })).toHaveValue('Team workspace');
  await page.getByRole('combobox', { name: 'Workflow project', exact: true }).selectOption(prefix);
  await page.getByRole('button', { name: 'Add suggested statuses', exact: true }).click();
  await page.getByLabel('Allow To Do → Planned', { exact: true }).check();
  await page.getByLabel(`I reviewed this flow and its required fields for ${prefix}.`, { exact: true }).check();
  await audit(page);
  await page.screenshot({ path: info.outputPath('workspace-workflow-settings.png'), fullPage: true });
  await page.getByRole('button', { name: 'Save workflow', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Workflow version 2');
  const config = await (await context.request.get(`/api/v1/projects/${prefix}/config`)).json();
  expect(config.statuses.map((status: { name: string }) => status.name)).toEqual(expect.arrayContaining(['Unassigned', 'To Do', 'On Hold', 'Planned', 'In Progress', 'Blocked', 'Completed']));
  const result = await context.request.post('/api/v1/items', { data: { project: prefix, type: 'story', title: 'Uses custom flow' } });
  expect(result.ok()).toBe(true);
  const item = await result.json();
  await page.goto('/' + item.key);
  await page.getByRole('button', { name: 'Change status', exact: true }).click();
  await page.getByRole('combobox', { name: 'New status', exact: true }).selectOption('planned');
  await page.getByRole('dialog').getByRole('button', { name: 'Change status', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeHidden();
  await expect(page.getByRole('button', { name: 'Edit item', exact: true })).toBeFocused();
  await expect(page.locator('.item-heading .badge')).toContainText('Planned');
});

test('priorities: default-size settings buttons have readable labels in every appearance', async ({ page }) => {
  await page.goto('/settings');
  await page.getByRole('combobox', { name: 'Workflow project', exact: true }).selectOption('SRX');
  await page.getByLabel('I reviewed this flow and its required fields for SRX.', { exact: true }).check();
  await page.evaluate(() => { document.documentElement.dataset.motion = 'reduce'; });
  for (const { id } of appearanceThemes) {
    await page.evaluate((theme) => { document.documentElement.dataset.theme = theme; }, id);
    for (const name of ['Save workspace', 'Add status', 'Add suggested statuses', 'Save workflow']) {
      const colors = await page.getByRole('button', { name, exact: true }).evaluate((element) => {
        const style = getComputedStyle(element);
        let ancestor: Element | null = element;
        let background = style.backgroundColor;
        while (ancestor) {
          background = getComputedStyle(ancestor).backgroundColor;
          const components = background.match(/[\d.]+/g)?.map(Number) ?? [];
          if (components.length < 4 || components[3] !== 0) break;
          ancestor = ancestor.parentElement;
        }
        return { text: style.color, background };
      });
      expect(contrastRatio(colors.text, colors.background), `${id}: ${name}`).toBeGreaterThanOrEqual(4.5);
    }
  }
});

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
const themeIDs = ['system', ...appearanceThemes.map(({ id }) => id)];
function contrastRatio(foreground: string, background: string) {
  const luminance = (value: string) => {
    const channels = value.match(/[\d.]+/g)?.slice(0, 3).map(Number);
    if (!channels || channels.length !== 3)
      throw new Error(`Unsupported computed color: ${value}`);
    const [r, g, b] = channels.map((channel) => {
      const normalized = channel / 255;
      return normalized <= 0.04045
        ? normalized / 12.92
        : ((normalized + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const a = luminance(foreground);
  const b = luminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}
test('native dropdowns keep readable colors in the affected themes', async ({
  page,
  context,
}) => {
  for (const theme of ['swiss', 'eink', 'eink-dark', 'brutal', 'civic', 'kraft']) {
    const updated = await context.request.patch('/api/v1/me', {
      data: { theme, reduced_motion: null },
    });
    expect(updated.ok()).toBe(true);
    await page.goto('/');
    const foreground = await page
      .getByRole('combobox', { name: 'Theme', exact: true })
      .evaluate((control) => {
        const style = getComputedStyle(control);
        return { color: style.color, background: style.backgroundColor };
      });
    expect(contrastRatio(foreground.color, foreground.background)).toBeGreaterThanOrEqual(4.5);
    const options = await page.locator('select option').evaluateAll((elements) =>
      elements.map((option) => {
        const style = getComputedStyle(option);
        return { color: style.color, background: style.backgroundColor };
      }),
    );
    for (const option of options)
      expect(contrastRatio(option.color, option.background)).toBeGreaterThanOrEqual(4.5);
  }
});
for (const [index, theme] of themeIDs.entries()) {
  const nextTheme = themeIDs[(index + 1) % themeIDs.length];
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
    const optionColors = await page.locator('select option').evaluateAll((options) =>
      options.map((option) => {
        const style = getComputedStyle(option);
        return { foreground: style.color, background: style.backgroundColor };
      }),
    );
    const themeControlColors = await page
      .getByRole('combobox', { name: 'Theme', exact: true })
      .evaluate((control) => {
        const style = getComputedStyle(control);
        return { foreground: style.color, background: style.backgroundColor };
      });
    expect(
      contrastRatio(themeControlColors.foreground, themeControlColors.background),
    ).toBeGreaterThanOrEqual(4.5);
    expect(optionColors.length).toBeGreaterThan(0);
    for (const colors of optionColors)
      expect(contrastRatio(colors.foreground, colors.background)).toBeGreaterThanOrEqual(4.5);
    await audit(page);
    await page
      .getByRole('combobox', { name: 'Theme', exact: true })
      .selectOption(nextTheme);
    await expect(page.locator('html')).toHaveAttribute(
      'data-theme',
      nextTheme,
    );
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute(
      'data-theme',
      nextTheme,
    );
    await keyboardActivate(page, 'Create item');
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.getByRole('dialog').getByRole('combobox', { name: 'Project', exact: true }).selectOption('SRX');
    await expect(
      page.getByRole('combobox', { name: 'Type', exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole('combobox', { name: 'Type', exact: true }),
    ).toHaveAccessibleDescription(/^Initial status: .+/);
    await audit(page);
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toBeHidden();
    await expect(
      page.getByRole('button', { name: 'Create item', exact: true }),
    ).toBeFocused();
    const item = await create(context, 'Theme detail ' + theme);
    await page.goto('/' + item.key);
    await audit(page);
    await keyboardActivate(page, 'Edit item');
    await expect(page.getByRole('dialog')).toBeVisible();
    await expect(page.getByLabel('Title', { exact: true })).toBeVisible();
    await audit(page);
    await page.keyboard.press('Escape');
  });
}
test('initial list, query and deep link need no client data waterfall', async ({
  page,
  context,
}, info) => {
  const trace: { document: string; apiRequests: string[] }[] = [];
  const item = await create(context, 'Initial content <script>safe</script>');
  // Each engine shares the backlog; newly created rows can be virtualized away.
  const initial = await context.request.get('/api/v1/items?limit=1&fields=key,title');
  expect(initial.ok()).toBe(true);
  const first = (await initial.json()).data[0];
  expect(first).toBeDefined();
  for (const { path, title } of [
    { path: '/', title: first.title },
    { path: '/?q=' + encodeURIComponent(`key = "${item.key}"`), title: item.title },
    { path: '/' + item.key, title: item.title },
  ]) {
    const requests: string[] = [];
    const handler = (r: { url: () => string }) => {
      if (r.url().includes('/api/v1/')) requests.push(r.url());
    };
    page.on('request', handler);
    await page.route('**/api/v1/**', (route) => route.abort());
    await page.goto(path);
    await expect(
      page.getByText(title, { exact: true }).first(),
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
test('runtime pages make no requests to third-party origins', async ({
  page,
  context,
}) => {
  let instanceOrigin: string | undefined;
  const externalRequests: string[] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (!['http:', 'https:'].includes(url.protocol)) return;
    if (request.isNavigationRequest() && instanceOrigin === undefined)
      instanceOrigin = url.origin;
    if (instanceOrigin !== undefined && url.origin !== instanceOrigin)
      externalRequests.push(`${request.method()} ${url.origin}${url.pathname}`);
  });

  await page.goto('/privacy');
  await expect(page.getByRole('heading', { name: 'Privacy' })).toBeVisible();
  await expect(page).toHaveTitle('Privacy · Sierx');
  await page.goto('/third-party');
  await expect(page.getByRole('heading', { name: 'Third-party notices' })).toBeVisible();
  await expect(page).toHaveTitle('Third-party notices · Sierx');
  await page.goto('/login');
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
  await expect(page).toHaveTitle('Sign in · Sierx');
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Create item' })).toBeVisible();
  await expect(page).toHaveTitle('Workspace · Sierx');
  await page.goto('/?project=SRX');
  await expect(page).toHaveTitle('Backlog · Sierx');
  const item = await create(context, 'Private page request observation');
  await page.goto('/' + item.key);
  await expect(page.getByText(item.title, { exact: true })).toBeVisible();
  await expect(page).toHaveTitle(item.key + ' · ' + item.title + ' · Sierx');
  const commentStatus = await page.evaluate(async (key) =>
    (await fetch(`/api/v1/comments?item=${encodeURIComponent(key)}`)).status,
  item.key);
  expect(commentStatus).toBe(200);

  expect(externalRequests).toEqual([]);
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
  await page.getByRole('dialog').getByRole('combobox', { name: 'Project', exact: true }).selectOption('SRX');
  await page.getByRole('combobox', { name: 'Type', exact: true }).focus();
  await page.keyboard.press('s');
  await page.keyboard.press('Tab');
  await page.keyboard.type('Keyboard acceptance story');
  await page.getByLabel('Description', { exact: true }).focus();
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
  await expect(page.getByRole('dialog')).toBeHidden();
  await keyboardActivate(page, 'Move or reorder');
  await page.getByLabel('Parent item key').fill(parent.key);
  await page.getByLabel('Place after item key').fill(sibling.key);
  await keyboardActivate(page, 'Move item');
  await expect(page.getByRole('status')).toContainText('completed');
  await page.keyboard.press('Escape');
  await page.getByLabel('New comment', { exact: true }).focus();
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
test('comment completion waits for item refresh before follow-up linking', async ({ page, context }) => {
  const item = await create(context, 'Comment then link');
  const target = await create(context, 'Follow-up link target');
  await page.goto('/' + item.key);
  let posted = false;
  let releaseItem!: () => void;
  const itemGate = new Promise<void>((resolve) => { releaseItem = resolve; });
  await page.route((url) => url.pathname === '/api/v1/comments', async (route) => {
    if (route.request().method() === 'POST') posted = true;
    await route.continue();
  });
  await page.route((url) => url.pathname === '/api/v1/items/' + item.key, async (route) => {
    if (posted && route.request().method() === 'GET') await itemGate;
    await route.continue();
  });
  const comment = page.getByLabel('New comment', { exact: true });
  await comment.fill('Posted before item refresh');
  try {
    await page.getByRole('button', { name: 'Add comment', exact: true }).click();
    await expect(page.locator('.comment-body')).toContainText('Posted before item refresh');
    await expect(page.getByRole('button', { name: 'Saving…', exact: true })).toBeDisabled();
    await expect(comment).toHaveValue('Posted before item refresh');
  } finally {
    releaseItem();
  }
  await expect(comment).toHaveValue('');
  await page.getByRole('button', { name: 'Link item', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Item key', { exact: true }).fill(target.key);
  await dialog.getByRole('button', { name: 'Add link', exact: true }).click();
  await expect(dialog.getByRole('status')).toContainText('completed');
  const links = await (await context.request.get('/api/v1/items/' + item.key + '/links')).json();
  expect(links.data.some((link: { to: { key: string } }) => link.to.key === target.key)).toBe(true);
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
  const link = await linked.json();
  const linkPath = '/api/v1/links/' + link.id;
  let releaseDelete!: () => void;
  const deleteGate = new Promise<void>((resolve) => { releaseDelete = resolve; });
  await page.route((target) => target.pathname === linkPath, async (route) => {
    if (route.request().method() === 'DELETE') await deleteGate;
    await route.continue();
  });
  await page.goto('/' + second.key);
  await page.getByRole('button', { name: 'Remove link' }).first().click();
  const dialog = page.getByRole('dialog');
  const deleted = page.waitForResponse((response) =>
    response.request().method() === 'DELETE' && new URL(response.url()).pathname === linkPath,
  );
  try {
    await dialog.getByRole('button', { name: 'Remove link' }).click();
    await expect(dialog.getByRole('button', { name: 'Saving…' })).toBeDisabled();
    const pending = await (await context.request.get('/api/v1/items/' + second.key + '/links')).json();
    expect(pending.data).toHaveLength(1);
  } finally {
    releaseDelete();
  }
  // While saving, the submit label changes and the modal hides background
  // buttons from role queries. Their absence alone is not deletion success.
  expect((await deleted).status()).toBe(200);
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Remove link' })).toHaveCount(0);
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
  await expect(other.getByRole('dialog')).toBeHidden();
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
  await expect(page.getByRole('dialog')).toBeHidden();
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
  await expect(page.getByLabel('New comment', { exact: true })).toHaveCount(0);
  await audit(page);
});
test('query errors, copied URLs, reload and history navigation', async ({
  page,
  context,
}) => {
  const item = await create(context, 'Query target');
  const query = `project = SRX AND key = "${item.key}"`;
  await page.goto('/?q=' + encodeURIComponent(query));
  await expect(
    page.getByRole('link', { name: item.title, exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('Search backlog', { exact: true })).toHaveValue(query);
  await page.getByLabel('Search backlog', { exact: true }).fill('nonsense = foo');
  await keyboardActivate(page, 'Search');
  await expect(page.getByRole('alert')).toBeVisible();
  await audit(page);
  await page.goBack();
  await expect(page.getByLabel('Search backlog', { exact: true })).toHaveValue(query);
});
test('search controls stay within narrow viewports without an enclosing shell', async ({
  page,
}) => {
  await page.setViewportSize({ width: 280, height: 760 });
  await page.goto('/?q=' + encodeURIComponent('project = SRX'));
  const panel = page.locator('.search-panel');
  await expect(panel).toBeVisible();
  await expect(panel).not.toHaveClass(/sx-query/);
  const geometry = await panel.evaluate((element) => {
    const rects = [...element.querySelectorAll('input, .search-actions, .search-actions > *')]
      .map((child) => child.getBoundingClientRect());
    return {
      width: element.clientWidth,
      scrollWidth: element.scrollWidth,
      borders: getComputedStyle(element).borderTopWidth,
      controlsFit: rects.every((rect) => rect.left >= 0 && rect.right <= innerWidth),
    };
  });
  expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.width);
  expect(geometry.borders).toBe('0px');
  expect(geometry.controlsFit).toBe(true);
  await audit(page);
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
  await expect(page.getByRole('dialog')).toBeHidden();
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
  await expect(page.getByRole('dialog')).toBeHidden();
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
