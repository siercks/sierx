import { beforeEach, expect, it, vi } from 'vitest';
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
