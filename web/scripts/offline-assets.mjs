import assert from 'node:assert/strict';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { parseHTML } from 'linkedom';

const fontManifest = JSON.parse(readFileSync('design/fonts/fonts.json', 'utf8'));
assert.equal(fontManifest.families?.length ?? 0, 0, 'third-party font families are forbidden');
const builtFaces = fontManifest.built ?? [];
for (const face of builtFaces) assert.equal(face.license, 'Apache-2.0', `${face.id}: only Sierx Apache-2.0 faces may ship`);
for (const file of readdirSync('design/tokens').filter((name) => /^\d.*\.json$/.test(name))) {
  const theme = JSON.parse(readFileSync(join('design/tokens', file), 'utf8'));
  assert.equal(theme.fonts?.length ?? 0, 0, `${theme.id}: third-party font declarations are forbidden`);
}
assert(!existsSync('design/fonts/third-party'), 'third-party font files must not be bundled');

function walk(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? walk(path) : [path];
  });
}
const declaredFonts = new Set(builtFaces.flatMap((face) => face.files.map((file) => file.file)));
for (const path of walk('design/fonts/sierx'))
  assert(declaredFonts.has(path.split(/[\\/]/).at(-1)), `${path} is not declared as a built Sierx face`);

const external = /(?:@import\s+(?:url\()?\s*['"]?https?:\/\/|url\(\s*['"]?https?:\/\/|url\(\s*['"]?\/\/)/i;

function htmlResources(content) {
  const { document } = parseHTML(content);
  const resourceAttrs = [
    ['script[src],iframe[src],frame[src],img[src],source[src],video[src],audio[src],track[src],embed[src],input[type="image"][src]', 'src'],
    ['video[poster]', 'poster'],
    ['object[data]', 'data'],
    ['img[srcset],source[srcset]', 'srcset'],
  ];
  const resources = [];
  for (const [selector, attribute] of resourceAttrs) {
    for (const element of document.querySelectorAll(selector)) {
      const raw = element.getAttribute(attribute) ?? '';
      if (attribute === 'srcset') {
        for (const entry of raw.split(',')) resources.push(entry.trim().split(/\s+/)[0]);
      } else resources.push(raw);
    }
  }
  for (const link of document.querySelectorAll('link[href]')) {
    const rel = (link.getAttribute('rel') ?? '').toLowerCase().split(/\s+/);
    if (rel.some((value) => ['stylesheet', 'preload', 'modulepreload', 'icon', 'apple-touch-icon', 'manifest', 'prefetch', 'preconnect', 'dns-prefetch'].includes(value)))
      resources.push(link.getAttribute('href'));
  }
  for (const base of document.querySelectorAll('base[href]')) resources.push(base.getAttribute('href'));
  return resources;
}

function assertLocalHTMLResources(file, content, checkPath) {
  for (const target of htmlResources(content)) {
    if (!target || /^(?:data:|blob:|#)/i.test(target)) continue;
    assert(!/^(?:https?:)?\/\//i.test(target), `${file} automatically fetches a remote resource`);
    if (/\.(?:js|css)(?:[?#]|$)/i.test(target))
      assert(!/[?#]/.test(target), `${file} adds a query or fragment to a JavaScript/CSS entry URL; version its filename so lazy imports share the same module URL`);
    const path = target.split(/[?#]/, 1)[0];
    const local = path.startsWith('/') ? resolve('dist', `.${path}`) : resolve(dirname(checkPath), path);
    assert(existsSync(local), `${file} references missing local asset ${target}`);
  }
}

if (process.argv.includes('--prove')) {
  for (const fixture of [
    '<script src="https://example.test/app.js"></script>',
    '<link rel="stylesheet" href="//example.test/app.css">',
    '<img src="https://example.test/image.png">',
  ]) {
    let rejected = false;
    try { assertLocalHTMLResources('<fixture>', fixture, resolve('dist', 'fixture.html')); }
    catch (error) { rejected = /automatically fetches a remote resource/.test(String(error)); }
    assert(rejected, 'remote script, stylesheet, or image fixture was accepted');
  }
  assertLocalHTMLResources('<fixture>', '<a href="https://example.test/read-more">Read more</a>', resolve('dist', 'fixture.html'));
  console.log('offline asset proof: remote script, stylesheet and image rejected; clicked external link allowed');
}

const files = [...walk('design/css'), ...walk('design/fonts')];
if (existsSync('dist')) files.push(...walk('dist'));
const scanned = files.filter((file) => /\.(?:css|html)$/i.test(file));
for (const file of scanned) {
  const content = readFileSync(file, 'utf8');
  assert(!external.test(content), `${file} contains a remote stylesheet or asset reference`);
  if (file.endsWith('.css')) {
    for (const [, target] of content.matchAll(/url\(\s*['"]?([^)'"\s]+)['"]?\s*\)/gi)) {
      if (target.startsWith('data:') || target.startsWith('#')) continue;
      const local = target.startsWith('/') ? resolve('dist', `.${target}`) : resolve(dirname(file), target);
      assert(existsSync(local), `${file} references missing local asset ${target}`);
    }
  }
  if (file.endsWith('.html')) {
    assertLocalHTMLResources(file, content, file);
  }
}

console.log(`offline assets: ${scanned.length} CSS/HTML files checked; no OFL fonts or automatically fetched remote resources`);
