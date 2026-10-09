import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { appearanceThemes, normalizeTheme } from './catalog';

const tokenIDs = readdirSync('design/tokens')
  .filter((file) => /^\d.*\.json$/.test(file))
  .map((file) => JSON.parse(readFileSync(join('design/tokens', file), 'utf8')).id)
  .sort();

describe('appearance catalog', () => {
  it('offers every token theme exactly once', () => {
    const catalogIDs = appearanceThemes.map(({ id }) => id).sort();
    expect(catalogIDs).toEqual(tokenIDs);
  });

  it('maps the old preference values to their closest named appearances', () => {
    expect(normalizeTheme('system')).toBe('system');
    expect(normalizeTheme('light')).toBe('quiet');
    expect(normalizeTheme('dark')).toBe('dusk');
    expect(normalizeTheme('light-hc')).toBe('eink');
    expect(normalizeTheme('dark-hc')).toBe('eink-dark');
    expect(normalizeTheme('unknown')).toBe('system');
  });
});
