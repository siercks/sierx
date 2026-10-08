#!/usr/bin/env node
// Compiles fonts/source/sierx-mono.mjs into WOFF fonts. No network, no dependencies,
// byte-for-byte reproducible (fixed timestamps, no randomness). Node 18+.
//
//   node tools/build-font.mjs           write fonts/sierx/*.woff
//   node tools/build-font.mjs --check   fail if the committed files differ from a fresh build
//
// Pipeline: stroke centrelines -> outline contours (capsules, arc bands, discs,
// polygons) with quadratic arcs -> TrueType glyf/loca/cmap/hmtx/... -> sfnt -> WOFF 1.0
// (zlib per table). Overlapping contours are allowed (nonzero winding, OVERLAP_SIMPLE).

import { writeFileSync, readFileSync, mkdirSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { deflateSync } from 'node:zlib';
import { createHash } from 'node:crypto';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const SRC = await import(pathToFileURL(join(ROOT, 'fonts/source/sierx-mono.mjs')).href);
const UPM = 1000, ADV = 600, ASC = 800, DESC = -200;
const EPOCH_1904 = 3870000000n; // fixed created/modified stamp keeps the build reproducible

// ---- geometry ---------------------------------------------------------------
const rad = (d) => (d * Math.PI) / 180;
const pt = (cx, cy, rx, ry, a) => ({ x: cx + rx * Math.cos(rad(a)), y: cy + ry * Math.sin(rad(a)), on: true });
/** Points from a0 to a1 (exclusive of start, inclusive of end) as quadratic segments of at most 30 degrees. */
function arcPts(cx, cy, rx, ry, a0, a1) {
  const n = Math.max(1, Math.ceil(Math.abs(a1 - a0) / 30)), step = (a1 - a0) / n, k = 1 / Math.cos(rad(step / 2)), out = [];
  for (let i = 0; i < n; i++) {
    const t0 = a0 + step * i, tm = t0 + step / 2, t1 = t0 + step;
    out.push({ x: cx + rx * Math.cos(rad(tm)) * k, y: cy + ry * Math.sin(rad(tm)) * k, on: false });
    out.push(pt(cx, cy, rx, ry, t1));
  }
  return out;
}
const ellipse = (cx, cy, rx, ry) => [pt(cx, cy, rx, ry, 0), ...arcPts(cx, cy, rx, ry, 0, 360).slice(0, -1)];

function makeGlyph(draw, m) {
  const contours = []; // { pts, hole }
  const w = m.w;
  const g = {
    line(x1, y1, x2, y2) {
      if (x1 === x2 && y1 === y2) return g.dot(x1, y1, w);
      const th = (Math.atan2(y2 - y1, x2 - x1) * 180) / Math.PI;
      contours.push({ pts: [pt(x1, y1, w, w, th + 90), pt(x2, y2, w, w, th + 90), ...arcPts(x2, y2, w, w, th + 90, th - 90),
        pt(x1, y1, w, w, th - 90), ...arcPts(x1, y1, w, w, th - 90, th - 270).slice(0, -1)] });
    },
    path(points) { for (let i = 1; i < points.length; i++) g.line(...points[i - 1], ...points[i]); },
    arc(cx, cy, rx, ry, a0, a1) {
      if (a1 - a0 >= 360) return g.ring(cx, cy, rx, ry);
      const e = pt(cx, cy, rx, ry, a1), s = pt(cx, cy, rx, ry, a0);
      contours.push({ pts: [pt(cx, cy, rx + w, ry + w, a0), ...arcPts(cx, cy, rx + w, ry + w, a0, a1), ...arcPts(e.x, e.y, w, w, a1, a1 + 180),
        ...arcPts(cx, cy, rx - w, ry - w, a1, a0), ...arcPts(s.x, s.y, w, w, a0 + 180, a0 + 360).slice(0, -1)] });
    },
    ring(cx, cy, rx, ry) {
      contours.push({ pts: ellipse(cx, cy, rx + w, ry + w) });
      contours.push({ pts: ellipse(cx, cy, rx - w, ry - w), hole: true });
    },
    dot(cx, cy, r) { contours.push({ pts: ellipse(cx, cy, r, r) }); },
    poly(points) { contours.push({ pts: points.map(([x, y]) => ({ x, y, on: true })) }); },
    pie(cx, cy, r, a0, a1) { contours.push({ pts: [{ x: cx, y: cy, on: true }, pt(cx, cy, r, r, a0), ...arcPts(cx, cy, r, r, a0, a1)] }); },
  };
  draw(g, m);
  // Integer grid, drop repeated points, then orient: outer contours clockwise, holes anticlockwise.
  return contours.map(({ pts, hole }) => {
    let p = pts.map((q) => ({ x: Math.round(q.x), y: Math.round(q.y), on: q.on }));
    p = p.filter((q, i) => { const n = p[(i + 1) % p.length]; return !(n.x === q.x && n.y === q.y && n.on === q.on); });
    let area = 0;
    for (let i = 0; i < p.length; i++) { const a = p[i], b = p[(i + 1) % p.length]; area += a.x * b.y - b.x * a.y; }
    if ((area > 0) !== Boolean(hole)) p.reverse();
    while (!p[0].on) p.push(p.shift()); // a contour must start on-curve
    return p;
  }).filter((p) => p.length >= 3);
}

// ---- binary helpers -----------------------------------------------------------
class W {
  constructor() { this.b = []; }
  u8(v) { this.b.push(v & 255); return this; }
  u16(v) { return this.u8(v >> 8).u8(v); }
  i16(v) { return this.u16(v < 0 ? v + 65536 : v); }
  u32(v) { return this.u16(Math.floor(v / 65536) & 65535).u16(v & 65535); }
  i64(v) { for (let s = 56n; s >= 0n; s -= 8n) this.u8(Number((v >> s) & 255n)); return this; }
  tag(s) { for (const ch of s) this.u8(ch.charCodeAt(0)); return this; }
  bytes(a) { for (const x of a) this.u8(x); return this; }
  pad4() { while (this.b.length % 4) this.u8(0); return this; }
  buf() { return Buffer.from(this.b); }
}
const checksum = (buf) => { const p = Buffer.concat([buf, Buffer.alloc((4 - (buf.length % 4)) % 4)]); let s = 0; for (let i = 0; i < p.length; i += 4) s = (s + p.readUInt32BE(i)) >>> 0; return s; };

function encodeGlyph(contours) {
  if (!contours.length) return Buffer.alloc(0);
  const all = contours.flat();
  const xs = all.map((p) => p.x), ys = all.map((p) => p.y);
  const w = new W().i16(contours.length).i16(Math.min(...xs)).i16(Math.min(...ys)).i16(Math.max(...xs)).i16(Math.max(...ys));
  let end = -1; for (const c of contours) { end += c.length; w.u16(end); }
  w.u16(0); // no instructions
  const flags = [], xb = new W(), yb = new W(); let px = 0, py = 0;
  all.forEach((p, i) => {
    let f = p.on ? 1 : 0; const dx = p.x - px, dy = p.y - py; px = p.x; py = p.y;
    if (dx === 0) f |= 0x10; else if (Math.abs(dx) < 256) { f |= 0x02 | (dx > 0 ? 0x10 : 0); xb.u8(Math.abs(dx)); } else xb.i16(dx);
    if (dy === 0) f |= 0x20; else if (Math.abs(dy) < 256) { f |= 0x04 | (dy > 0 ? 0x20 : 0); yb.u8(Math.abs(dy)); } else yb.i16(dy);
    if (i === 0) f |= 0x40; // OVERLAP_SIMPLE
    flags.push(f);
  });
  return w.bytes(flags).bytes(xb.b).bytes(yb.b).buf();
}

// ---- tables ---------------------------------------------------------------------
function buildFont({ family, style, weight, w, include }) {
  const m = SRC.metrics(w);
  const src = SRC.glyphs.filter(([cp]) => !include || include.has(cp) || cp === 0x20).sort((a, b) => a[0] - b[0]);
  const notdef = makeGlyph((g) => { g.path([[m.l, m.b], [m.r, m.b], [m.r, m.cap], [m.l, m.cap], [m.l, m.b]]); }, m);
  const glyphs = [{ cp: null, contours: notdef }, ...src.map(([cp, draw]) => ({ cp, contours: makeGlyph(draw, m) }))];
  const data = glyphs.map((gl) => encodeGlyph(gl.contours));
  const bbox = (gl) => { const a = gl.contours.flat(); return a.length ? [Math.min(...a.map((p) => p.x)), Math.min(...a.map((p) => p.y)), Math.max(...a.map((p) => p.x)), Math.max(...a.map((p) => p.y))] : [0, 0, 0, 0]; };
  const boxes = glyphs.map(bbox);
  const inked = boxes.filter((b, i) => glyphs[i].contours.length);
  const [xMin, yMin, xMax, yMax] = [Math.min(...inked.map((b) => b[0])), Math.min(...inked.map((b) => b[1])), Math.max(...inked.map((b) => b[2])), Math.max(...inked.map((b) => b[3]))];

  const glyf = new W(), loca = new W();
  for (const d of data) { loca.u32(glyf.b.length); glyf.bytes(d).pad4(); }
  loca.u32(glyf.b.length);

  const hmtx = new W(); boxes.forEach((b, i) => hmtx.u16(ADV).i16(glyphs[i].contours.length ? b[0] : 0));

  // cmap format 4, one segment per run of consecutive codepoints
  const cps = glyphs.slice(1).map((g, i) => [g.cp, i + 1]);
  const segs = [];
  for (const [cp, gid] of cps) {
    const s = segs[segs.length - 1];
    if (s && cp === s.end + 1 && gid === s.gid + (cp - s.start)) s.end = cp; else segs.push({ start: cp, end: cp, gid });
  }
  segs.push({ start: 0xffff, end: 0xffff, gid: 0, delta: 1 });
  const n = segs.length, sr = 2 * 2 ** Math.floor(Math.log2(n));
  const f4 = new W().u16(4).u16(16 + 8 * n).u16(0).u16(n * 2).u16(sr).u16(Math.log2(sr / 2)).u16(n * 2 - sr);
  segs.forEach((s) => f4.u16(s.end)); f4.u16(0); segs.forEach((s) => f4.u16(s.start));
  segs.forEach((s) => f4.u16(s.delta ?? ((s.gid - s.start + 65536) % 65536))); segs.forEach(() => f4.u16(0));
  const cmap = new W().u16(0).u16(2).u16(0).u16(3).u32(20).u16(3).u16(1).u32(20).bytes(f4.b);

  const bold = weight >= 700;
  const head = new W().u32(0x00010000).u32(0x00010000).u32(0).u32(0x5f0f3cf5).u16(0x0003).u16(UPM).i64(EPOCH_1904).i64(EPOCH_1904)
    .i16(xMin).i16(yMin).i16(xMax).i16(yMax).u16(bold ? 1 : 0).u16(8).i16(2).i16(1).i16(0);
  const lsbs = boxes.map((b) => b[0]), rsbs = boxes.map((b) => ADV - b[2]);
  const hhea = new W().u32(0x00010000).i16(ASC).i16(DESC).i16(0).u16(ADV).i16(Math.min(...lsbs)).i16(Math.min(...rsbs)).i16(xMax)
    .i16(1).i16(0).i16(0).i16(0).i16(0).i16(0).i16(0).i16(0).u16(glyphs.length);
  const maxPts = Math.max(...glyphs.map((g) => g.contours.flat().length)), maxCont = Math.max(...glyphs.map((g) => g.contours.length));
  const maxp = new W().u32(0x00010000).u16(glyphs.length).u16(maxPts).u16(maxCont).u16(0).u16(0).u16(2).u16(0).u16(0).u16(0).u16(0).u16(0).u16(0).u16(0).u16(0);
  const firstCp = cps[0][0], lastCp = cps[cps.length - 1][0];
  const os2 = new W().u16(4).i16(ADV).u16(weight).u16(5).u16(0)
    .i16(650).i16(600).i16(0).i16(75).i16(650).i16(600).i16(0).i16(350).i16(2 * w).i16(300).i16(0)
    .bytes([2, 11, bold ? 8 : 5, 9, 0, 0, 0, 0, 0, 0])
    .u32(0x80000003).u32(0x0000e060).u32(0).u32(0).tag('SIRX')
    .u16((bold ? 0x20 : 0x40) | 0x80).u16(firstCp).u16(Math.min(lastCp, 0xffff))
    .i16(ASC).i16(DESC).i16(0).u16(Math.max(yMax, ASC)).u16(Math.max(-yMin, -DESC))
    .u32(1).u32(0).i16(520).i16(700).u16(0).u16(32).u16(2);
  const post = new W().u32(0x00030000).u32(0).i16(-120).i16(2 * w).u32(1).u32(0).u32(0).u32(0).u32(0);

  const ps = family.replace(/\s/g, '') + '-' + style;
  const names = [[0, 'Copyright 2026 the sierx authors'], [1, family], [2, style], [3, `${ps};1.000`], [4, `${family} ${style}`],
    [5, 'Version 1.000'], [6, ps], [13, 'Licensed under the Apache License, Version 2.0'], [14, 'https://www.apache.org/licenses/LICENSE-2.0']];
  const strs = names.map(([, s]) => Buffer.from(s, 'utf16le').swap16());
  const name = new W().u16(0).u16(names.length).u16(6 + 12 * names.length);
  let off = 0; names.forEach(([id], i) => { name.u16(3).u16(1).u16(0x409).u16(id).u16(strs[i].length).u16(off); off += strs[i].length; });
  strs.forEach((s) => name.bytes(s));

  const tables = { 'OS/2': os2, cmap, glyf, head, hhea, hmtx, loca, maxp, name, post };
  const tags = Object.keys(tables).sort();
  const nt = tags.length, srT = 16 * 2 ** Math.floor(Math.log2(nt));
  const dir = new W().u32(0x00010000).u16(nt).u16(srT).u16(Math.log2(srT / 16)).u16(nt * 16 - srT);
  let offset = 12 + 16 * nt; const bodies = [];
  for (const t of tags) { const b = tables[t].buf(); dir.tag(t).u32(checksum(b)).u32(offset).u32(b.length); bodies.push(b); offset += b.length + ((4 - (b.length % 4)) % 4); }
  const pad = (b) => Buffer.concat([b, Buffer.alloc((4 - (b.length % 4)) % 4)]);
  let sfnt = Buffer.concat([dir.buf(), ...bodies.map(pad)]);
  const adj = (0xb1b0afba - checksum(sfnt)) >>> 0;
  const headOff = 12 + 16 * nt + bodies.slice(0, tags.indexOf('head')).reduce((a, b) => a + pad(b).length, 0);
  sfnt.writeUInt32BE(adj, headOff + 8);
  bodies[tags.indexOf('head')].writeUInt32BE(adj, 8);

  // WOFF 1.0
  const entries = tags.map((t, i) => { const orig = bodies[i], z = deflateSync(orig, { level: 9 }); return { t, orig, data: z.length < orig.length ? z : orig }; });
  const woffDir = new W(); let wOff = 44 + 20 * nt; const chunks = [];
  for (const e of entries) { woffDir.tag(e.t).u32(wOff).u32(e.data.length).u32(e.orig.length).u32(checksum(e.orig)); chunks.push(pad(e.data)); wOff += pad(e.data).length; }
  const header = new W().tag('wOFF').u32(0x00010000).u32(wOff).u16(nt).u16(0).u32(sfnt.length).u16(1).u16(0).u32(0).u32(0).u32(0).u32(0).u32(0);
  return { woff: Buffer.concat([header.buf(), woffDir.buf(), ...chunks]), glyphCount: glyphs.length };
}

// ---- outputs ------------------------------------------------------------------
const OUT = [
  { file: 'sierx-mono-400.woff', family: 'Sierx Mono', style: 'Regular', weight: 400, w: 40 },
  { file: 'sierx-mono-700.woff', family: 'Sierx Mono', style: 'Bold', weight: 700, w: 60 },
  { file: 'sierx-symbols-400.woff', family: 'Sierx Symbols', style: 'Regular', weight: 400, w: 40, include: new Set(SRC.symbols) },
  { file: 'sierx-symbols-700.woff', family: 'Sierx Symbols', style: 'Bold', weight: 700, w: 60, include: new Set(SRC.symbols) },
];
const dir = join(ROOT, 'fonts/sierx');
mkdirSync(dir, { recursive: true });
let stale = [];
for (const o of OUT) {
  const { woff, glyphCount } = buildFont(o);
  const p = join(dir, o.file);
  if (process.argv.includes('--check')) { if (!existsSync(p) || !readFileSync(p).equals(woff)) stale.push(o.file); continue; }
  writeFileSync(p, woff);
  console.log(`${o.file.padEnd(24)} ${String(glyphCount).padStart(3)} glyphs  ${(woff.length / 1000).toFixed(1)} KB  sha256 ${createHash('sha256').update(woff).digest('hex').slice(0, 16)}…`);
}
if (stale.length) { console.error(`Stale or modified built fonts: ${stale.join(', ')}. Run node tools/build-font.mjs`); process.exit(1); }
