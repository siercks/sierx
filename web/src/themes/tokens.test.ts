import { describe, it, expect } from 'vitest';
import { wcagContrast } from 'culori';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import postcss from 'postcss';
const root = join('design', 'tokens');
const files = readdirSync(root).filter((file) => /^\d.*\.json$/.test(file)).sort();
const themes = files.map((file) => JSON.parse(readFileSync(join(root, file), 'utf8')));
const pairs: [string, string, 'text' | 'ui'][] = [
  ['foreground', 'background', 'text'], ['muted-foreground', 'background', 'text'],
  ['card-foreground', 'card', 'text'], ['muted-foreground', 'card', 'text'],
  ['foreground', 'muted', 'text'], ['foreground', 'sx-panel', 'text'],
  ['muted-foreground', 'sx-panel', 'text'], ['primary-foreground', 'primary', 'text'],
  ['accent-foreground', 'accent', 'text'], ['destructive', 'background', 'text'],
  ['destructive', 'card', 'text'], ['destructive-foreground', 'destructive', 'text'],
  ['sx-chrome-foreground', 'sx-chrome', 'text'], ['sx-chrome-muted', 'sx-chrome', 'text'],
  ['sx-selected-foreground', 'sx-selected', 'text'], ['sx-selected-muted', 'sx-selected', 'text'],
  ['border', 'background', 'ui'], ['input', 'background', 'ui'], ['ring', 'background', 'ui'],
  ['ring', 'card', 'ui'], ['status-open', 'card', 'ui'], ['status-active', 'card', 'ui'],
  ['status-done', 'card', 'ui'], ['status-cancelled', 'card', 'ui'],
];
function assertThemeContrast(theme: typeof themes[number]) {
  const minText = theme.contrast === 'high' ? 7 : 4.5;
  const values = { ...theme.tokens, ...(theme.private ?? {}) };
  for (const [fg, bg, kind] of [...pairs, ...(theme.pairs ?? [])])
    expect(wcagContrast(values[fg], values[bg]), `${theme.id}: ${fg}/${bg}`)
      .toBeGreaterThanOrEqual(kind === 'text' ? minText : 3);
}
describe('declared theme pairs', () => {
  for (const theme of themes) {
    it(theme.id, () => {
      assertThemeContrast(theme);
    });
  }
  it('rejects unreadable declared theme pairs', () => {
    const theme = themes[0];
    expect(() => assertThemeContrast({
      ...theme,
      tokens: { ...theme.tokens, foreground: theme.tokens.background },
    })).toThrow();
  });
  it('delivered CSS contains every named theme and its declared colors', () => {
    const css = postcss.parse(readFileSync('design/css/tokens.css', 'utf8'));
    for (const theme of themes) {
      let found = false;
      css.walkRules((rule) => {
        if (
          rule.selector.replaceAll("'", '"') !== `[data-theme="${theme.id}"]`
        )
          return;
        found = true;
        const declarations = new Map<string, string>();
        rule.walkDecls((d) => {
          declarations.set(d.prop, d.value);
        });
        for (const [key, value] of Object.entries(theme.tokens))
          expect(declarations.get('--' + key)).toBe(value);
      });
      expect(found, theme.id).toBe(true);
    }
  });
});
