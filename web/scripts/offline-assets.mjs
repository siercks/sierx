import assert from 'node:assert/strict';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';

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
    for (const [, target] of content.matchAll(/(?:src|href)=["']([^"']+)["']/gi)) {
      if (/^(?:data:|#|https?:\/\/|\/\/)/i.test(target)) continue;
      if (/\.(?:js|css)(?:[?#]|$)/i.test(target))
        assert(
          !/[?#]/.test(target),
          `${file} adds a query or fragment to a JavaScript/CSS entry URL; version its filename so lazy imports share the same module URL`,
        );
      const local = target.startsWith('/') ? resolve('dist', `.${target}`) : resolve(dirname(file), target);
      assert(existsSync(local), `${file} references missing local asset ${target}`);
    }
  }
}

console.log(`offline assets: ${scanned.length} CSS/HTML files checked; no OFL fonts or remote references`);
