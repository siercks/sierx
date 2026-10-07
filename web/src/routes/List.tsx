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
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
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
        <span className="item-identity">
          <strong className="item-key">{item.key}</strong>
          <small className="item-type">{item.type.name}</small>
        </span>
        <div className="item-summary">
          <a className="item-title" href={'/' + item.key}>
            {item.title}
          </a>
          <small className="item-meta">
            {item.project.key_prefix !== item.key.split('-')[0]
              ? `${item.project.name} (${item.project.key_prefix})`
              : item.project.name}
            {item.assignee ? ` · ${item.assignee.display_name}` : ''}
          </small>
        </div>
        <Badge
          variant={item.status.category as 'open' | 'active' | 'done' | 'cancelled'}
          className="item-status"
        >
          {item.status.name}
        </Badge>
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
      <section className="page-heading">
        <div>
          <p className="eyebrow">Workspace</p>
          <h1>Your backlog</h1>
          <p className="page-description">
            Keep the work moving, one clear next step at a time.
          </p>
        </div>
        <Create
          projects={state.projects.data ?? []}
          workspace={state.me.workspace_id}
        />
      </section>
      <form action="/" method="get" className="search-panel">
        <label className="search-field">
          <span>Search backlog</span>
          <input
            id="query"
            name="q"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Try project = SRX or status = active"
            list="suggestions"
            autoComplete="off"
          />
        </label>
        <datalist id="suggestions">
          {suggestions.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
        <div className="search-actions">
          <Button variant="default" type="submit">
            Search
          </Button>
          {state.query && (
            <a className="button button-ghost" href="/">
              Clear
            </a>
          )}
        </div>
      </form>
      {initialProblem && (
        <p className="alert alert-error" role="alert">
          {initialProblem.detail || initialProblem.title}
        </p>
      )}
      {result.error && (
        <div className="alert alert-error" role="alert">
          {result.error.message}{' '}
          <Button variant="outline" onClick={() => void result.refetch()}>
            Try again
          </Button>
        </div>
      )}
      {result.isPending && !initialProblem ? (
        <p role="status">Loading items…</p>
      ) : unique.length ? (
        <>
          <div className="list-heading">
            <div>
              <h2>{state.query ? 'Search results' : 'All work'}</h2>
              <p className="muted">Items in this workspace</p>
            </div>
            <Badge variant="outline">{unique.length} loaded</Badge>
          </div>
          <Rows items={unique} />
          <p className="list-footnote" role="status">
            {unique.length} items loaded
            {result.isFetching ? ' · Refreshing…' : ''}
          </p>
        </>
      ) : (
        !initialProblem && (
          <section className="empty-state">
            <div className="empty-icon" aria-hidden="true">+</div>
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
            {state.query && <a className="button button-outline" href="/">Clear query</a>}
          </section>
        )
      )}
      {result.hasNextPage ? (
        <Button
          variant="outline"
          className="load-more"
          disabled={result.isFetchingNextPage}
          onClick={() => void result.fetchNextPage()}
        >
          {result.isFetchingNextPage ? 'Loading more…' : 'Load more items'}
        </Button>
      ) : (
        unique.length > 0 && (
          <p className="list-footnote">You’re all caught up. Every matching item is loaded.</p>
        )
      )}
    </Shell>
  );
}
