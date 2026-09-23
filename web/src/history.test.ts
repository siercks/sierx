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

  it('summarizes comment events without exposing storage JSON', () => {
    const added = {
      kind: 'field_changed',
      field: 'comment',
      old_value: null,
      new_value: { id: 'comment-1', body: '**Hello**', deleted: false },
    };
    expect(historyAction(added)).toBe('added a comment');
    expect(historyValue(added, added.new_value, statuses)).toBe('**Hello**');

    const removed = {
      ...added,
      old_value: added.new_value,
      new_value: { id: 'comment-1', body: null, deleted: true },
    };
    expect(historyAction(removed)).toBe('deleted a comment');
    expect(historyValue(removed, removed.new_value, statuses)).toBe('Deleted');
  });
});
