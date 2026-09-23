import { describe, it, expect } from 'vitest';
import { wcagContrast, converter } from 'culori';
import palettes from './palettes.json';
import { readFileSync } from 'node:fs';
import postcss from 'postcss';
const chroma = converter('oklch');
function check(name: string, p: Record<string, string>) {
  const text = name.endsWith('hc') ? 7 : 4.5;
  for (const bg of ['background', 'card', 'muted', 'input']) {
    for (const fg of [
      'foreground',
      'muted-foreground',
      'primary',
      'destructive',
    ])
      expect(
        wcagContrast(p[bg], p[fg]),
        `${name} ${fg}/${bg}`,
      ).toBeGreaterThanOrEqual(text);
    for (const fg of ['border', 'ring'])
      expect(
        wcagContrast(p[bg], p[fg]),
        `${name} ${fg}/${bg}`,
      ).toBeGreaterThanOrEqual(3);
  }
  expect(
    wcagContrast(p.primary, p['primary-foreground']),
  ).toBeGreaterThanOrEqual(text);
  for (const status of ['open', 'active', 'done', 'cancelled'])
    expect(wcagContrast(p.card, p[`status-${status}`])).toBeGreaterThanOrEqual(
      3,
    );
  for (const bg of ['background', 'card', 'muted'])
    expect(chroma(p[bg])!.c).toBeLessThanOrEqual(0.02);
}
describe('declared theme pairs', () => {
  for (const [name, p] of Object.entries(palettes))
    it(name, () => check(name, p));
  it('rejects weak text and chromatic surfaces', () => {
    expect(() =>
      check('light', { ...palettes.light, foreground: '#eeeeee' }),
    ).toThrow();
    expect(() =>
      check('light', { ...palettes.light, background: '#ff0000' }),
    ).toThrow();
  });
  it('delivered CSS contains the checked tokens', () => {
    const root = postcss.parse(readFileSync('src/themes/tokens.css', 'utf8'));
    for (const [name, p] of Object.entries(palettes)) {
      let found = false;
      root.walkRules((rule) => {
        if (
          rule.selector.replaceAll("'", '"') !== `:root[data-theme="${name}"]`
        )
          return;
        found = true;
        const declarations = new Map<string, string>();
        rule.walkDecls((d) => {
          declarations.set(d.prop, d.value);
        });
        for (const [key, value] of Object.entries(p))
          expect(declarations.get('--' + key)).toBe(value);
      });
      expect(found).toBe(true);
    }
  });
});
