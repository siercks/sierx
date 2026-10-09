import { Suspense, lazy, useEffect, useRef, useState } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { defaultRangeExtractor, useVirtualizer } from '@tanstack/react-virtual';
import {
  bootstrap,
  cache,
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
import { ProjectNavigation } from '../components/ProjectNavigation';
const ProjectManagement = lazy(() => import('../components/ProjectManagement').then((module) => ({ default: module.ProjectManagement })));
type State = {
  me: Me;
  auth_mode: string;
  query: string;
  items: Page<Item> | Problem;
  projects: Page<Project>;
  project?: string;
  selected_project?: Project;
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
        className="sx-row item-row"
        data-cat={item.status.category}
        data-type={item.type.name.toLowerCase().replaceAll(' ', '-')}
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
          <strong className="sx-key item-key">{item.key}</strong>
          <small className="sx-type item-type">{item.type.name}</small>
        </span>
        <div className="item-summary">
          <a className="sx-row-title item-title" href={'/' + item.key}>
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
      className="sx-list sx-virtual-list list-viewport"
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
  const [project, setProject] = useState(state.project ?? '');
  const [managing, setManaging] = useState(false);
  const [projectRows, setProjectRows] = useState(state.projects.data ?? []);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const initialMatches = query === state.query && project === (state.project ?? '');
  const initialProblem = initialMatches && isProblem(state.items) ? state.items : null;
  const selectedProjectQuery = useQuery({
    queryKey: [state.me.workspace_id, 'project', project],
    queryFn: ({ signal }) => request<Project>(`/projects/${encodeURIComponent(project)}`, { signal }),
    enabled: !!project,
    initialData: state.selected_project?.key_prefix === project ? state.selected_project : undefined,
  });
  const result = useInfiniteQuery({
    queryKey: listKey(state.me.workspace_id, query, project),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      request<Page<Item>>(
        `/items?${new URLSearchParams({ fields: LIST_FIELDS, q: query, limit: '100', ...(project ? { project } : {}), ...(pageParam ? { cursor: pageParam } : {}) })}`,
        { signal },
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    initialData: !initialMatches || initialProblem
      ? undefined
      : { pages: [state.items as Page<Item>], pageParams: [null] },
    enabled: !initialProblem,
  });
  useEffect(() => {
    const update = () => {
      setProject(new URLSearchParams(location.search).get('project') ?? '');
      setQuery(new URLSearchParams(location.search).get('q') ?? '');
    };
    window.addEventListener('popstate', update);
    return () => window.removeEventListener('popstate', update);
  }, []);
  useEffect(() => {
    const active = listKey(state.me.workspace_id, query, project);
    const contexts = cache.getQueryCache().findAll({ queryKey: [state.me.workspace_id, 'list'] });
    const recent = contexts
      .filter((entry) => entry.state.data !== undefined)
      .sort((a, b) => b.state.dataUpdatedAt - a.state.dataUpdatedAt)
      .slice(0, 3);
    for (const entry of contexts) {
      const isActive = entry.queryKey.length === active.length && entry.queryKey.every((value, index) => value === active[index]);
      if (!isActive && !recent.includes(entry)) cache.removeQueries({ queryKey: entry.queryKey, exact: true });
    }
  }, [state.me.workspace_id, query, project]);
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
  const projects = projectRows;
  const selected = selectedProjectQuery.data ?? projects.find((item) => item.key_prefix === project) ?? null;
  useEffect(() => { document.title = `${selected ? selected.name : 'Workspace'} · Sierx`; }, [selected?.name]);
  function navigateProject(key: string) {
    const url = new URL(location.href);
    if (key) url.searchParams.set('project', key); else url.searchParams.delete('project');
    history.pushState({}, '', url);
    setProject(key);
  }
  function projectSaved(saved: Project) {
    setProjectRows((current) => [...new Map([...current, saved].map((item) => [item.key_prefix, item])).values()]);
    cache.setQueryData([state.me.workspace_id, 'project', saved.key_prefix], saved);
    void cache.invalidateQueries({ queryKey: [state.me.workspace_id, 'projects'] });
    navigateProject(saved.key_prefix);
  }
  return (
    <Shell me={state.me} authMode={state.auth_mode}>
      <section className="sx-main-h page-heading">
        <div>
          <p className="eyebrow">{selected ? 'Project dashboard' : 'Workspace'}</p>
          <h1 className="sx-main-title">{selected?.name ?? 'Your backlog'}</h1>
          <p className="sx-main-sub page-description">{selected ? `${selected.key_prefix} · ${selected.kind}` : 'Keep the work moving, one clear next step at a time.'}</p>
        </div>
        <Create
          projects={projects}
          workspace={state.me.workspace_id}
          defaultProject={project}
          projectsNextCursor={state.projects.next_cursor}
          selectedProject={selected}
        />
      </section>
      <ProjectNavigation workspace={state.me.workspace_id} me={state.me} projectPage={state.projects} selected={selected} onNavigate={navigateProject} onManage={() => setManaging(true)} />
      {managing && state.me.role === 'admin' && <Suspense fallback={<p role="status">Loading project management…</p>}><ProjectManagement project={selected ?? undefined} workspace={state.me.workspace_id} onSaved={projectSaved} onDismiss={() => setManaging(false)} /></Suspense>}
      <form action="/" method="get" className="search-panel">
        {project && <input type="hidden" name="project" value={project} />}
        <label className="sx-field search-field workflow-field">
          <span>Search backlog</span>
          <input
            id="query"
            name="q"
            className="sx-control"
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
          {query && (
            <a className="button button-ghost" href={project ? `/?project=${encodeURIComponent(project)}` : '/'}>
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
            <h2 className="sx-main-title">{query ? 'Search results' : selected ? 'Project work' : 'All work'}</h2>
              <p className="muted">{selected ? `Items in ${selected.name}` : 'Items in this workspace'}</p>
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
              {query
                ? 'No items match this query'
                : 'Your backlog starts here'}
            </h2>
            <p>
              {query
                ? 'Clear the query or create an item.'
                : 'Create an item to capture the work ahead.'}
            </p>
            {query && <a className="button button-outline" href={project ? `/?project=${encodeURIComponent(project)}` : '/'}>Clear query</a>}
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
