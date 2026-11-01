import { beforeEach, expect, it, vi } from 'vitest';
import { QueryObserver } from '@tanstack/react-query';
import {
  decode,
  encode,
  cache,
  itemKey,
  mutateItem,
  type Item,
} from './client';
beforeEach(() => {
  cache.clear();
  vi.restoreAllMocks();
});
it('retains committed item responses when refreshes fail and sends the next write once at the new version', async () => {
  const original = { key: 'SRX-1', title: 'Original', version: 1 } as Item;
  cache.setQueryData(itemKey('workspace', 'SRX-1'), original);
  const mock = vi.fn(async (_url: string, options?: RequestInit) => {
    if (!options?.method || options.method === 'GET') return new Response('Unavailable', { status: 503 });
    const version = options.method === 'PATCH' ? 2 : 3;
    return new Response(encode({ ...original, title: 'Canonical saved title', version }), { status: 200 });
  });
  vi.stubGlobal('fetch', mock);
  const observer = new QueryObserver(cache, {
    queryKey: itemKey('workspace', 'SRX-1'),
    queryFn: async () => { const response = await fetch('/api/v1/items/SRX-1'); if (!response.ok) throw new Error('Refresh failed'); return response.json(); },
  });
  const unsubscribe = observer.subscribe(() => {});
  try {
    await mutateItem('workspace', 'SRX-1', { path: '/items/SRX-1', method: 'PATCH', body: { title: 'Draft' }, optimistic: { title: 'Draft' }, version: 1 });
    expect(observer.getCurrentResult().isError).toBe(true);
    expect(cache.getQueryData<Item>(itemKey('workspace', 'SRX-1'))).toMatchObject({ title: 'Canonical saved title', version: 2 });
    await mutateItem('workspace', 'SRX-1', { path: '/items/SRX-1/transition', method: 'POST', body: { to_status: 'doing' }, version: 2 });
    expect(cache.getQueryData<Item>(itemKey('workspace', 'SRX-1'))?.version).toBe(3);
    const writes = mock.mock.calls.filter(([, options]) => options?.method && options.method !== 'GET');
    expect(writes.map(([, options]) => options?.headers)).toEqual([
      expect.objectContaining({ 'If-Match': '"1"' }), expect.objectContaining({ 'If-Match': '"2"' }),
    ]);
    expect(mock).toHaveBeenCalledTimes(4);
  } finally { unsubscribe(); }
});

it('does not replace a newer item with a delayed write response or a relationship envelope', async () => {
  const newer = { key: 'SRX-1', title: 'Newer concurrent read', version: 4 } as Item;
  vi.stubGlobal('fetch', vi.fn(async () => {
    cache.setQueryData(itemKey('workspace', 'SRX-1'), newer);
    return new Response(encode({ ...newer, title: 'Older write', version: 2 }), { status: 200 });
  }));
  await mutateItem('workspace', 'SRX-1', { path: '/items/SRX-1', method: 'PATCH', version: 1 });
  expect(cache.getQueryData(itemKey('workspace', 'SRX-1'))).toEqual(newer);
  vi.stubGlobal('fetch', vi.fn(async () => new Response(encode({ id: 'comment', body: 'Saved comment' }), { status: 201 })));
  await mutateItem('workspace', 'SRX-1', { path: '/comments', method: 'POST', version: 4 });
  expect(cache.getQueryData(itemKey('workspace', 'SRX-1'))).toEqual(newer);
});
it('preserves integral tokens above 2^53 including int64 max and keeps ordinary decimals', () => {
  const text =
    '{"next_seq":9223372036854775807,"change_seq":9007199254740993,"version":2147483647,"points":1.5}';
  const parsed = decode<{
    next_seq: bigint;
    change_seq: bigint;
    version: number;
    points: number;
  }>(text);
  expect(String(parsed.next_seq)).toBe('9223372036854775807');
  expect(String(parsed.change_seq)).toBe('9007199254740993');
  expect(parsed.version).toBe(2147483647);
  expect(parsed.points).toBe(1.5);
  expect(encode(parsed)).toBe(text);
});
it.each([409, 422, 503])(
  'rolls back failed optimistic writes (%s) without automatic replay',
  async (status) => {
    const original = { key: 'SRX-1', title: 'Original', version: 1 } as Item;
    cache.setQueryData(itemKey('workspace', 'SRX-1'), original);
    let resolve!: (r: Response) => void;
    const mock = vi.fn(
      () =>
        new Promise<Response>((r) => {
          resolve = r;
        }),
    );
    vi.stubGlobal('fetch', mock);
    const pending = mutateItem('workspace', 'SRX-1', {
      path: '/items/SRX-1',
      method: 'PATCH',
      body: { title: 'Draft' },
      optimistic: { title: 'Draft' },
      version: 1,
    });
    await vi.waitFor(() => expect(mock).toHaveBeenCalledOnce());
    expect(cache.getQueryData<Item>(itemKey('workspace', 'SRX-1'))?.title).toBe(
      'Draft',
    );
    resolve(
      new Response(
        JSON.stringify({
          status,
          title: 'Write failed',
          ...(status === 409
            ? { current: { ...original, title: 'Server', version: 2 } }
            : {}),
        }),
        { status },
      ),
    );
    await expect(pending).rejects.toThrow();
    expect(cache.getQueryData<Item>(itemKey('workspace', 'SRX-1'))?.title).toBe(
      status === 409 ? 'Server' : 'Original',
    );
    expect(mock).toHaveBeenCalledOnce();
    expect(
      (mock.mock.calls[0] as unknown as [string, RequestInit])[1].headers,
    ).toMatchObject({ 'If-Match': '"1"' });
  },
);
