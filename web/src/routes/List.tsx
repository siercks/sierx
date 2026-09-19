import { useEffect, useRef, useState } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { defaultRangeExtractor, useVirtualizer } from '@tanstack/react-virtual';
import {
  bootstrap,
  request,
  isProblem,
  listKey,
  LIST_FIELDS,
  type Item,
  type Page,
  type Me,
  type Project,
  type Problem,
} from '../api/client';
import { Shell } from '../components/Shell';
import { Create } from '../components/Create';
type State = {
  me: Me;
  auth_mode: string;
  query: string;
  items: Page<Item> | Problem;
  projects: Page<Project>;
};
export function Rows({ items }: { items: Item[] }) {
  const viewport = useRef<HTMLDivElement>(null);
  const [focused, setFocused] = useState(-1);
  const virtual = useVirtualizer({
    count: items.length,
    getScrollElement: () => viewport.current,
    estimateSize: () => 76,
    overscan: 5,
    rangeExtractor: (range) =>
      [
        ...new Set([
          ...defaultRangeExtractor(range),
          ...(focused >= 0 && focused < items.length ? [focused] : []),
        ]),
      ].sort((a, b) => a - b),
  });
  function row(item: Item, index: number, style?: React.CSSProperties) {
    return (
      <div
        role="listitem"
        className="item-row"
        key={item.id}
        data-index={index}
        ref={items.length > 50 ? virtual.measureElement : undefined}
        style={style}
        onFocusCapture={() => setFocused(index)}
        onBlurCapture={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node))
            setFocused(-1);
        }}
      >
        <span>
          {item.key}
          <small>{item.type.name}</small>
        </span>
        <div>
          <a href={'/' + item.key}>{item.title}</a>
          <small>
            {item.project.key_prefix !== item.key.split('-')[0]
              ? `${item.project.name} (${item.project.key_prefix})`
              : item.project.name}
            {item.assignee ? ` · ${item.assignee.display_name}` : ''}
          </small>
        </div>
        <span className={'status status-' + item.status.category}>
          {item.status.name}
        </span>
      </div>
    );
  }
  return (
    <div
      ref={viewport}
      className="list-viewport"
      role="region"
      aria-label="Backlog items"
      tabIndex={0}
    >
      <div
        role="list"
        aria-label="Items"
        style={
          items.length > 50
            ? { height: virtual.getTotalSize(), position: 'relative' }
            : undefined
        }
      >
        {items.length > 50
          ? virtual
              .getVirtualItems()
              .map((v) =>
                row(items[v.index], v.index, {
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  transform: `translateY(${v.start}px)`,
                }),
              )
          : items.map((item, index) => row(item, index))}
      </div>
    </div>
  );
}
export default function List() {
  const state = useState(() => bootstrap<State>())[0];
  const [query, setQuery] = useState(state.query);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const initialProblem = isProblem(state.items) ? state.items : null;
  const result = useInfiniteQuery({
    queryKey: listKey(state.me.workspace_id, state.query),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      request<Page<Item>>(
        `/items?${new URLSearchParams({ fields: LIST_FIELDS, q: state.query, limit: '100', ...(pageParam ? { cursor: pageParam } : {}) })}`,
        { signal },
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    initialData: initialProblem
      ? undefined
      : { pages: [state.items as Page<Item>], pageParams: [null] },
    enabled: !initialProblem,
  });
  useEffect(() => {
    const controller = new AbortController();
    const timeout = setTimeout(() => {
      if (query !== state.query)
        void request<{ suggestions: string[] }>(
          `/sxq/complete?partial=${encodeURIComponent(query)}`,
          { signal: controller.signal },
        )
          .then((r) => setSuggestions(r.suggestions))
          .catch(() => setSuggestions([]));
    }, 250);
    return () => {
      clearTimeout(timeout);
      controller.abort();
    };
  }, [query, state.query]);
  const items = result.data?.pages.flatMap((p) => p.data) ?? [];
  const unique = [...new Map(items.map((i) => [i.id, i])).values()];
  return (
    <Shell me={state.me} authMode={state.auth_mode}>
      <div className="toolbar">
        <div style={{ flex: 1 }}>
          <h1>Your backlog</h1>
          <p className="muted">Find your next step. Keep the details close.</p>
        </div>
        <Create
          projects={state.projects.data ?? []}
          workspace={state.me.workspace_id}
        />
      </div>
      <form action="/" method="get" className="toolbar">
        <label>
          Search with SXQ
          <input
            id="query"
            name="q"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="project = SRX"
            list="suggestions"
            autoComplete="off"
          />
        </label>
        <datalist id="suggestions">
          {suggestions.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
        <button className="primary">Search</button>
        {state.query && <a href="/">Clear query</a>}
      </form>
      {initialProblem && (
        <p className="error" role="alert">
          {initialProblem.detail || initialProblem.title}
        </p>
      )}
      {result.error && (
        <div className="error" role="alert">
          {result.error.message}{' '}
          <button onClick={() => void result.refetch()}>Try again</button>
        </div>
      )}
      {result.isPending && !initialProblem ? (
        <p role="status">Loading items…</p>
      ) : unique.length ? (
        <>
          <Rows items={unique} />
          <p className="muted" role="status">
            {unique.length} items loaded
            {result.isFetching ? ' · Refreshing…' : ''}
          </p>
        </>
      ) : (
        !initialProblem && (
          <section className="panel">
            <h2>
              {state.query
                ? 'No items match this query'
                : 'Your backlog starts here'}
            </h2>
            <p>
              {state.query
                ? 'Clear the query or create an item.'
                : 'Create an item to capture the work ahead.'}
            </p>
            {state.query && <a href="/">Clear query</a>}
          </section>
        )
      )}
      {result.hasNextPage ? (
        <button
          disabled={result.isFetchingNextPage}
          onClick={() => void result.fetchNextPage()}
        >
          {result.isFetchingNextPage ? 'Loading more…' : 'Load more items'}
        </button>
      ) : (
        unique.length > 0 && (
          <p className="muted">All matching items are loaded.</p>
        )
      )}
    </Shell>
  );
}
