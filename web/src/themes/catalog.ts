export const appearanceThemes = [
  { id: 'swiss', name: 'Swiss grid' },
  { id: 'quiet', name: 'Quiet utility' },
  { id: 'ledger', name: 'Ledger' },
  { id: 'commander', name: 'Commander' },
  { id: 'platinum', name: 'Platinum desktop' },
  { id: 'blueprint', name: 'Blueprint' },
  { id: 'eink', name: 'E-ink' },
  { id: 'eink-dark', name: 'E-ink dark' },
  { id: 'ticker', name: 'Ticker' },
  { id: 'plain', name: 'Plain text' },
  { id: 'brutal', name: 'Neo-brutalist' },
  { id: 'civic', name: 'Civic' },
  { id: 'dusk', name: 'Low-glare dark' },
  { id: 'cockpit', name: 'Cockpit' },
  { id: 'chart', name: 'Chart' },
  { id: 'appliance', name: 'Appliance' },
  { id: 'redlight', name: 'Red light' },
  { id: 'celadon', name: 'Celadon' },
  { id: 'riso', name: 'Riso' },
  { id: 'vellum', name: 'Vellum' },
  { id: 'kraft', name: 'Kraft' },
  { id: 'indigo', name: 'Indigo' },
  { id: 'indexcard', name: 'Index card' },
] as const;

const themeIDs = new Set<string>(appearanceThemes.map(({ id }) => id));
const legacyThemeAliases: Record<string, string> = {
  light: 'quiet',
  dark: 'dusk',
  'light-hc': 'eink',
  'dark-hc': 'eink-dark',
};

export function normalizeTheme(theme: string): string {
  if (theme === 'system') return theme;
  if (themeIDs.has(theme)) return theme;
  return legacyThemeAliases[theme] ?? 'system';
}
