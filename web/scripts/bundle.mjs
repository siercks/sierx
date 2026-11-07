import { readFileSync, writeFileSync, readdirSync } from 'node:fs';
import { brotliCompressSync, gzipSync, constants } from 'node:zlib';
import assert from 'node:assert/strict';
import { assertLazyModules } from './bundle-contract.mjs';
const manifest = JSON.parse(readFileSync('dist/.vite/manifest.json', 'utf8'));
const entry = Object.entries(manifest).find(([, v]) => v.isEntry)?.[0];
assert(entry, 'Missing entry');
const initial = new Set();
function visit(key) {
  if (initial.has(key)) return;
  initial.add(key);
  for (const k of manifest[key].imports ?? []) visit(k);
}
visit(entry);
const sizes = new Map();
for (const file of readdirSync('dist/assets')) {
  if (!/\.(js|css)$/.test(file)) continue;
  const data = readFileSync(`dist/assets/${file}`);
  const br = brotliCompressSync(data, {
    params: { [constants.BROTLI_PARAM_QUALITY]: 11 },
  });
  writeFileSync(`dist/assets/${file}.br`, br);
  writeFileSync(`dist/assets/${file}.gz`, gzipSync(data, { level: 9 }));
  sizes.set(`assets/${file}`, br.length);
}
const scripts = new Set([...initial].map((k) => manifest[k].file));
const css = new Set([...initial].flatMap((k) => manifest[k].css ?? []));
const jsBytes = [...scripts].reduce((n, f) => n + sizes.get(f), 0);
const cssBytes = [...css].reduce((n, f) => n + sizes.get(f), 0);
function budgets(js, css, lazy) {
  assert(js <= 250000, `Initial JS ${js} > 250000 bytes`);
  assert(css <= 20000, `Initial CSS ${css} > 20000 bytes`);
  for (const [f, bytes] of lazy)
    assert(bytes <= 60000, `${f}: ${bytes} > 60000 bytes`);
}
const lazy = [...sizes].filter(([f]) => f.endsWith('.js') && !scripts.has(f));
budgets(jsBytes, cssBytes, lazy);
const modules = JSON.parse(readFileSync('dist/modules.json', 'utf8'));
assertLazyModules(scripts, modules);
const report = {
  convention:
    'decimal KB, Brotli quality 11; unique entry + transitive static imports and CSS',
  initialJS: jsBytes,
  initialCSS: cssBytes,
  lazy: Object.fromEntries(lazy),
};
writeFileSync('dist/budget.json', JSON.stringify(report, null, 2));
if (process.argv.includes('--prove')) {
  assert.throws(() => budgets(250001, 0, []));
  assert.throws(() => budgets(0, 20001, []));
  assert.throws(() => budgets(0, 0, [['large import', 60001]]));
  for (const module of [
    'src/routes/Board.tsx', 'src/routes/AccountSecurity.tsx',
    'src/components/AvatarEditor.tsx', 'src/components/DatePicker.tsx',
    'node_modules/@dnd-kit/core/dist/core.js',
  ]) {
    const planted = structuredClone(modules);
    planted[[...scripts][0]].push(module);
    assert.throws(() => assertLazyModules(scripts, planted), /entered eager graph/);
  }
  console.log('bundle proofs: initial JS/CSS and lazy excess rejected');
}
console.log(JSON.stringify(report, null, 2));
