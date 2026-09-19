// Compact events invalidate projections; they never replace full items.
export function startFeed({
  sequence,
  active,
  fetchPage,
  invalidate,
  schedule = setTimeout,
  cancel = clearTimeout,
}: {
  sequence: string;
  active: () => boolean;
  fetchPage: (
    sequence: string,
  ) => Promise<{ data: unknown[]; next_seq: number | bigint }>;
  invalidate: () => Promise<unknown>;
  schedule?: typeof setTimeout;
  cancel?: typeof clearTimeout;
}) {
  let stopped = false,
    delay = 10000,
    timer: ReturnType<typeof setTimeout>;
  const poll = async () => {
    if (stopped) return;
    if (!active()) {
      timer = schedule(poll, 10000);
      return;
    }
    try {
      const result = await fetchPage(sequence);
      if (stopped) return;
      sequence = String(result.next_seq);
      if (result.data.length) await invalidate();
      delay = result.data.length === 200 ? 1000 : 10000;
    } catch {
      delay = Math.min(delay * 2, 120000);
    }
    if (!stopped) timer = schedule(poll, delay);
  };
  timer = schedule(poll, 10000);
  return () => {
    stopped = true;
    cancel(timer);
  };
}
