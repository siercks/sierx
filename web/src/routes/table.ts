// Canonical route source. The generator reads this literal, not arbitrary TS.
// prettier-ignore
export const routes = [
  { id: 'list', path: '/', eager: true, handler: 'bootstrapList' },
  { id: 'login', path: '/login', eager: false, handler: 'bootstrapLogin' },
  { id: 'privacy', path: '/privacy', eager: false, handler: 'bootstrapPrivacy' },
  { id: 'copyright', path: '/copyright', eager: false, handler: 'bootstrapCopyright' },
  { id: 'third-party', path: '/third-party', eager: false, handler: 'bootstrapThirdParty' },
  { id: 'item', path: '/:key', eager: false, handler: 'bootstrapItem' },
] as const;
