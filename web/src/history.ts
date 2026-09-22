import type { Config } from './api/client';

type HistoryEvent = {
  kind: string;
  field: string | null;
  old_value?: unknown;
  new_value?: unknown;
};

function record(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === 'object'
    ? (value as Record<string, unknown>)
    : undefined;
}

export function historyAction(event: HistoryEvent): string {
  if (event.field === 'comment') {
    if (record(event.new_value)?.deleted === true) return 'deleted a comment';
    if (event.old_value === null || event.old_value === undefined)
      return 'added a comment';
    return 'edited a comment';
  }
  if (event.kind === 'status_changed') return 'changed status';
  if (event.kind === 'field_changed' && event.field)
    return `changed ${event.field.replace(/^fields\./, '').replaceAll('_', ' ')}`;
  return event.kind.replaceAll('_', ' ');
}

export function historyValue(
  event: HistoryEvent,
  value: unknown,
  statuses: Config['statuses'],
): string {
  if (event.kind === 'status_changed' && typeof value === 'string')
    return statuses.find((status) => status.key === value)?.name ?? value;
  if (event.field === 'comment') {
    const comment = record(value);
    if (comment?.deleted === true) return 'Deleted';
    if (typeof comment?.body === 'string') return comment.body;
  }
  if (value === null || value === undefined) return 'Not set';
  if (typeof value === 'object')
    return JSON.stringify(value, (_, nested) =>
      typeof nested === 'bigint' ? String(nested) : nested,
    );
  return String(value);
}
