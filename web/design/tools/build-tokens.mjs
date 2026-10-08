#!/usr/bin/env node
// Builds css/tokens.css and css/production.css from tokens/*.json, checks every
// declared colour pair against SPEC §10.3, and writes THEMES.md.
// Zero dependencies. Node 18+.
//
//   node tools/build-tokens.mjs            build + report; exit 1 if a production theme fails
//   node tools/build-tokens.mjs --strict   exit 1 if any theme fails
//   node tools/build-tokens.mjs --check    verify generated files are current; write nothing (CI)

import { readFileSync, writeFileSync, readdirSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { brotliCompressSync, constants } from 'node:zlib';
import { execFileSync } from 'node:child_process';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const args = new Set(process.argv.slice(2));
const read = (p) => readFileSync(join(ROOT, p), 'utf8');
const readJSON = (p) => JSON.parse(read(p));

// ---- the token contract -------------------------------------------------
// SPEC §10.2 names, then sierx extensions (sx-*). Every theme declares every colour.
export const SPEC_COLORS = [
  'background', 'foreground', 'card', 'card-foreground', 'muted', 'muted-foreground',
  'border', 'input', 'ring', 'primary', 'primary-foreground', 'destructive', 'destructive-foreground',
  'status-open', 'status-active', 'status-done', 'status-cancelled',
];
export const EXT_COLORS = [
  'accent', 'accent-foreground',
  'sx-chrome', 'sx-chrome-foreground', 'sx-chrome-muted', 'sx-panel',
  'sx-rule', 'sx-hairline', 'sx-selected', 'sx-selected-foreground', 'sx-selected-muted',
];
const COLORS = [...SPEC_COLORS, ...EXT_COLORS];

// [foreground, background, kind]. text: 4.5:1 (7:1 in HC). ui: 3:1.
// sx-rule and sx-hairline are decorative separators and are deliberately not gated.
export const PAIRS = [
  ['foreground', 'background', 'text'],
  ['muted-foreground', 'background', 'text'],
  ['card-foreground', 'card', 'text'],
  ['muted-foreground', 'card', 'text'],
  ['foreground', 'muted', 'text'],
  ['foreground', 'sx-panel', 'text'],
  ['muted-foreground', 'sx-panel', 'text'],
  ['primary-foreground', 'primary', 'text'],
  ['accent-foreground', 'accent', 'text'],
  ['destructive', 'background', 'text'],
  ['destructive', 'card', 'text'],
  ['destructive-foreground', 'destructive', 'text'],
  ['sx-chrome-foreground', 'sx-chrome', 'text'],
  ['sx-chrome-muted', 'sx-chrome', 'text'],
  ['sx-selected-foreground', 'sx-selected', 'text'],
  ['sx-selected-muted', 'sx-selected', 'text'],
  ['border', 'background', 'ui'],
  ['input', 'background', 'ui'],
  ['ring', 'background', 'ui'],
  ['ring', 'card', 'ui'],
  ['status-open', 'card', 'ui'],
  ['status-active', 'card', 'ui'],
  ['status-done', 'card', 'ui'],
  ['status-cancelled', 'card', 'ui'],
];

// ---- WCAG 2.x relative luminance ---------------------------------------
const HEX = /^#[0-9a-f]{6}$/i;
const lin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const lum = (hex) => {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => lin(v / 255));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
export const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};

// ---- load ---------------------------------------------------------------
const defaults = readJSON('tokens/_defaults.json').tokens;
const production = readJSON('tokens/_production.json');
delete production.$comment;
const files = readdirSync(join(ROOT, 'tokens')).filter((f) => /^\d.*\.json$/.test(f)).sort();
const errors = [];
const themes = files.map((file) => {
  const t = readJSON(`tokens/${file}`);
  t.file = file;
  for (const k of ['id', 'name', 'scheme', 'contrast', 'tokens']) if (!t[k]) errors.push(`${file}: missing "${k}"`);
  for (const k of COLORS) {
    const v = t.tokens?.[k];
    if (v === undefined) errors.push(`${file}: missing colour token "${k}"`);
    else if (!HEX.test(v)) errors.push(`${file}: "${k}" must be #rrggbb, got ${v}`);
  }
  for (const k of Object.keys(t.tokens ?? {})) {
    if (!COLORS.includes(k) && !(k in defaults)) errors.push(`${file}: unknown token "${k}" (typo, or add it to _defaults.json)`);
  }
  for (const [k, v] of Object.entries(t.private ?? {})) {
    if (!HEX.test(v)) errors.push(`${file}: private "${k}" must be #rrggbb`);
  }
  t.all = { ...defaults, ...t.tokens };
  t.set = t.set || 'study';
  return t;
});
const byId = Object.fromEntries(themes.map((t) => [t.id, t]));

// ---- fonts: no third-party faces; rebuild Sierx's own fonts offline --------
const fontSpec = readJSON('fonts/fonts.json');
if ((fontSpec.families ?? []).length) errors.push('fonts: third-party font families are not permitted; use system stacks or Sierx-built faces');
for (const t of themes) if ((t.fonts ?? []).length) errors.push(`${t.file}: third-party font families are not permitted`);

// ---- sierx-drawn faces: compiled from fonts/source, verified by rebuilding --------
// No lock is needed: the source is in the repo and the compiler is reproducible, so a
// fresh build must match the committed bytes exactly.
const built = fontSpec.built ?? [];
try { execFileSync(process.execPath, [join(ROOT, 'tools/build-font.mjs'), '--check'], { stdio: 'pipe' }); }
catch (e) { errors.push(`fonts: ${String(e.stderr || e.message).trim()}`); }
const builtBytes = Object.fromEntries(built.map((fam) => [fam.id, fam.files.reduce((a, f) => {
  const p = join(ROOT, 'fonts/sierx', f.file);
  if (!existsSync(p)) { errors.push(`fonts: fonts/sierx/${f.file} missing. Run node tools/build-font.mjs`); return a; }
  return a + readFileSync(p).length;
}, 0)]));
if (errors.length) {
  console.error(errors.join('\n'));
  process.exit(1);
}
for (const [mode, id] of Object.entries(production)) if (!byId[id]) errors.push(`_production.json: ${mode} -> unknown theme "${id}"`);
if (errors.length) {
  console.error(errors.join('\n'));
  process.exit(1);
}

// ---- contrast -----------------------------------------------------------
const prodIds = new Set(Object.values(production));
for (const t of themes) {
  const vals = { ...t.tokens, ...(t.private ?? {}) };
  const hc = t.contrast === 'high';
  t.results = [...PAIRS, ...(t.pairs ?? [])].map(([fg, bg, kind]) => {
    const min = kind === 'text' ? (hc ? 7 : 4.5) : 3;
    const r = ratio(vals[fg], vals[bg]);
    return { fg, bg, kind, min, r, pass: r >= min - 1e-9 };
  });
  t.failures = t.results.filter((x) => !x.pass);
}

// ---- css ----------------------------------------------------------------
const LAYERS = '@layer sx.reset, sx.tokens, sx.layout, sx.components, sx.theme;';
const decls = (t, indent) => {
  const lines = [`color-scheme: ${t.scheme};`];
  for (const [k, v] of Object.entries(t.all)) lines.push(`--${k}: ${v};`);
  for (const [k, v] of Object.entries(t.private ?? {})) lines.push(`--${k}: ${v};`);
  return lines.map((l) => indent + l).join('\n');
};
const block = (sel, t, indent = '  ') => `${indent}${sel} {\n${decls(t, indent + '  ')}\n${indent}}`;
const banner = (what) => `/* GENERATED by tools/build-tokens.mjs from tokens/*.json. Do not edit by hand.\n   ${what} */\n${LAYERS}\n`;

const tokensCss = banner('Every theme, scoped to [data-theme="<id>"] on any ancestor. The default is the production light theme.') +
  `@layer sx.tokens {\n${block(':where(:root)', byId[production.light])}\n\n` +
  themes.map((t) => block(`[data-theme="${t.id}"]`, t)).join('\n\n') + '\n}\n';

// sierx-drawn faces. Production ships these and nothing else: no third-party font,
// no licence beyond sierx's own, no network at any step.
const face = (family, f, url, range) => `@font-face {\n  font-family: "${family}";\n  font-style: ${f.style || 'normal'};\n  font-weight: ${f.weight};\n  font-display: swap;\n` +
  `  src: url("${url}") format("${url.endsWith('.woff2') ? 'woff2' : 'woff'}");\n  unicode-range: ${range};\n}`;
const builtCss = built.flatMap((fam) => fam.files.map((f) => face(fam.family, f, `../fonts/sierx/${f.file}`, fam.unicodeRange))).join('\n') + '\n';

const SYS = ':root:is([data-theme="system"], :not([data-theme]))';
const prodCss = banner('SPEC §10.2 theme values only. Ship this, not tokens.css, in the sierx build.') + builtCss +
  `@layer sx.tokens {\n` +
  Object.entries(production).map(([mode, id]) => block(`:root[data-theme="${mode}"]`, byId[id])).join('\n\n') + '\n\n' +
  block(SYS, byId[production.light]) + '\n\n' +
  `  @media (prefers-color-scheme: dark) {\n${block(SYS, byId[production.dark], '    ')}\n  }\n\n` +
  `  @media (prefers-contrast: more) {\n${block(SYS, byId[production['light-hc']], '    ')}\n  }\n\n` +
  `  @media (prefers-contrast: more) and (prefers-color-scheme: dark) {\n${block(SYS, byId[production['dark-hc']], '    ')}\n  }\n}\n`;

// ---- sizes (brotli q11, as SPEC §9.1 measures) ---------------------------
const br = (s) => brotliCompressSync(Buffer.from(s), { params: { [constants.BROTLI_PARAM_QUALITY]: 11 } }).length;
const kb = (n) => (n / 1000).toFixed(1) + ' KB';
const base = read('css/base.css');
const themeCss = Object.fromEntries(themes.map((t) => {
  const p = `css/themes/${t.file.replace('.json', '.css')}`;
  return [t.id, existsSync(join(ROOT, p)) ? read(p) : ''];
}));

// ---- fonts.css: same-origin woff2, never a font service -------------------
const fontsCss = `/* GENERATED by tools/build-tokens.mjs from fonts/fonts.json. Do not edit by hand.\n` +
  `   Sierx Mono and Sierx Symbols are compiled from the included source. No third-party\n` +
  `   font files or network-hosted font services are used. */\n` + builtCss;
for (const t of themes) {
  t.fontInfo = [];
  t.fontBytes = 0;
}

// ---- theme-meta.js: what the gallery shows, from the same source --------------
const meta = Object.fromEntries(themes.map((t) => [t.id, {
  name: t.name, set: t.set, scheme: t.scheme, contrast: t.contrast, summary: t.summary,
  overrides: Boolean(themeCss[t.id]), overrideBytes: themeCss[t.id] ? br(themeCss[t.id]) : 0,
  fonts: t.fontInfo, fontBytes: t.fontBytes, pairs: t.results.length, failures: t.failures.length, production: prodIds.has(t.id),
}]));
const builtFiles = built.flatMap((fam) => fam.files.map((f) => ({ family: fam.family, weight: f.weight, file: f.file, bytes: readFileSync(join(ROOT, 'fonts/sierx', f.file)).length })));
const metaJs = `/* GENERATED by tools/build-tokens.mjs. Do not edit by hand. */\nwindow.SierxThemes = ${JSON.stringify(meta, null, 1)};\nwindow.SierxBuiltFonts = ${JSON.stringify(builtFiles, null, 1)};\n`;

// ---- report -------------------------------------------------------------
const pct = (r) => r.toFixed(2);
let md = `# Theme reference\n\nGenerated by \`tools/build-tokens.mjs\`. Do not edit by hand.\n\n`;
md += `## Production mapping (SPEC §10.2)\n\n| \`user_account.theme\` | Study theme |\n|---|---|\n`;
for (const [m, id] of Object.entries(production)) md += `| \`${m}\` | ${byId[id].name} (\`${id}\`) |\n`;
md += `| \`system\` | ${byId[production.light].name} or ${byId[production.dark].name} by \`prefers-color-scheme\`; the HC pair under \`prefers-contrast: more\` |\n\n`;
md += `## Budget (brotli q11)\n\n| File | Size |\n|---|---|\n| css/base.css | ${kb(br(base))} |\n| css/production.css | ${kb(br(prodCss))} |\n| **Production CSS (base + production)** | **${kb(br(base + prodCss))}** of the 20 KB first-route budget |\n| css/tokens.css (all study themes) | ${kb(br(tokensCss))} |\n`;
for (const t of themes) if (themeCss[t.id]) md += `| css/themes/${t.file.replace('.json', '.css')} | ${kb(br(themeCss[t.id]))} |\n`;
md += `\n## Sierx faces, compiled from source\n\nBuilt by \`tools/build-font.mjs\` from \`fonts/source/sierx-mono.mjs\`. Nothing is downloaded at any step, the faces are licensed under sierx's own Apache-2.0, and they are verified by rebuilding: a fresh compile must match the committed bytes. These are the only fonts production ships.\n\n| File | Family | Weight | Size |\n|---|---|---|---|\n`;
for (const f of builtFiles) md += `| fonts/sierx/${f.file} | ${f.family} | ${f.weight} | ${kb(f.bytes)} |\n`;
md += `\n## Typeface policy\n\nThird-party font binaries are excluded. Themes use operating-system font stacks and the Sierx Mono/Symbols faces compiled reproducibly from the included source. The generated font CSS references only same-origin WOFF files.\n`;
md += `\n## Contrast summary\n\nText pairs need 4.5:1, or 7:1 in high-contrast themes. UI pairs need 3:1.\n\n| Theme | Mode | Overrides | Pairs | Failures |\n|---|---|---|---|---|\n`;
for (const t of themes) md += `| ${t.name}${prodIds.has(t.id) ? ' (production)' : ''} | ${t.scheme}${t.contrast === 'high' ? ', HC' : ''} | ${themeCss[t.id] ? 'yes' : 'token-only'} | ${t.results.length} | ${t.failures.length ? t.failures.map((f) => `\`${f.fg}\` on \`${f.bg}\` ${pct(f.r)}`).join('<br>') : 'none'} |\n`;
for (const t of themes) {
  md += `\n## ${t.name} \`${t.id}\`\n\n${t.summary}\n\n| Pair | Kind | Ratio | Min | |\n|---|---|---|---|---|\n`;
  for (const x of t.results) md += `| \`${x.fg}\` on \`${x.bg}\` | ${x.kind} | ${pct(x.r)} | ${x.min} | ${x.pass ? 'pass' : '**fail**'} |\n`;
}

// ---- write or check -----------------------------------------------------
const outputs = { 'css/tokens.css': tokensCss, 'css/production.css': prodCss, 'css/fonts.css': fontsCss, 'reference/theme-meta.js': metaJs, 'THEMES.md': md };
if (args.has('--check')) {
  const stale = Object.entries(outputs).filter(([p, s]) => !existsSync(join(ROOT, p)) || read(p) !== s).map(([p]) => p);
  if (stale.length) { console.error(`Stale generated files: ${stale.join(', ')}. Run node tools/build-tokens.mjs`); process.exit(1); }
} else {
  for (const [p, s] of Object.entries(outputs)) writeFileSync(join(ROOT, p), s);
}

console.log(`Production CSS ${kb(br(base + prodCss))} brotli (base ${kb(br(base))} + production ${kb(br(prodCss))})`);
let bad = false;
for (const t of themes) {
  const gate = prodIds.has(t.id) || args.has('--strict');
  const line = `${t.failures.length ? (gate ? 'FAIL' : 'warn') : ' ok '}  ${t.id.padEnd(10)} ${t.results.length - t.failures.length}/${t.results.length}` +
    (t.failures.length ? '  ' + t.failures.map((f) => `${f.fg}/${f.bg} ${pct(f.r)}<${f.min}`).join(', ') : '');
  console.log(line);
  if (t.failures.length && gate) bad = true;
}
process.exit(bad ? 1 : 0);
