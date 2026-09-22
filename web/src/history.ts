import type { Config } from './api/client';

type HistoryEvent = { kind: string; field: string | null };

export function historyAction(event: HistoryEvent): string {
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
  if (value === null || value === undefined) return 'Not set';
  if (typeof value === 'object')
    return JSON.stringify(value, (_, nested) =>
      typeof nested === 'bigint' ? String(nested) : nested,
    );
  return String(value);
}
