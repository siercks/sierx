import { describe, expect, it } from 'vitest';
import { historyAction, historyValue } from './history';

const statuses = [
  { key: 'todo', name: 'Todo', category: 'backlog' },
  { key: 'doing', name: 'In Progress', category: 'active' },
];

describe('history presentation', () => {
  it('uses configured status names without repeating the field', () => {
    const event = { kind: 'status_changed', field: 'status' };
    expect(historyAction(event)).toBe('changed status');
    expect(historyValue(event, 'todo', statuses)).toBe('Todo');
    expect(historyValue(event, 'doing', statuses)).toBe('In Progress');
  });

  it('turns field keys into readable change descriptions', () => {
    expect(
      historyAction({ kind: 'field_changed', field: 'fields.customer_impact' }),
    ).toBe('changed customer impact');
  });
});
