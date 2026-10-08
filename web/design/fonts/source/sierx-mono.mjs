// Sierx Mono: glyph source.
// Copyright 2026 the sierx authors. Licensed under the Apache License, Version 2.0.
//
// A monoline geometric monospace, drawn as stroke centrelines on a 1000-unit em
// with a 600-unit advance. tools/build-font.mjs expands each stroke to an outline
// at the requested weight, so Regular and Bold come from this one file: weight is
// only the stroke width. Every glyph is a function of the metrics, so changing
// x-height or stroke width re-draws the whole face consistently.
//
// The sierx status and type glyphs are drawn on the same grid as the letters, so
// ○ ◐ ● ⊘ sit on the x-height centre and match stroke weight in every theme.
//
// Helpers (g): line, path, arc (a0 < a1, degrees, counter-clockwise from +x),
// ring (closed ellipse), dot (filled disc), poly (filled polygon), pie (filled sector).

export const family = 'Sierx Mono';

/** Metrics for a half-stroke width w. Centrelines sit inside the metric lines by w,
    so outer edges land on baseline, x-height and cap height. */
export function metrics(w) {
  const m = { w, o: 10, c: 300, ax: 320 };
  m.b = w; m.x = 520 - w; m.cap = 700 - w; m.asc = 750 - w; m.dsc = -200 + w;
  m.l = 82 + w; m.r = 518 - w;
  m.cy = (m.b + m.x) / 2; m.Cy = (m.b + m.cap) / 2;
  m.rx = (m.r - m.l) / 2; m.ry = (m.x - m.b) / 2; m.Ry = (m.cap - m.b) / 2;
  m.rd = Math.round(w * 1.35); m.dotY = m.rd;         // a dot sits on the baseline
  m.W = m.r - m.l; m.H = m.cap - m.b;
  return m;
}

const at = (cx, cy, rx, ry, a) => [cx + rx * Math.cos(a * Math.PI / 180), cy + ry * Math.sin(a * Math.PI / 180)];

/** Each entry: [codepoint, draw(g, m)]. */
export const glyphs = [
  // ---- lowercase -------------------------------------------------------
  [0x61, (g, m) => { g.ring(m.c, m.cy, m.rx, m.ry + m.o); g.line(m.r, m.b, m.r, m.x); }],                       // a
  [0x62, (g, m) => { g.line(m.l, m.b, m.l, m.asc); g.ring(m.c, m.cy, m.rx, m.ry + m.o); }],                     // b
  [0x63, (g, m) => { g.arc(m.c, m.cy, m.rx, m.ry + m.o, 42, 318); }],                                             // c
  [0x64, (g, m) => { g.ring(m.c, m.cy, m.rx, m.ry + m.o); g.line(m.r, m.b, m.r, m.asc); }],                     // d
  [0x65, (g, m) => { g.line(m.l, m.cy, m.r, m.cy); g.arc(m.c, m.cy, m.rx, m.ry + m.o, 0, 322); }],              // e
  [0x66, (g, m) => { const s = m.c - 40, k = 125; g.line(s, m.b, s, m.asc - k); g.arc(s + k, m.asc - k, k, k, 30, 180); g.line(m.l, m.x, m.r - 30, m.x); }], // f
  [0x67, (g, m) => { g.ring(m.c, m.cy, m.rx, m.ry + m.o); const h = 125; g.line(m.r, m.x, m.r, m.dsc + h); g.arc(m.c, m.dsc + h, m.rx, h, 200, 360); }], // g
  [0x68, (g, m) => { g.line(m.l, m.b, m.l, m.asc); g.arc(m.c, m.x - m.rx, m.rx, m.rx, 0, 180); g.line(m.r, m.b, m.r, m.x - m.rx); }], // h
  [0x69, (g, m) => { g.line(m.c, m.b, m.c, m.x); g.line(m.c - 130, m.x, m.c, m.x); g.line(m.l + 20, m.b, m.r - 20, m.b); g.dot(m.c, m.x + 185, m.rd); }], // i
  [0x6a, (g, m) => { const s = m.c + 60, k = 135; g.line(s, m.x, s, m.dsc + k); g.arc(s - k, m.dsc + k, k, k, 200, 360); g.line(s - 140, m.x, s, m.x); g.dot(s, m.x + 185, m.rd); }], // j
  [0x6b, (g, m) => { const j = [m.l, m.cy - 30]; g.line(m.l, m.b, m.l, m.asc); g.line(j[0], j[1], m.r, m.x); const t = 0.38; g.line(j[0] + t * (m.r - j[0]), j[1] + t * (m.x - j[1]), m.r, m.b); }], // k
  [0x6c, (g, m) => { g.line(m.c, m.b, m.c, m.asc); g.line(m.c - 130, m.asc, m.c, m.asc); g.line(m.l + 20, m.b, m.r - 20, m.b); }], // l
  [0x6d, (g, m) => { const a = (m.c - m.l) / 2, b2 = (m.r - m.c) / 2; g.line(m.l, m.b, m.l, m.x); g.arc(m.l + a, m.x - a, a, a, 0, 180); g.line(m.c, m.b, m.c, m.x - a); g.arc(m.c + b2, m.x - b2, b2, b2, 0, 180); g.line(m.r, m.b, m.r, m.x - b2); }], // m
  [0x6e, (g, m) => { g.line(m.l, m.b, m.l, m.x); g.arc(m.c, m.x - m.rx, m.rx, m.rx, 0, 180); g.line(m.r, m.b, m.r, m.x - m.rx); }], // n
  [0x6f, (g, m) => { g.ring(m.c, m.cy, m.rx, m.ry + m.o); }],                                                     // o
  [0x70, (g, m) => { g.line(m.l, m.x, m.l, m.dsc); g.ring(m.c, m.cy, m.rx, m.ry + m.o); }],                     // p
  [0x71, (g, m) => { g.ring(m.c, m.cy, m.rx, m.ry + m.o); g.line(m.r, m.x, m.r, m.dsc); }],                     // q
  [0x72, (g, m) => { g.line(m.l, m.b, m.l, m.x); g.arc(m.l + m.rx, m.x - m.rx, m.rx, m.rx, 55, 180); }],       // r
  [0x73, (g, m) => { const h = (m.x - m.b) / 4 + 2; g.arc(m.c, m.cy + h, m.rx * 0.92, h + m.o / 2, 35, 270); g.arc(m.c, m.cy - h, m.rx, h + m.o / 2, -145, 90); }], // s
  [0x74, (g, m) => { const s = m.c - 50, k = 125; g.line(s, m.asc - 90, s, m.b + k); g.arc(s + k, m.b + k, k, k, 180, 300); g.line(m.l, m.x, m.r - 20, m.x); }], // t
  [0x75, (g, m) => { g.line(m.l, m.x, m.l, m.b + m.rx); g.arc(m.c, m.b + m.rx, m.rx, m.rx, 180, 360); g.line(m.r, m.x, m.r, m.b); }], // u
  [0x76, (g, m) => { g.path([[m.l, m.x], [m.c, m.b], [m.r, m.x]]); }],                                          // v
  [0x77, (g, m) => { const q = m.W * 0.25; g.path([[m.l, m.x], [m.l + q, m.b], [m.c, m.x - 170], [m.r - q, m.b], [m.r, m.x]]); }], // w
  [0x78, (g, m) => { g.line(m.l, m.b, m.r, m.x); g.line(m.l, m.x, m.r, m.b); }],                                 // x
  [0x79, (g, m) => { const e = [m.l + 50, m.dsc]; g.line(m.r, m.x, e[0], e[1]); const t = (m.x - m.b) / (m.x - m.dsc); g.line(m.l, m.x, m.r + t * (e[0] - m.r), m.b); }], // y
  [0x7a, (g, m) => { g.path([[m.l, m.x], [m.r, m.x], [m.l, m.b], [m.r, m.b]]); }],                              // z

  // ---- uppercase -------------------------------------------------------
  [0x41, (g, m) => { g.path([[m.l, m.b], [m.c, m.cap], [m.r, m.b]]); const y = m.b + m.H * 0.32, f = (y - m.b) / m.H; g.line(m.l + f * (m.c - m.l), y, m.r - f * (m.r - m.c), y); }], // A
  [0x42, (g, m) => { const my = m.b + m.H * 0.54, r1 = (m.cap - my) / 2, r2 = (my - m.b) / 2, k1 = m.r - 28 - r1, k2 = m.r - r2;
    g.line(m.l, m.b, m.l, m.cap); g.line(m.l, m.cap, k1, m.cap); g.arc(k1, m.cap - r1, r1, r1, -90, 90); g.line(k1, my, m.l, my);
    g.line(m.l, my, k2, my); g.arc(k2, m.b + r2, r2, r2, -90, 90); g.line(k2, m.b, m.l, m.b); }],             // B
  [0x43, (g, m) => { g.arc(m.c, m.Cy, m.rx, m.Ry + m.o, 40, 320); }],                                             // C
  [0x44, (g, m) => { const rx = m.W * 0.6, k = m.r - rx; g.line(m.l, m.b, m.l, m.cap); g.line(m.l, m.cap, k, m.cap); g.arc(k, m.Cy, rx, m.Ry, -90, 90); g.line(k, m.b, m.l, m.b); }], // D
  [0x45, (g, m) => { g.path([[m.r, m.cap], [m.l, m.cap], [m.l, m.b], [m.r, m.b]]); g.line(m.l, m.Cy + 10, m.r - 50, m.Cy + 10); }], // E
  [0x46, (g, m) => { g.path([[m.r, m.cap], [m.l, m.cap], [m.l, m.b]]); g.line(m.l, m.Cy + 10, m.r - 50, m.Cy + 10); }], // F
  [0x47, (g, m) => { g.arc(m.c, m.Cy, m.rx, m.Ry + m.o, 42, 360); g.line(m.c + 30, m.Cy, m.r, m.Cy); }],         // G
  [0x48, (g, m) => { g.line(m.l, m.b, m.l, m.cap); g.line(m.r, m.b, m.r, m.cap); g.line(m.l, m.Cy, m.r, m.Cy); }], // H
  [0x49, (g, m) => { g.line(m.c, m.b, m.c, m.cap); g.line(m.l + 40, m.cap, m.r - 40, m.cap); g.line(m.l + 40, m.b, m.r - 40, m.b); }], // I
  [0x4a, (g, m) => { const s = m.r - 30, k = (s - m.l) / 2; g.line(s, m.cap, s, m.b + k); g.arc(s - k, m.b + k, k, k, 180, 360); g.line(m.l + 90, m.cap, s, m.cap); }], // J
  [0x4b, (g, m) => { const j = [m.l, m.Cy - 40]; g.line(m.l, m.b, m.l, m.cap); g.line(j[0], j[1], m.r, m.cap); const t = 0.4; g.line(j[0] + t * (m.r - j[0]), j[1] + t * (m.cap - j[1]), m.r, m.b); }], // K
  [0x4c, (g, m) => { g.path([[m.l, m.cap], [m.l, m.b], [m.r, m.b]]); }],                                        // L
  [0x4d, (g, m) => { g.path([[m.l, m.b], [m.l, m.cap], [m.c, m.Cy - 60], [m.r, m.cap], [m.r, m.b]]); }],          // M
  [0x4e, (g, m) => { g.path([[m.l, m.b], [m.l, m.cap], [m.r, m.b], [m.r, m.cap]]); }],                            // N
  [0x4f, (g, m) => { g.ring(m.c, m.Cy, m.rx, m.Ry + m.o); }],                                                     // O
  [0x50, (g, m) => { const py = m.b + m.H * 0.42, ry = (m.cap - py) / 2, k = m.r - ry; g.line(m.l, m.b, m.l, m.cap); g.line(m.l, m.cap, k, m.cap); g.arc(k, py + ry, ry, ry, -90, 90); g.line(k, py, m.l, py); }], // P
  [0x51, (g, m) => { g.ring(m.c, m.Cy, m.rx, m.Ry + m.o); g.line(m.c + 60, m.b + 140, m.r + 25, m.b - 70); }],    // Q
  [0x52, (g, m) => { const py = m.b + m.H * 0.42, ry = (m.cap - py) / 2, k = m.r - ry; g.line(m.l, m.b, m.l, m.cap); g.line(m.l, m.cap, k, m.cap); g.arc(k, py + ry, ry, ry, -90, 90); g.line(k, py, m.l, py); g.line(m.c - 10, py, m.r, m.b); }], // R
  [0x53, (g, m) => { const h = m.H / 4; g.arc(m.c, m.Cy + h, m.rx * 0.9, h + m.o / 2, 35, 270); g.arc(m.c, m.Cy - h, m.rx, h + m.o / 2, -145, 90); }], // S
  [0x54, (g, m) => { g.line(m.l, m.cap, m.r, m.cap); g.line(m.c, m.cap, m.c, m.b); }],                         // T
  [0x55, (g, m) => { g.line(m.l, m.cap, m.l, m.b + m.rx); g.arc(m.c, m.b + m.rx, m.rx, m.rx, 180, 360); g.line(m.r, m.b + m.rx, m.r, m.cap); }], // U
  [0x56, (g, m) => { g.path([[m.l, m.cap], [m.c, m.b], [m.r, m.cap]]); }],                                      // V
  [0x57, (g, m) => { const q = m.W * 0.22; g.path([[m.l, m.cap], [m.l + q, m.b], [m.c, m.Cy + 90], [m.r - q, m.b], [m.r, m.cap]]); }], // W
  [0x58, (g, m) => { g.line(m.l, m.b, m.r, m.cap); g.line(m.l, m.cap, m.r, m.b); }],                             // X
  [0x59, (g, m) => { g.path([[m.l, m.cap], [m.c, m.Cy - 10], [m.r, m.cap]]); g.line(m.c, m.Cy - 10, m.c, m.b); }], // Y
  [0x5a, (g, m) => { g.path([[m.l, m.cap], [m.r, m.cap], [m.l, m.b], [m.r, m.b]]); }],                            // Z

  // ---- figures (lining, cap height) ------------------------------------
  [0x30, (g, m) => { g.ring(m.c, m.Cy, m.rx, m.Ry + m.o); g.dot(m.c, m.Cy, m.rd); }],                             // 0, dotted
  [0x31, (g, m) => { g.line(m.c, m.b, m.c, m.cap); g.line(m.c, m.cap, m.c - 140, m.cap - 120); g.line(m.l + 40, m.b, m.r - 40, m.b); }], // 1
  [0x32, (g, m) => { const ra = m.H * 0.27, cy = m.cap - ra; g.arc(m.c, cy, m.rx, ra + m.o / 2, -38, 165); const [ex, ey] = at(m.c, cy, m.rx, ra + m.o / 2, -38); g.line(ex, ey, m.l, m.b); g.line(m.l, m.b, m.r, m.b); }], // 2
  [0x33, (g, m) => { const ru = m.H * 0.235, mid = m.cap - 2 * ru, rl = (mid - m.b) / 2; g.arc(m.c, m.cap - ru, m.rx * 0.9, ru, -90, 150); g.arc(m.c, m.b + rl, m.rx, rl + m.o / 2, -150, 90); }], // 3
  [0x34, (g, m) => { const s = m.r - 70, y = m.b + m.H * 0.3; g.line(s, m.b, s, m.cap); g.line(s, m.cap, m.l, y); g.line(m.l, y, m.r, y); }], // 4
  [0x35, (g, m) => { const rb = m.H * 0.33, cy = m.b + rb; const [px, py] = at(m.c, cy, m.rx, rb, 128); g.arc(m.c, cy, m.rx, rb + m.o / 2, -150, 128); g.line(px, py, px + 10, m.cap); g.line(px + 10, m.cap, m.r - 10, m.cap); }], // 5
  [0x36, (g, m) => { const rb = m.H * 0.31; g.ring(m.c, m.b + rb, m.rx, rb + m.o / 2); g.arc(m.r - 40, m.b + rb, m.r - 40 - m.l, m.cap - m.b - rb, 90, 180); }], // 6
  [0x37, (g, m) => { g.path([[m.l, m.cap], [m.r, m.cap], [m.c - 30, m.b]]); }],                                 // 7
  [0x38, (g, m) => { const ru = m.H * 0.235, rl = (m.H - 2 * ru) / 2; g.ring(m.c, m.cap - ru, m.rx * 0.84, ru); g.ring(m.c, m.b + rl, m.rx, rl + m.o / 2); }], // 8
  [0x39, (g, m) => { const rb = m.H * 0.31; g.ring(m.c, m.cap - rb, m.rx, rb + m.o / 2); g.arc(m.l + 40, m.cap - rb, m.r - m.l - 40, m.cap - rb - m.b, 270, 360); }], // 9

  // ---- punctuation and symbols ----------------------------------------
  [0x20, () => {}],                                                                                                  // space
  [0x21, (g, m) => { g.line(m.c, m.cap, m.c, m.b + 210); g.dot(m.c, m.dotY, m.rd); }],                            // !
  [0x22, (g, m) => { g.line(m.c - 75, m.cap, m.c - 75, m.cap - 190); g.line(m.c + 75, m.cap, m.c + 75, m.cap - 190); }], // "
  [0x23, (g, m) => { g.line(m.c - 95, m.b + 20, m.c - 55, m.cap - 20); g.line(m.c + 55, m.b + 20, m.c + 95, m.cap - 20); g.line(m.l, m.Cy + 100, m.r, m.Cy + 100); g.line(m.l, m.Cy - 110, m.r, m.Cy - 110); }], // #
  [0x24, (g, m) => { const h = m.H / 4 - 10; g.arc(m.c, m.Cy + h, m.rx * 0.9, h, 35, 270); g.arc(m.c, m.Cy - h, m.rx, h, -145, 90); g.line(m.c, m.cap + 70, m.c, m.b - 70); }], // $
  [0x25, (g, m) => { g.ring(m.l + 55, m.cap - 115, 55, 105); g.ring(m.r - 55, m.b + 105, 55, 105); g.line(m.r, m.cap, m.l, m.b); }], // %
  [0x26, (g, m) => { const t = [m.c - 40, m.cap - 120]; g.ring(t[0], t[1], 95, 120); const s = at(t[0], t[1], 95, 120, 235); g.line(s[0], s[1], m.r, m.b);
    const e = at(t[0], t[1], 95, 120, -55); const bs = at(m.c - 40, m.b + 150, 150, 150, 135); g.line(e[0], e[1], bs[0], bs[1]); g.arc(m.c - 40, m.b + 150, 150, 150, 135, 370); }], // &
  [0x27, (g, m) => { g.line(m.c, m.cap, m.c, m.cap - 190); }],                                                    // '
  [0x28, (g, m) => { g.arc(m.c + 190, m.Cy, 230, m.Ry + 90, 118, 242); }],                                        // (
  [0x29, (g, m) => { g.arc(m.c - 190, m.Cy, 230, m.Ry + 90, -62, 62); }],                                         // )
  [0x2a, (g, m) => { const y = m.cap - 170; for (const a of [90, 30, 150]) { const [x1, y1] = at(m.c, y, 150, 150, a), [x2, y2] = at(m.c, y, 150, 150, a + 180); g.line(x1, y1, x2, y2); } }], // *
  [0x2b, (g, m) => { g.line(m.c, m.ax - 170, m.c, m.ax + 170); g.line(m.c - 170, m.ax, m.c + 170, m.ax); }],      // +
  [0x2c, (g, m) => { g.line(m.c + 25, m.b + 70, m.c - 45, m.b - 150); }],                                         // ,
  [0x2d, (g, m) => { g.line(m.c - 150, m.ax, m.c + 150, m.ax); }],                                                // -
  [0x2e, (g, m) => { g.dot(m.c, m.dotY, m.rd); }],                                                                // .
  [0x2f, (g, m) => { g.line(m.l + 30, m.b - 70, m.r - 30, m.cap + 70); }],                                        // /
  [0x3a, (g, m) => { g.dot(m.c, m.x - m.rd + m.w, m.rd); g.dot(m.c, m.dotY, m.rd); }],                            // :
  [0x3b, (g, m) => { g.dot(m.c, m.x - m.rd + m.w, m.rd); g.line(m.c + 25, m.b + 70, m.c - 45, m.b - 150); }],     // ;
  [0x3c, (g, m) => { g.path([[m.r - 30, m.ax + 190], [m.l + 30, m.ax], [m.r - 30, m.ax - 190]]); }],              // <
  [0x3d, (g, m) => { g.line(m.l + 30, m.ax + 90, m.r - 30, m.ax + 90); g.line(m.l + 30, m.ax - 90, m.r - 30, m.ax - 90); }], // =
  [0x3e, (g, m) => { g.path([[m.l + 30, m.ax + 190], [m.r - 30, m.ax], [m.l + 30, m.ax - 190]]); }],              // >
  [0x3f, (g, m) => { const r = 135, cy = m.cap - r; g.arc(m.c, cy, m.rx * 0.9, r, -90, 160); g.line(m.c, cy - r, m.c, m.b + 220); g.dot(m.c, m.dotY, m.rd); }], // ?
  [0x40, (g, m) => { const cy = m.ax + 40; g.ring(m.c - 15, cy, 95, 125); g.line(m.c + 80, cy + 150, m.c + 80, cy - 70); g.arc(m.c, cy, m.rx + 15, 330, -12, 300); }], // @
  [0x5b, (g, m) => { g.path([[m.c + 90, m.cap + 70], [m.c - 60, m.cap + 70], [m.c - 60, m.b - 110], [m.c + 90, m.b - 110]]); }], // [
  [0x5c, (g, m) => { g.line(m.l + 30, m.cap + 70, m.r - 30, m.b - 70); }],                                        // backslash
  [0x5d, (g, m) => { g.path([[m.c - 90, m.cap + 70], [m.c + 60, m.cap + 70], [m.c + 60, m.b - 110], [m.c - 90, m.b - 110]]); }], // ]
  [0x5e, (g, m) => { g.path([[m.l + 40, m.cap - 250], [m.c, m.cap], [m.r - 40, m.cap - 250]]); }],                // ^
  [0x5f, (g, m) => { g.line(m.l - 30, m.dsc + 30, m.r + 30, m.dsc + 30); }],                                       // _
  [0x60, (g, m) => { g.line(m.c - 60, m.cap + 40, m.c + 40, m.cap - 110); }],                                     // `
  [0x7b, (g, m) => { const k = 80; g.arc(m.c + k, m.cap - 20, k, k, 90, 180); g.line(m.c, m.cap - 20, m.c, m.Cy + k); g.arc(m.c - k, m.Cy + k, k, k, 270, 360);
    g.arc(m.c - k, m.Cy - k, k, k, 0, 90); g.line(m.c, m.Cy - k, m.c, m.b - 20); g.arc(m.c + k, m.b - 20, k, k, 180, 270); }], // {
  [0x7c, (g, m) => { g.line(m.c, m.cap + 80, m.c, m.dsc + 40); }],                                                // |
  [0x7d, (g, m) => { const k = 80; g.arc(m.c - k, m.cap - 20, k, k, 0, 90); g.line(m.c, m.cap - 20, m.c, m.Cy + k); g.arc(m.c + k, m.Cy + k, k, k, 180, 270);
    g.arc(m.c + k, m.Cy - k, k, k, 90, 180); g.line(m.c, m.Cy - k, m.c, m.b - 20); g.arc(m.c - k, m.b - 20, k, k, 270, 360); }], // }
  [0x7e, (g, m) => { g.arc(m.c - 90, m.ax - 25, 90, 70, 0, 160); g.arc(m.c + 90, m.ax - 25, 90, 70, 180, 340); }],  // ~

  // ---- typographic extras used in the sierx interface --------------------
  [0x00b7, (g, m) => { g.dot(m.c, m.ax, m.rd); }],                                                                // ·
  [0x00d7, (g, m) => { g.line(m.c - 130, m.ax - 130, m.c + 130, m.ax + 130); g.line(m.c - 130, m.ax + 130, m.c + 130, m.ax - 130); }], // ×
  [0x2013, (g, m) => { g.line(m.l - 10, m.ax, m.r + 10, m.ax); }],                                                // –
  [0x2014, (g, m) => { g.line(20 + m.w, m.ax, 580 - m.w, m.ax); }],                                               // —
  [0x2018, (g, m) => { g.line(m.c + 30, m.cap - 10, m.c - 30, m.cap - 190); }],                                   // ‘
  [0x2019, (g, m) => { g.line(m.c + 30, m.cap, m.c - 30, m.cap - 180); }],                                        // ’
  [0x201c, (g, m) => { g.line(m.c - 50, m.cap - 10, m.c - 110, m.cap - 190); g.line(m.c + 110, m.cap - 10, m.c + 50, m.cap - 190); }], // “
  [0x201d, (g, m) => { g.line(m.c - 50, m.cap, m.c - 110, m.cap - 180); g.line(m.c + 110, m.cap, m.c + 50, m.cap - 180); }], // ”
  [0x2026, (g, m) => { for (const x of [m.c - 180, m.c, m.c + 180]) g.dot(x, m.dotY, m.rd * 0.9); }],             // …
  [0x203a, (g, m) => { g.path([[m.c - 90, m.ax + 140], [m.c + 90, m.ax], [m.c - 90, m.ax - 140]]); }],            // ›
  [0x2192, (g, m) => { g.line(m.l - 20, m.ax, m.r + 20, m.ax); g.path([[m.r - 140, m.ax + 140], [m.r + 20, m.ax], [m.r - 140, m.ax - 140]]); }], // →
  [0x22ef, (g, m) => { for (const x of [m.c - 180, m.c, m.c + 180]) g.dot(x, m.ax, m.rd * 0.9); }],               // ⋯

  // ---- sierx status and type glyphs: same grid, same stroke ---------------
  [0x25cb, (g, m) => { g.ring(m.c, m.cy + 20, 220, 220); }],                                                      // ○ open
  [0x25d0, (g, m) => { g.ring(m.c, m.cy + 20, 220, 220); g.pie(m.c, m.cy + 20, 220, 90, 270); }],               // ◐ active
  [0x25d1, (g, m) => { g.ring(m.c, m.cy + 20, 220, 220); g.pie(m.c, m.cy + 20, 220, -90, 90); }],               // ◑ review
  [0x25cf, (g, m) => { g.dot(m.c, m.cy + 20, 220 + m.w); }],                                                     // ● done
  [0x2298, (g, m) => { const cy = m.cy + 20, [x1, y1] = at(m.c, cy, 220, 220, 225), [x2, y2] = at(m.c, cy, 220, 220, 45); g.ring(m.c, cy, 220, 220); g.line(x1, y1, x2, y2); }], // ⊘ cancelled, blocked
  [0x25ad, (g, m) => { const cy = m.cy + 20; g.path([[m.l - 20, cy - 150], [m.r + 20, cy - 150], [m.r + 20, cy + 150], [m.l - 20, cy + 150], [m.l - 20, cy - 150]]); }], // ▭ story
  [0x2715, (g, m) => { const cy = m.cy + 20; g.line(m.c - 185, cy - 185, m.c + 185, cy + 185); g.line(m.c - 185, cy + 185, m.c + 185, cy - 185); }], // ✕ bug
  [0x25c6, (g, m) => { const cy = m.cy + 20, r = 255; g.poly([[m.c, cy + r], [m.c + r, cy], [m.c, cy - r], [m.c - r, cy]]); }], // ◆ epic
  [0x25c7, (g, m) => { const cy = m.cy + 20, r = 235; g.path([[m.c, cy + r], [m.c + r, cy], [m.c, cy - r], [m.c - r, cy], [m.c, cy + r]]); }], // ◇ idea
  [0x25b2, (g, m) => { const cy = m.cy + 20; g.poly([[m.c, cy + 245], [m.c + 255, cy - 200], [m.c - 255, cy - 200]]); }], // ▲ initiative, caution
  [0x25a0, (g, m) => { const cy = m.cy + 20, r = 205; g.poly([[m.c - r, cy - r], [m.c + r, cy - r], [m.c + r, cy + r], [m.c - r, cy + r]]); }], // ■
  [0x25be, (g, m) => { const cy = m.cy + 10; g.poly([[m.c - 150, cy + 80], [m.c + 150, cy + 80], [m.c, cy - 120]]); }], // ▾
  [0x25b8, (g, m) => { const cy = m.cy + 20; g.poly([[m.c - 80, cy + 150], [m.c + 120, cy], [m.c - 80, cy - 150]]); }], // ▸
  [0x2610, (g, m) => { const cy = m.cy + 20, r = 215; g.path([[m.c - r, cy - r], [m.c + r, cy - r], [m.c + r, cy + r], [m.c - r, cy + r], [m.c - r, cy - r]]); }], // ☐
  [0x2611, (g, m) => { const cy = m.cy + 20, r = 215; g.path([[m.c - r, cy - r], [m.c + r, cy - r], [m.c + r, cy + r], [m.c - r, cy + r], [m.c - r, cy - r]]); g.path([[m.c - 100, cy + 10], [m.c - 25, cy - 75], [m.c + 110, cy + 95]]); }], // ☑
];

/** Codepoints that also go into the small "Sierx Symbols" face, which every theme can
    put first in its stack so status glyphs look the same everywhere. */
export const symbols = [0x25cb, 0x25d0, 0x25d1, 0x25cf, 0x2298, 0x25ad, 0x2715, 0x25c6, 0x25c7, 0x25b2, 0x25a0, 0x25be, 0x25b8, 0x2610, 0x2611, 0x2192, 0x203a, 0x22ef];
