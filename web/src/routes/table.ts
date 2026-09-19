// Canonical route source. The generator reads this literal, not arbitrary TS.
// prettier-ignore
export const routes = [
  { id: 'list', path: '/', eager: true, handler: 'bootstrapList' },
  { id: 'login', path: '/login', eager: false, handler: 'bootstrapLogin' },
  { id: 'item', path: '/:key', eager: false, handler: 'bootstrapItem' },
] as const;
