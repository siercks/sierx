import { useEffect, useRef, useState } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import {
  bootstrap,
  request,
  isProblem,
  itemKey,
  DETAIL_FIELDS,
  type Item as ItemData,
  type Page,
  type Config,
  type Me,
  type Problem,
} from '../api/client';
import { Shell } from '../components/Shell';
import { ItemActions, ActionForm } from '../components/ItemActions';
import { Dialog } from '../components/ui/dialog';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { renderMarkdown } from '../markdown/render';
import { historyAction, historyValue } from '../history';
type Comment = {
  id: string;
  body: string | null;
  author: { id: string; display_name: string };
  created_at: string;
  edited_at: string | null;
  deleted_at: string | null;
};
type Link = {
  id: string;
  kind: string;
  from: { key: string; title: string };
  to: { key: string; title: string };
};
type Child = Pick<ItemData, 'key' | 'title' | 'status' | 'rank'>;
type History = {
  seq: number | bigint;
  kind: string;
  field: string | null;
  at: string;
  actor: { display_name: string } | null;
  old_value: unknown;
  new_value: unknown;
};
type State = {
  me: Me;
  auth_mode: string;
  item: ItemData | Problem;
  config: Config;
  comments: Page<Comment>;
  children?: Page<Child>;
  links: Page<Link>;
  history: Page<History>;
};
function Markdown({ text }: { text: string }) {
  return (
    <div
      className="markdown"
      dangerouslySetInnerHTML={{ __html: renderMarkdown(text) }}
    />
  );
}
function format(value: unknown): string {
  if (value === null || value === undefined) return 'Not set';
  if (typeof value === 'object')
    return JSON.stringify(value, (_, nested) =>
      typeof nested === 'bigint' ? String(nested) : nested,
    );
  return String(value);
}
function usePages<T>(
  workspace: string,
  kind: string,
  key: string,
  path: string,
  initial: Page<T> | undefined,
  enabled = true,
) {
  return useInfiniteQuery({
    queryKey: [workspace, kind, key],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      request<Page<T>>(
        path +
          (path.includes('?') ? '&' : '?') +
          (pageParam ? `cursor=${encodeURIComponent(pageParam)}` : ''),
        { signal },
      ),
    getNextPageParam: (p) => p.next_cursor ?? undefined,
    initialData:
      initial && !isProblem(initial)
        ? { pages: [initial], pageParams: [null] }
        : undefined,
    enabled,
  });
}
export default function Item() {
  const state = useState(() => bootstrap<State>())[0];
  const key = location.pathname.slice(1);
  const result = useQuery({
    queryKey: itemKey(state.me.workspace_id, key),
    queryFn: () => request<ItemData>(`/items/${key}?fields=${DETAIL_FIELDS}`),
    initialData: isProblem(state.item) ? undefined : state.item,
    enabled: !isProblem(state.item),
  });
  const item = result.data;
  return (
    <Shell me={state.me} authMode={state.auth_mode}>
      <nav className="breadcrumbs" aria-label="Breadcrumb">
        <a href="/">Workspace</a>
        <span aria-hidden="true">/</span>
        <span>{key}</span>
      </nav>
      {isProblem(state.item) ? (
        <>
          <h1>Item unavailable</h1>
          <p role="alert">{state.item.detail || state.item.title}</p>
        </>
      ) : item ? (
        <Detail state={state} item={item} />
      ) : (
        <p role="status">Loading item…</p>
      )}
      {result.error && (
        <p className="error" role="alert">
          {result.error.message}
        </p>
      )}
    </Shell>
  );
}
function Detail({ state, item }: { state: State; item: ItemData }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (item.deleted_at) {
      const frame = requestAnimationFrame(() => heading.current?.focus());
      return () => cancelAnimationFrame(frame);
    }
  }, [item.deleted_at]);
  const workspace = state.me.workspace_id;
  const config = useQuery({
    queryKey: [workspace, 'config', item.project.key_prefix],
    queryFn: () =>
      request<Config>(`/projects/${item.project.key_prefix}/config`),
    initialData: state.config,
  });
  const comments = usePages<Comment>(
    workspace,
    'comments',
    item.key,
    `/comments?item=${item.key}`,
    state.comments,
    !item.deleted_at,
  );
  const links = usePages<Link>(
    workspace,
    'links',
    item.key,
    `/items/${item.key}/links`,
    state.links,
    !item.deleted_at,
  );
  const history = usePages<History>(
    workspace,
    'history',
    item.key,
    `/items/${item.key}/history`,
    state.history,
  );
  const childQuery = new URLSearchParams({
    q: `parent = "${item.key}" order by rank`,
    fields: 'key,title,status,rank',
    limit: '100',
  });
  const children = usePages<Child>(
    workspace,
    'children',
    item.key,
    `/items?${childQuery}`,
    state.children,
    !item.deleted_at,
  );
  const statuses = config.data?.statuses ?? state.config.statuses;
  return (
    <>
      <header className="item-heading">
        <div className="item-heading-copy">
          <p className="eyebrow">
            {item.key} <span aria-hidden="true">·</span> {item.project.name} <span aria-hidden="true">·</span> {item.type.name}
          </p>
          <div className="item-heading-title">
            <h1 ref={heading} tabIndex={-1}>{item.title}</h1>
            <Badge variant={item.status.category as 'open' | 'active' | 'done' | 'cancelled'}>
              {item.status.name}
            </Badge>
          </div>
          {item.deleted_at && (
            <div className="alert alert-notice" role="status">
              Deleted on {new Date(item.deleted_at).toLocaleString()}. This
              permanent link preserves the item's record.
            </div>
          )}
        </div>
        {!item.deleted_at && config.data && !isProblem(config.data) && (
          <div className="item-actions" aria-label="Item actions">
            <ItemActions
              item={item}
              config={config.data}
              workspace={workspace}
              userID={state.me.id}
            />
          </div>
        )}
      </header>
      <div className="detail-grid">
        <div className="item-main-column">
          <section className="card description-card">
            <div className="card-heading">
              <h2>Description</h2>
            </div>
            {item.body ? (
              <Markdown text={item.body} />
            ) : (
              <p className="muted">No description yet.</p>
            )}
          </section>
          {!item.deleted_at && (
            <section className="card" aria-labelledby="children-heading">
              <div className="card-heading">
                <h2 id="children-heading">Direct children</h2>
                <Badge variant="outline">
                  {children.data?.pages.flatMap((page) => page.data).length ?? 0}
                </Badge>
              </div>
              {children.error && <p className="alert alert-error" role="alert">{children.error.message}</p>}
              {children.data?.pages.every((page) => page.data.length === 0) && (
                <p className="muted">No direct children.</p>
              )}
              <ol
                className="children-list"
                aria-label="Direct children, in order"
              >
                {children.data?.pages
                  .flatMap((page) => page.data)
                  .map((child) => (
                    <li key={child.key}>
                      <a href={'/' + child.key}>
                        <strong>{child.key}</strong>: {child.title}
                      </a>
                      <Badge variant={child.status.category as 'open' | 'active' | 'done' | 'cancelled'}>
                        {child.status.name}
                      </Badge>
                    </li>
                  ))}
              </ol>
              {children.hasNextPage && (
                <Button
                  variant="outline"
                  disabled={children.isFetchingNextPage}
                  onClick={() => void children.fetchNextPage()}
                >
                  Load more children
                </Button>
              )}
            </section>
          )}
          <section className="card" aria-labelledby="comments-heading">
            <div className="card-heading">
              <h2 id="comments-heading">Comments</h2>
              <Badge variant="outline">
                {comments.data?.pages.flatMap((page) => page.data).length ?? 0}
              </Badge>
            </div>
          {comments.error && (
            <p className="alert alert-error" role="alert">
              {comments.error.message}
            </p>
          )}
          {comments.data?.pages
            .flatMap((p) => p.data)
            .map((c) => (
              <article className="comment-card" key={c.id}>
                <p className="comment-meta">
                  <strong>{c.author.display_name}</strong>{' '}
                  <time dateTime={c.created_at}>
                    {new Date(c.created_at).toLocaleString()}
                  </time>
                  {c.edited_at ? ' (edited)' : ''}
                </p>
                {c.deleted_at ? (
                  <p className="muted">Comment deleted.</p>
                ) : (
                  <>
                    <div className="comment-body">
                      <Markdown text={c.body ?? ''} />
                    </div>
                    {!item.deleted_at && (
                      <div className="comment-actions">
                        {c.author.id === state.me.id && (
                          <Dialog trigger="Edit comment" title="Edit comment">
                            <ActionForm
                              item={item}
                              workspace={workspace}
                              path={'/comments/' + c.id}
                              method="PATCH"
                              label="Save comment"
                              body={(d) => ({ body: d.get('body') })}
                            >
                              <label>
                                Comment
                                <textarea
                                  name="body"
                                  required
                                  defaultValue={c.body ?? ''}
                                />
                              </label>
                            </ActionForm>
                          </Dialog>
                        )}
                        {(c.author.id === state.me.id ||
                          state.me.role === 'admin') && (
                          <Dialog
                            trigger="Delete comment"
                            title="Delete comment?"
                          >
                            <ActionForm
                              item={item}
                              workspace={workspace}
                              path={'/comments/' + c.id}
                              method="DELETE"
                              label="Delete comment"
                              body={() => undefined}
                            >
                              <p>
                                The comment will be removed from this
                                conversation.
                              </p>
                            </ActionForm>
                          </Dialog>
                        )}
                      </div>
                    )}
                  </>
                )}
              </article>
            ))}
          {comments.hasNextPage && (
            <Button
              variant="outline"
              disabled={comments.isFetchingNextPage}
              onClick={() => void comments.fetchNextPage()}
            >
              Load more comments
            </Button>
          )}
          {!item.deleted_at && (
            <ActionForm
              item={item}
              workspace={workspace}
              path="/comments"
              label="Add comment"
              resetOnSuccess
              body={(d) => ({ item: item.key, body: d.get('body') })}
            >
              <label>
                New comment
                <textarea
                  name="body"
                  required
                  placeholder="Write a comment in Markdown"
                />
              </label>
            </ActionForm>
          )}
          </section>
          <section className="card" aria-labelledby="history-heading">
          <div className="card-heading">
            <h2 id="history-heading">History</h2>
            <Badge variant="outline">
              {history.data?.pages.flatMap((page) => page.data).length ?? 0}
            </Badge>
          </div>
          {history.error && <p className="alert alert-error" role="alert">{history.error.message}</p>}
          <ol className="history-list">
            {history.data?.pages
              .flatMap((p) => p.data)
              .map((h) => (
                <li className="history-entry" key={String(h.seq)}>
                  <p className="history-meta">
                    <strong>{h.actor?.display_name ?? 'System'}</strong>{' '}
                    {historyAction(h)}{' '}
                    <time dateTime={h.at}>
                      {new Date(h.at).toLocaleString()}
                    </time>
                  </p>
                  {h.field && (
                    <div>
                      <p>
                        Before:{' '}
                        {historyValue(h, h.old_value, statuses)}
                      </p>
                      <p>
                        After:{' '}
                        {historyValue(h, h.new_value, statuses)}
                      </p>
                    </div>
                  )}
                </li>
              ))}
          </ol>
          {history.hasNextPage && (
            <Button
              variant="outline"
              disabled={history.isFetchingNextPage}
              onClick={() => void history.fetchNextPage()}
            >
              Load more history
            </Button>
          )}
          </section>
        </div>
        <aside className="item-sidebar">
          <section className="card" aria-labelledby="details-heading">
            <div className="card-heading"><h2 id="details-heading">Details</h2></div>
            <dl className="detail-list">
              <dt>Status</dt>
              <dd className={'status status-' + item.status.category}>
                {item.status.name}
              </dd>
              <dt>Assignee</dt>
              <dd>{item.assignee?.display_name ?? 'Unassigned'}</dd>
              <dt>Parent</dt>
              <dd>
                {item.parent ? (
                  <a href={'/' + item.parent.key}>{item.parent.key}</a>
                ) : (
                  'Top level'
                )}
              </dd>
              <dt>Points</dt>
              <dd>{item.points ?? 'Not set'}</dd>
              <dt>Start date</dt>
              <dd>{item.start_date ?? 'Not set'}</dd>
              <dt>Due date</dt>
              <dd>{item.due_date ?? 'Not set'}</dd>
            </dl>
            {Object.entries(item.fields ?? {}).map(([k, v]) => (
              <p className="custom-detail" key={k}>
                {config.data?.fields.find((f) => f.key === k)?.name ?? k}:{' '}
                {format(v)}
              </p>
            ))}
          </section>
          {item.rollup?.descendant_count > 0 && (
            <section className="card">
              <div className="card-heading"><h2>Progress</h2></div>
              <p>
                {item.rollup.done_count} of {item.rollup.descendant_count}{' '}
                descendant items done
              </p>
              <div
                className="progress-track"
                role="progressbar"
                aria-label="Descendant items complete"
                aria-valuemin={0}
                aria-valuemax={item.rollup.descendant_count}
                aria-valuenow={item.rollup.done_count}
              >
                <span style={{ width: `${Math.min(100, (item.rollup.done_count / item.rollup.descendant_count) * 100)}%` }} />
              </div>
              {item.rollup.points_total !== null && (
                <p>
                  {item.rollup.points_done ?? 0} of {item.rollup.points_total}{' '}
                  points done
                </p>
              )}
            </section>
          )}
          <section className="card">
            <div className="card-heading"><h2>Linked items</h2></div>
            {links.error && <p className="alert alert-error" role="alert">{links.error.message}</p>}
            {links.data?.pages
              .flatMap((p) => p.data)
              .map((l) => (
                <div className="linked-item" key={l.id}>
                  <p>
                    {l.kind.replaceAll('_', ' ')}:{' '}
                    <a
                      href={
                        '/' + (l.from.key === item.key ? l.to.key : l.from.key)
                      }
                    >
                      {l.from.key === item.key ? l.to.key : l.from.key}
                    </a>
                  </p>
                  {!item.deleted_at && (
                    <Dialog trigger="Remove link" title="Remove link?">
                      <ActionForm
                        item={item}
                        workspace={workspace}
                        path={
                          '/links/' + l.id + '?item=' + encodeURIComponent(item.key)
                        }
                        method="DELETE"
                        label="Remove link"
                        body={() => undefined}
                      >
                        <p>
                          Remove the relationship to{' '}
                          {l.from.key === item.key ? l.to.key : l.from.key}.
                        </p>
                      </ActionForm>
                    </Dialog>
                  )}
                </div>
              ))}
            {links.hasNextPage && (
              <Button variant="outline" onClick={() => void links.fetchNextPage()}>
                Load more links
              </Button>
            )}
          </section>
        </aside>
      </div>
    </>
  );
}
