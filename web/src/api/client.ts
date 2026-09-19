import { parse, stringify } from 'lossless-json';
import { QueryClient, useMutation } from '@tanstack/react-query';
import type { ItemFields } from './fields';

// Wire numbers stay JSON numbers. Integral tokens are decoded exactly before
// IEEE-754 conversion. Unsafe integers use bigint; sequences are normalized to
// decimal strings at the boundary. No API or generated-type changes are needed.
export function decode<T>(text: string): T {
  return parse(text, undefined, (token) => {
    if (/^-?\d+$/.test(token)) {
      const exact = BigInt(token);
      return exact > BigInt(Number.MAX_SAFE_INTEGER) ||
        exact < BigInt(Number.MIN_SAFE_INTEGER)
        ? exact
        : Number(token);
    }
    return Number(token);
  }) as T;
}
export const encode = (value: unknown) => stringify(value)!;
export type Item = Omit<ItemFields, 'change_seq'> & {
  change_seq: number | bigint;
};
export type Page<T> = { data: T[]; next_cursor: string | null };
export type Me = {
  id: string;
  workspace_id: string;
  display_name: string;
  role: string;
  theme: string;
  reduced_motion: boolean | null;
};
export type Project = {
  key_prefix: string;
  name: string;
  archived_at: string | null;
};
export type Config = {
  types: { key: string; name: string; initial_status: string }[];
  statuses: { key: string; name: string; category: string }[];
  transitions: Record<string, { to_key: string; requires: string[] }[]>;
  fields: { key: string; name: string; data_type: string; options: unknown }[];
};
export type Problem = {
  status: number;
  title: string;
  detail?: string;
  current?: Item;
  submitted?: unknown;
};
export class APIError extends Error {
  constructor(public problem: Problem) {
    super(problem.detail || problem.title || 'Request failed. Try again.');
  }
}
export const LIST_FIELDS =
  'id,key,title,version,change_seq,status,type,parent,project,assignee,rank,points,updated_at';
export const DETAIL_FIELDS =
  'id,key,title,body,version,change_seq,config_version,rank,points,start_date,due_date,created_at,updated_at,deleted_at,status,assignee,type,parent,project,fields,rollup';
export async function request<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    version?: number;
    signal?: AbortSignal;
  } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (options.version !== undefined) {
    if (!Number.isSafeInteger(options.version) || options.version < 1)
      throw new Error('Invalid item version. Reload the item.');
    headers['If-Match'] = `"${options.version}"`;
  }
  const response = await fetch('/api/v1' + path, {
    method: options.method ?? 'GET',
    headers,
    credentials: 'same-origin',
    body: options.body === undefined ? undefined : encode(options.body),
    signal: options.signal,
  });
  const text = await response.text();
  const data = text ? decode<T & Problem>(text) : undefined;
  if (!response.ok) {
    if (response.status === 401 && path !== '/auth/login')
      window.dispatchEvent(new Event('sierx:expired'));
    throw new APIError(
      data && typeof data === 'object'
        ? { ...data, status: response.status }
        : { status: response.status, title: 'Request failed. Try again.' },
    );
  }
  return data as T;
}
export const cache = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30000, retry: false, refetchOnWindowFocus: false },
    mutations: { retry: false },
  },
});
export const itemKey = (workspace: string, key: string) =>
  [workspace, 'item', key, DETAIL_FIELDS] as const;
export const listKey = (workspace: string, query: string) =>
  [workspace, 'list', query, LIST_FIELDS] as const;
export type Write = {
  path: string;
  method: string;
  body?: unknown;
  version: number;
  optimistic?: Partial<Item>;
};
export async function mutateItem(workspace: string, key: string, write: Write) {
  await cache.cancelQueries({ queryKey: [workspace] });
  const previous = cache.getQueriesData({ queryKey: [workspace] });
  if (write.optimistic) {
    cache.setQueryData<Item>(itemKey(workspace, key), (old) =>
      old ? { ...old, ...write.optimistic } : old,
    );
    cache.setQueriesData<{ pages: Page<Item>[] }>(
      { queryKey: [workspace, 'list'] },
      (old) =>
        old
          ? {
              ...old,
              pages: old.pages.map((p) => ({
                ...p,
                data: p.data.map((i) =>
                  i.key === key ? { ...i, ...write.optimistic } : i,
                ),
              })),
            }
          : old,
    );
  }
  try {
    await request(write.path, write);
  } catch (error) {
    for (const [queryKey, data] of previous) cache.setQueryData(queryKey, data);
    if (error instanceof APIError && error.problem.current)
      cache.setQueryData(itemKey(workspace, key), error.problem.current);
    throw error;
  } finally {
    // Moves can alter query membership, ancestors and entire descendant paths;
    // compact events never replace full items. Invalidate the workspace scope.
    await cache.invalidateQueries({ queryKey: [workspace] });
  }
}
export function useItemWrite(workspace: string, key: string) {
  return useMutation({
    mutationFn: (write: Write) => mutateItem(workspace, key, write),
  });
}
export function bootstrap<T>(): T {
  const node = document.getElementById('sierx-state');
  if (!node?.textContent)
    throw new Error(
      'Initial page data is missing. Open Sierx through its application server.',
    );
  return decode<T>(node.textContent);
}
export function isProblem(value: unknown): value is Problem {
  return (
    !!value &&
    typeof value === 'object' &&
    'status' in value &&
    typeof value.status === 'number'
  );
}
