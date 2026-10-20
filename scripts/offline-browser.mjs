// Delivered-image browser acceptance. Credentials and work content never enter reports.
import assert from 'node:assert/strict';
import { createHash, randomUUID, X509Certificate } from 'node:crypto';
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
const { chromium, firefox } = await import('/opt/acceptance/node_modules/playwright/index.mjs');
const { expect: baseExpect } = await import('/opt/acceptance/node_modules/@playwright/test/index.mjs');
assert([undefined, '0', '1'].includes(process.env.SIERX_TEST_EMULATED), 'Invalid fixture timing mode');
const emulated = process.env.SIERX_TEST_EMULATED === '1';
const expect = baseExpect.configure({ timeout: emulated ? 60000 : 5000 });
const launchTimeout = emulated ? 180000 : 30000;
const firefoxLaunchTimeout = emulated ? 600000 : 30000;
const base = process.env.SIERX_BASE_URL;
const certificate = process.env.SSL_CERT_FILE;
const serverCertificate = process.env.SIERX_TEST_SERVER_CERT;
assert(base && certificate && serverCertificate, 'Explicit fixture origin, CA and leaf certificate are required');
const origin = new URL(base).origin;
let phase = 'launch';
// Match Mozilla's own desktop test profile: a slow offline run must not
// trigger the browser updater's aus5.mozilla.org lookup in the background.
const firefoxUserPrefs = { 'app.update.disabledForTesting': true,
  'app.update.auto': false, 'app.update.checkInstallTime': false };

async function guard(context) {
  const state = { external: [], workers: 0, negative: false, controls: new Set() };
  const allowed = (raw) => {
    const target = new URL(raw);
    if (['about:', 'data:', 'blob:'].includes(target.protocol)) return true;
    if (target.protocol === 'wss:') target.protocol = 'https:';
    return target.origin === origin;
  };
  context.on('serviceworker', () => { state.workers++; });
  context.on('request', (request) => {
    if (!allowed(request.url()) && !state.negative) state.external.push(request.resourceType());
  });
  await context.route('**/*', async (route) => {
    if (allowed(route.request().url())) return route.continue();
    if (state.negative) state.controls.add(route.request().resourceType()+(new URL(route.request().url()).hostname.includes(':')?'-ipv6':''));
    else state.external.push(route.request().resourceType());
    await route.abort('blockedbyclient');
  });
  await context.routeWebSocket(/.*/, (socket) => {
    if (allowed(socket.url())) { socket.connectToServer(); return; }
    if (state.negative) state.controls.add('websocket');
    else state.external.push('websocket');
    socket.close({ code: 1008, reason: 'Fixture forbids external destinations' });
  });
  return state;
}

async function controls(context, state) {
  // Firefox's persistent context exits when its last window closes. Keep the
  // control window alive while disposing of the application's pages.
  const page = await context.newPage();
  for (const existing of context.pages()) if (existing !== page) await existing.close();
  state.negative = true;
  await page.goto('https://192.0.2.10/blocked-navigation', { timeout: 5000 }).catch(() => {});
  await page.goto('https://[2001:db8::10]/blocked-ipv6-navigation', { timeout: 5000 }).catch(() => {});
  const blank = await context.newPage();
  await blank.setContent('<img src="https://192.0.2.10/blocked-image">');
  await blank.evaluate(() => { const socket = new WebSocket('ws://192.0.2.10:18181/blocked-socket'); socket.onerror = () => {}; });
  await blank.evaluate(async (controlTimeout) => {
    const source = URL.createObjectURL(new Blob(["fetch('https://192.0.2.10/blocked-worker').then(() => postMessage('unexpected')).catch(() => postMessage('blocked'))"], { type: 'text/javascript' }));
    const worker = new Worker(source);
    try {
      await new Promise((resolve, reject) => {
        const deadline = setTimeout(() => reject(new Error('Worker control timed out')), controlTimeout);
        worker.onmessage = (event) => { clearTimeout(deadline); event.data === 'blocked' ? resolve() : reject(new Error('Worker fetch escaped the guard')); };
        worker.onerror = () => { clearTimeout(deadline); reject(new Error('Worker control did not execute')); };
      });
    } finally { worker.terminate(); URL.revokeObjectURL(source); }
  }, emulated ? 60000 : 5000);
  await expect.poll(() => [...state.controls].sort()).toEqual(['document','document-ipv6', 'fetch', 'image', 'websocket']);
  assert.equal(state.workers, 0, 'Service workers must not hide requests');
}

async function core(context, engine) {
  phase = engine + '-context-setup';
  context.setDefaultTimeout(emulated && engine === 'firefox' ? firefoxLaunchTimeout : emulated ? 120000 : 30000);
  context.setDefaultNavigationTimeout(emulated ? 120000 : 30000);
  const observation = await guard(context);
  phase = engine + '-new-page';
  // A fresh persistent Firefox profile already opens a blank page. Reuse it
  // instead of starting an unnecessary second renderer under emulation.
  const page = context.pages()[0] ?? await context.newPage();
  context.setDefaultTimeout(emulated ? 120000 : 30000);
  const prefix = 'OF' + randomUUID().slice(0, 6).toUpperCase();
  const title = 'Offline browser ' + engine + ' ' + prefix;
  phase = engine + '-login';
  await page.goto(base + '/login');
  await page.getByLabel('Email', { exact: true }).fill(process.env.SIERX_BOOTSTRAP_ADMIN_EMAIL);
  await page.getByLabel('Password', { exact: true }).fill(process.env.SIERX_BOOTSTRAP_ADMIN_PASSWORD);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Create item', exact: true })).toBeVisible();
  phase = engine + '-create-project';
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  let dialog = page.getByRole('dialog');
  await dialog.getByLabel('Project name', { exact: true }).fill('Offline project ' + prefix);
  await dialog.getByLabel('Key prefix', { exact: true }).fill(prefix);
  await dialog.getByRole('button', { name: 'Create project', exact: true }).click();
  await expect(dialog).toBeHidden();
  phase = engine + '-edit-project';
  await page.getByRole('button', { name: 'Manage projects', exact: true }).click();
  await page.getByRole('button', { name: 'Edit project', exact: true }).click();
  dialog = page.getByRole('dialog');
  await dialog.getByLabel('Project name', { exact: true }).fill('Edited offline project ' + prefix);
  await dialog.getByRole('button', { name: 'Save project', exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole('heading', { name: 'Edited offline project ' + prefix, exact: true })).toBeVisible();
  phase = engine + '-create-edit-transition-comment-link';
  await page.getByRole('button', { name: 'Create item', exact: true }).click();
  dialog = page.getByRole('dialog');
  await dialog.getByLabel('Title', { exact: true }).fill(title);
  await dialog.getByRole('combobox', { name: 'Type', exact: true }).selectOption('story');
  await dialog.getByLabel('Description', { exact: true }).fill('**Local delivered Markdown**');
  await dialog.getByRole('button', { name: 'Create item', exact: true }).click();
  await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
  const key = new URL(page.url()).pathname.slice(1);
  await page.getByRole('button', { name: 'Edit item', exact: true }).click();
  await page.getByRole('dialog').getByLabel('Title', { exact: true }).fill(title + ' edited');
  await page.getByRole('dialog').getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeHidden();
  await page.getByRole('button', { name: 'Change status', exact: true }).click();
  await page.getByRole('combobox', { name: 'New status', exact: true }).selectOption('doing');
  await page.getByRole('dialog').getByRole('button', { name: 'Change status', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeHidden();
  await page.getByLabel('New comment', { exact: true }).fill('**Delivered comment** ' + prefix);
  await page.getByRole('button', { name: 'Add comment', exact: true }).click();
  await expect(page.getByText('Delivered comment ' + prefix, { exact: true })).toBeVisible();
  const targetResponse = await context.request.post(base + '/api/v1/items', { headers: { Origin: origin }, data: { project: prefix, type: 'story', title: 'Link target ' + prefix } });
  assert.equal(targetResponse.status(), 201);
  const target = await targetResponse.json();
  await page.getByRole('button', { name: 'Link item', exact: true }).click();
  await page.getByRole('dialog').getByLabel('Item key', { exact: true }).fill(target.key);
  await page.getByRole('dialog').getByRole('button', { name: 'Add link', exact: true }).click();
  await expect(page.getByRole('dialog').getByRole('status')).toContainText('completed');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toBeHidden();
  await expect(page.getByRole('link', { name: target.key, exact: true })).toBeVisible();
  phase = engine + '-search-reload-bootstrap';
  await page.goto(base + '/?project=' + prefix);
  await page.getByLabel('Search backlog', { exact: true }).fill('status.category = active');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.getByRole('link', { name: title + ' edited', exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('link', { name: title + ' edited', exact: true })).toBeVisible();
  const waterfall = [];
  await page.route('**/api/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.startsWith('/api/v1/items') || path.startsWith('/api/v1/projects')) { waterfall.push(path); return route.abort(); }
    return route.continue();
  });
  for (const [path, name] of [['/', title + ' edited'], ['/?project=' + prefix, title + ' edited'], ['/' + key.toLowerCase() + '/', title + ' edited']]) {
    await page.goto(base + path);
    if (path.startsWith('/?') || path === '/') await expect(page.getByRole('link', { name, exact: true })).toBeVisible();
    else { await expect(page.getByRole('heading', { name, exact: true })).toBeVisible(); await expect(page).toHaveURL(base + '/' + key); }
  }
  assert.deepEqual(waterfall, [], 'First useful content depended on a serialized API request');
  await page.unroute('**/api/v1/**');
  assert.deepEqual(observation.external, [], 'Default workflow attempted a third-party request');
  phase = engine + '-guard-controls';
  await controls(context, observation);
  return { engine, version: context.browser().version(), external_requests: 0, service_workers: 0,
           tls: engine === 'chromium' ? 'leaf-spki-pin' : 'fixture-ca-nss',
           observer_controls: [...observation.controls].sort(),
           checks: ['login', 'create-edit-project', 'create-edit-item', 'transition', 'comment', 'link', 'query-reload', 'cold-bootstrap', 'canonical-deep-link'] };
}

async function networkControl(browser, engine) {
  phase = engine + '-network-control';
  const context = await browser.newContext();
  context.setDefaultTimeout(emulated ? 120000 : 30000);
  const page = await context.newPage();
  const start = Date.now() / 1000;
  try {
    await page.goto(`http://198.51.100.${engine === 'chromium' ? '15' : '17'}:18181/forbidden`, { timeout: 5000 }).catch(() => {});
  } finally {
    await context.close();
    const path = join(process.env.HOME, 'network-controls.json');
    const entries = JSON.parse(readFileSync(path));
    // Date.now() truncates milliseconds; strace timestamps retain microseconds.
    entries.push({ name: engine + '-tcp', start, end: (Date.now()+1) / 1000 });
    writeFileSync(path, JSON.stringify(entries));
  }
}

async function driverControl() {
  const proof = execFileSync('python3', ['-c',
    'import ctypes,errno,os; lib=ctypes.CDLL(None,use_errno=True); lib.syscall.restype=ctypes.c_long; buf=ctypes.create_string_buffer(256); result=lib.syscall(ctypes.c_long(425),ctypes.c_long(2),ctypes.byref(buf)); print("ENOSYS" if result==-1 and ctypes.get_errno()==errno.ENOSYS else "UNOBSERVABLE"); os.close(result) if result>=0 else None'], { encoding: 'utf8', stdio: 'pipe' });
  assert.equal(proof.trim(), 'ENOSYS', 'Browser driver must enforce its recorded syscall policy');
  const familyProof=execFileSync('python3',['-c',[
    'import errno,socket',
    'with socket.socket(socket.AF_INET,socket.SOCK_STREAM): pass',
    'try:',
    '    client=socket.socket(socket.AF_INET6,socket.SOCK_STREAM)',
    'except OSError as error:',
    '    print("IPV4_ONLY" if error.errno in {errno.EAFNOSUPPORT,errno.EPERM,errno.ENOSYS} else "UNEXPECTED")',
    'else:',
    '    client.close(); print("UNRESTRICTED")'
  ].join('\n')],{encoding:'utf8',stdio:'pipe'});
  assert.equal(familyProof.trim(),'IPV4_ONLY','Browser driver must enforce the recorded IPv4 fixture policy');
  const start = Date.now() / 1000;
  let failed = false;
  try { await fetch('http://198.51.100.14:18183/forbidden-driver-fetch', { signal: AbortSignal.timeout(3000) }); }
  catch { failed = true; }
  assert(failed, 'Forbidden driver fetch unexpectedly succeeded');
  const path = join(process.env.HOME, 'network-controls.json');
  const entries = JSON.parse(readFileSync(path));
  entries.push({ name: 'driver-node-fetch', start, end: (Date.now()+1) / 1000 });
  writeFileSync(path, JSON.stringify(entries));
}

async function main() {
  phase = 'driver-policy';
  await driverControl();
  const ca = new X509Certificate(readFileSync(certificate));
  const leaf = new X509Certificate(readFileSync(serverCertificate));
  assert(ca.ca && !leaf.ca && leaf.verify(ca.publicKey), 'A proper fixture CA and signed server leaf are required');
  assert.equal(leaf.checkHost(new URL(base).hostname), new URL(base).hostname);
  const spki = createHash('sha256').update(leaf.publicKey.export({ type: 'spki', format: 'der' })).digest('base64');
  const results = [];
  phase = 'chromium-launch';
  const chrome = await chromium.launch({ headless: true, timeout: launchTimeout, args: ['--ignore-certificate-errors-spki-list=' + spki, '--disable-background-networking'] });
  try { const context = await chrome.newContext({ baseURL: base, serviceWorkers: 'block', ignoreHTTPSErrors: false }); results.push(await core(context, 'chromium')); await context.close(); await networkControl(chrome, 'chromium'); }
  finally { await chrome.close(); }
  const profile = mkdtempSync(join(tmpdir(), 'sierx-firefox-trust-'));
  try {
    phase = 'firefox-launch';
    execFileSync('certutil', ['-N', '--empty-password', '-d', 'sql:' + profile], { stdio: 'pipe' });
    execFileSync('certutil', ['-A', '-n', 'Sierx fixture CA', '-t', 'C,,', '-i', certificate, '-d', 'sql:' + profile], { stdio: 'pipe' });
    const context = await firefox.launchPersistentContext(profile, { headless: true, timeout: firefoxLaunchTimeout, baseURL: base, serviceWorkers: 'block', ignoreHTTPSErrors: false, firefoxUserPrefs });
    try { results.push(await core(context, 'firefox')); }
    finally { await context.close(); }
  } finally { rmSync(profile, { recursive: true, force: true }); }
  phase = 'firefox-network-launch';
  const probe = await firefox.launch({ headless: true, timeout: firefoxLaunchTimeout, firefoxUserPrefs });
  try { await networkControl(probe, 'firefox'); }
  finally { await probe.close(); }
  return { result: 'passed', playwright: JSON.parse(readFileSync('/opt/acceptance/node_modules/playwright/package.json')).version,
    driver: { node: process.version, policy: 'seccomp-deny-io-uring', policy_verified: true, external_fetch_control: true,
              ipv4_only_verified:true, timing_mode: emulated ? 'software-emulation' : 'standard' }, browsers: results };
}

try { console.log(JSON.stringify(await main())); }
catch (error) {
  // stderr is retained only in the private, synthetic guest diagnostic log.
  console.error('offline-browser: failed at ' + phase + ' (' + error.name + '); no passing report');
  console.error(error.stack);
  process.exitCode = 1;
}
