import { it, expect } from 'vitest';
import { customValues } from './Fields';
const fields = [
  {
    key: 'tags',
    name: 'Tags',
    data_type: 'multiselect',
    options: ['one', 'two'],
  },
  { key: 'effort', name: 'Effort', data_type: 'number', options: [] },
  { key: 'ready', name: 'Ready', data_type: 'bool', options: [] },
];
it('clears deselected multiselects while preserving fields omitted by a transition form', () => {
  const data = new FormData();
  data.set('present:tags', '1');
  data.set('field:effort', '0');
  data.set('field:ready', 'false');
  expect(
    customValues(data, fields, { tags: ['one'], other: 'preserved' }),
  ).toEqual({ tags: [], effort: 0, ready: false, other: 'preserved' });
  expect(customValues(new FormData(), fields, { tags: ['two'] })).toEqual({
    tags: ['two'],
  });
});
