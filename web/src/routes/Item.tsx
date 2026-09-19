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
import { renderMarkdown } from '../markdown/render';
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
type History = {
  seq: number | bigint;
  kind: string;
  field: string;
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
      <a href="/">Back to backlog</a>
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
  return (
    <>
      <p className="muted" style={{ marginTop: '1rem' }}>
        {item.key} / {item.project.name} / {item.type.name}
      </p>
      <h1 ref={heading} tabIndex={-1}>
        {item.title}
      </h1>
      {item.deleted_at ? (
        <div className="notice" role="status">
          Deleted on {new Date(item.deleted_at).toLocaleString()}. This
          permanent link preserves the item’s record.
        </div>
      ) : (
        config.data &&
        !isProblem(config.data) && (
          <ItemActions
            item={item}
            config={config.data}
            workspace={workspace}
            userID={state.me.id}
          />
        )
      )}
      <div className="detail-grid">
        <section>
          <h2>Description</h2>
          {item.body ? (
            <Markdown text={item.body} />
          ) : (
            <p className="muted">No description yet.</p>
          )}
          <h2>Comments</h2>
          {comments.error && <p role="alert">{comments.error.message}</p>}
          {comments.data?.pages
            .flatMap((p) => p.data)
            .map((c) => (
              <article className="panel" key={c.id}>
                <p>
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
                    <Markdown text={c.body ?? ''} />
                    {!item.deleted_at && (
                      <div className="toolbar">
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
            <button
              disabled={comments.isFetchingNextPage}
              onClick={() => void comments.fetchNextPage()}
            >
              Load more comments
            </button>
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
          <h2>History</h2>
          {history.error && <p role="alert">{history.error.message}</p>}
          <ol>
            {history.data?.pages
              .flatMap((p) => p.data)
              .map((h) => (
                <li className="panel" key={String(h.seq)}>
                  <p>
                    <strong>{h.actor?.display_name ?? 'System'}</strong>{' '}
                    {h.kind.replaceAll('_', ' ')} {h.field}{' '}
                    <time dateTime={h.at}>
                      {new Date(h.at).toLocaleString()}
                    </time>
                  </p>
                  {h.field && (
                    <div>
                      <p>Before: {format(h.old_value)}</p>
                      <p>After: {format(h.new_value)}</p>
                    </div>
                  )}
                </li>
              ))}
          </ol>
          {history.hasNextPage && (
            <button
              disabled={history.isFetchingNextPage}
              onClick={() => void history.fetchNextPage()}
            >
              Load more history
            </button>
          )}
        </section>
        <aside>
          <section className="panel">
            <h2>Details</h2>
            <dl>
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
              <p key={k}>
                {config.data?.fields.find((f) => f.key === k)?.name ?? k}:{' '}
                {format(v)}
              </p>
            ))}
          </section>
          {item.rollup?.descendant_count > 0 && (
            <section className="panel">
              <h2>Progress</h2>
              <p>
                {item.rollup.done_count} of {item.rollup.descendant_count}{' '}
                descendant items done
              </p>
              {item.rollup.points_total !== null && (
                <p>
                  {item.rollup.points_done ?? 0} of {item.rollup.points_total}{' '}
                  points done
                </p>
              )}
            </section>
          )}
          <section className="panel">
            <h2>Linked items</h2>
            {links.error && <p role="alert">{links.error.message}</p>}
            {links.data?.pages
              .flatMap((p) => p.data)
              .map((l) => (
                <div key={l.id}>
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
                  {!item.deleted_at && l.from.key === item.key && (
                    <Dialog trigger="Remove link" title="Remove link?">
                      <ActionForm
                        item={item}
                        workspace={workspace}
                        path={'/links/' + l.id}
                        method="DELETE"
                        label="Remove link"
                        body={() => undefined}
                      >
                        <p>Remove the relationship to {l.to.key}.</p>
                      </ActionForm>
                    </Dialog>
                  )}
                </div>
              ))}
            {links.hasNextPage && (
              <button onClick={() => void links.fetchNextPage()}>
                Load more links
              </button>
            )}
          </section>
        </aside>
      </div>
    </>
  );
}
function format(value: unknown): string {
  if (value === null || value === undefined) return 'Not set';
  if (typeof value === 'object')
    return JSON.stringify(value, (_, v) =>
      typeof v === 'bigint' ? String(v) : v,
    );
  return String(value);
}
