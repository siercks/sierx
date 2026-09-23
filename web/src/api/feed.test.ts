import { afterEach, it, expect, vi } from 'vitest';
import { startFeed } from './feed';
afterEach(() => vi.useRealTimers());
it('pauses when hidden, preserves int64 positions and resumes at focus', async () => {
  vi.useFakeTimers();
  let active = false;
  const fetchPage = vi
    .fn()
    .mockResolvedValue({ data: [{}], next_seq: 9007199254740999n });
  const invalidate = vi.fn().mockResolvedValue(undefined);
  const stop = startFeed({
    sequence: '9007199254740998',
    active: () => active,
    fetchPage,
    invalidate,
  });
  await vi.advanceTimersByTimeAsync(20000);
  expect(fetchPage).not.toHaveBeenCalled();
  active = true;
  await vi.advanceTimersByTimeAsync(10000);
  expect(fetchPage).toHaveBeenLastCalledWith('9007199254740998');
  expect(invalidate).toHaveBeenCalledOnce();
  await vi.advanceTimersByTimeAsync(10000);
  expect(fetchPage).toHaveBeenLastCalledWith('9007199254740999');
  stop();
  await vi.advanceTimersByTimeAsync(120000);
  expect(fetchPage).toHaveBeenCalledTimes(2);
});
it('backs off failures without advancing the sequence and drains full pages', async () => {
  vi.useFakeTimers();
  const fetchPage = vi
    .fn()
    .mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValueOnce({ data: Array(200).fill({}), next_seq: 200 })
    .mockResolvedValue({ data: [], next_seq: 200 });
  const invalidate = vi.fn().mockResolvedValue(undefined);
  const stop = startFeed({
    sequence: '0',
    active: () => true,
    fetchPage,
    invalidate,
  });
  await vi.advanceTimersByTimeAsync(10000);
  expect(fetchPage).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(19999);
  expect(fetchPage).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(1);
  expect(fetchPage).toHaveBeenLastCalledWith('0');
  await vi.advanceTimersByTimeAsync(1000);
  expect(fetchPage).toHaveBeenLastCalledWith('200');
  stop();
});
