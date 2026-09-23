import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  APIError,
  encode,
  useItemWrite,
  type Item,
  type Config,
  type Write,
} from '../api/client';
import { Dialog } from './ui/dialog';
import { CustomFields, customValues } from './Fields';

export function ActionForm({
  item,
  workspace,
  label,
  path,
  method = 'POST',
  children,
  body,
  optimistic,
  resetOnSuccess = false,
}: {
  item: Item;
  workspace: string;
  label: string;
  path: string;
  method?: string;
  children: ReactNode;
  body: (data: FormData) => unknown;
  optimistic?: (data: FormData) => Partial<Item>;
  resetOnSuccess?: boolean;
}) {
  const form = useRef<HTMLFormElement>(null);
  const mutation = useItemWrite(workspace, item.key);
  const [version, setVersion] = useState(item.version);
  const [dirty, setDirty] = useState(false);
  const [conflict, setConflict] = useState<{
    current: Item;
    write: Write;
  } | null>(null);
  const [error, setError] = useState(''),
    [success, setSuccess] = useState(false),
    [needsLogin, setNeedsLogin] = useState(false);
  useEffect(() => {
    if (!dirty && !conflict && !mutation.isPending) setVersion(item.version);
  }, [item.version, dirty, conflict, mutation.isPending]);
  async function send(write: Write) {
    setSuccess(false);
    setError('');
    setNeedsLogin(false);
    try {
      await mutation.mutateAsync(write);
      setConflict(null);
      setSuccess(true);
      window.dispatchEvent(new Event('sierx:resumed'));
      setDirty(false);
      setVersion(write.version + 1);
      if (resetOnSuccess) form.current?.reset();
    } catch (e) {
      if (
        e instanceof APIError &&
        e.problem.status === 409 &&
        e.problem.current
      )
        setConflict({ current: e.problem.current, write });
      else {
        setError((e as Error).message);
        setNeedsLogin(e instanceof APIError && e.problem.status === 401);
      }
    }
  }
  return (
    <form
      ref={form}
      onChangeCapture={() => {
        if (!dirty) setVersion(item.version);
        setDirty(true);
        setSuccess(false);
      }}
      onSubmit={(e) => {
        e.preventDefault();
        if (mutation.isPending || conflict) return;
        const data = new FormData(e.currentTarget);
        try {
          void send({
            path,
            method,
            body: body(data),
            version,
            optimistic: optimistic?.(data),
          });
        } catch (e) {
          setError((e as Error).message);
        }
      }}
    >
      <fieldset
        disabled={mutation.isPending}
        style={{ display: 'grid', gap: '1rem' }}
      >
        <legend className="sr-only">{label}</legend>
        {children}
      </fieldset>
      {error && (
        <div className="error" role="alert">
          <p>{error}</p>
          {needsLogin && (
            <p>
              Keep this dialog open to preserve your draft.{' '}
              <a href="/login" target="_blank" rel="noopener noreferrer">
                Sign in in a new tab
              </a>
              , then submit again.
            </p>
          )}
        </div>
      )}
      {success && <p role="status">{label} completed.</p>}
      {conflict && (
        <section
          className="error"
          role="alert"
          aria-label="Conflicting changes"
        >
          <h3>
            Someone else changed this item. Review the differences and retry.
          </h3>
          <p>
            Your draft is preserved. Retry applies your submitted changes to
            version {conflict.current.version}.
          </p>
          <table>
            <thead>
              <tr>
                <th scope="col">Field</th>
                <th scope="col">Current value</th>
                <th scope="col">Your submission</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(
                (conflict.write.body ?? {}) as Record<string, unknown>,
              ).map(([key, value]) => (
                <tr key={key}>
                  <th scope="row">{key}</th>
                  <td>
                    {path.startsWith('/comments') ||
                    path.includes('/links') ||
                    key === 'rank_after'
                      ? 'Review the refreshed conversation or relationships before retrying'
                      : encode(
                          key === 'to_status'
                            ? conflict.current.status.key
                            : key === 'parent'
                              ? (conflict.current.parent?.key ?? null)
                              : key === 'assignee'
                                ? (conflict.current.assignee?.id ?? null)
                                : ((
                                    conflict.current as unknown as Record<
                                      string,
                                      unknown
                                    >
                                  )[key] ?? null),
                        )}
                  </td>
                  <td>{encode(value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="toolbar">
            <button
              type="button"
              disabled={mutation.isPending}
              onClick={() =>
                void send({
                  ...conflict.write,
                  version: conflict.current.version,
                })
              }
            >
              Retry my changes
            </button>
            <button
              type="button"
              onClick={() => {
                setVersion(conflict.current.version);
                setConflict(null);
                setError(
                  'Retry cancelled. Your draft is still here; review it before submitting again.',
                );
              }}
            >
              Cancel retry
            </button>
          </div>
        </section>
      )}
      <button className="primary" disabled={mutation.isPending || !!conflict}>
        {mutation.isPending ? 'Saving…' : label}
      </button>
    </form>
  );
}
const optional = (data: FormData, key: string) =>
  String(data.get(key) ?? '').trim() || null;
export function ItemActions({
  item,
  config,
  workspace,
  userID,
}: {
  item: Item;
  config: Config;
  workspace: string;
  userID: string;
}) {
  const [target, setTarget] = useState('');
  const transitions = config.transitions[item.status.key] ?? [];
  const transition =
    transitions.find((t) => t.to_key === target) ?? transitions[0];
  return (
    <div className="toolbar" aria-label="Item actions">
      <Dialog trigger="Edit item" title={'Edit ' + item.key}>
        <ActionForm
          item={item}
          workspace={workspace}
          path={'/items/' + item.key}
          method="PATCH"
          label="Save changes"
          optimistic={(d) => ({
            title: String(d.get('title')),
            body: optional(d, 'body'),
          })}
          body={(d) => ({
            title: d.get('title'),
            body: optional(d, 'body'),
            points:
              optional(d, 'points') === null ? null : Number(d.get('points')),
            start_date: optional(d, 'start_date'),
            due_date: optional(d, 'due_date'),
            assignee: optional(d, 'assignee'),
            fields: customValues(d, config.fields, item.fields),
          })}
        >
          <label>
            Title
            <input
              name="title"
              defaultValue={item.title}
              required
              maxLength={500}
            />
          </label>
          <label>
            Description
            <textarea name="body" defaultValue={item.body ?? ''} />
          </label>
          <label>
            Points
            <input
              type="number"
              name="points"
              min="0"
              step="any"
              defaultValue={item.points ?? ''}
            />
          </label>
          <label>
            Assignee account ID
            <input name="assignee" defaultValue={item.assignee?.id ?? ''} />
          </label>
          <label>
            Start date
            <input
              type="date"
              name="start_date"
              defaultValue={item.start_date ?? ''}
            />
          </label>
          <label>
            Due date
            <input
              type="date"
              name="due_date"
              defaultValue={item.due_date ?? ''}
            />
          </label>
          <CustomFields definitions={config.fields} values={item.fields} />
        </ActionForm>
      </Dialog>
      {!!transitions.length && (
        <Dialog trigger="Change status" title="Change status">
          <ActionForm
            item={item}
            workspace={workspace}
            path={'/items/' + item.key + '/transition'}
            label="Change status"
            body={(d) => {
              const fields: Record<string, unknown> = {};
              for (const field of transition?.requires ?? []) {
                if (field.startsWith('fields.')) continue;
                const value = d.get('required:' + field);
                if (value !== null)
                  fields[field] =
                    field === 'points' ? Number(value) : String(value) || null;
              }
              if (transition?.requires.some((f) => f.startsWith('fields.')))
                fields.fields = customValues(d, config.fields, item.fields);
              return { to_status: d.get('to_status'), fields };
            }}
          >
            <label>
              New status
              <select
                name="to_status"
                value={transition?.to_key}
                onChange={(e) => setTarget(e.target.value)}
              >
                {transitions.map((t) => (
                  <option key={t.to_key} value={t.to_key}>
                    {config.statuses.find((s) => s.key === t.to_key)?.name ??
                      t.to_key}
                  </option>
                ))}
              </select>
            </label>
            <p>
              Required fields: {transition?.requires.join(', ') || 'None'}.
              Existing values count.
            </p>
            {transition?.requires
              .filter((f) => !f.startsWith('fields.'))
              .map((field) =>
                field === 'assignee' ? (
                  <label key={field}>
                    Assign to
                    <select
                      name="required:assignee"
                      defaultValue={item.assignee?.id ?? userID}
                    >
                      <option value={userID}>Me</option>
                      {item.assignee && item.assignee.id !== userID && (
                        <option value={item.assignee.id}>
                          {item.assignee.display_name}
                        </option>
                      )}
                    </select>
                  </label>
                ) : (
                  <label key={field}>
                    {field.replaceAll('_', ' ')}
                    <input
                      name={'required:' + field}
                      type={
                        field === 'points'
                          ? 'number'
                          : field.endsWith('_date')
                            ? 'date'
                            : 'text'
                      }
                      required
                      defaultValue={String(
                        (item as unknown as Record<string, unknown>)[field] ??
                          '',
                      )}
                    />
                  </label>
                ),
              )}
            <CustomFields
              definitions={config.fields.filter((f) =>
                transition?.requires.includes('fields.' + f.key),
              )}
              values={item.fields}
            />
          </ActionForm>
        </Dialog>
      )}
      <Dialog trigger="Move or reorder" title="Move or reorder item">
        <ActionForm
          item={item}
          workspace={workspace}
          path={'/items/' + item.key + '/move'}
          label="Move item"
          body={(d) => ({
            parent: optional(d, 'parent')?.toUpperCase() ?? null,
            rank_after: optional(d, 'rank_after')?.toUpperCase() ?? null,
          })}
        >
          <label>
            Parent item key
            <input
              name="parent"
              defaultValue={item.parent?.key ?? ''}
              placeholder="Leave blank for top level"
            />
          </label>
          <label>
            Place after item key
            <input name="rank_after" placeholder="Leave blank to place first" />
          </label>
          <p className="muted">
            Choose a parent in {item.project.key_prefix}. The preceding item
            must share the destination parent.
          </p>
        </ActionForm>
      </Dialog>
      <Dialog trigger="Link item" title="Link item">
        <ActionForm
          item={item}
          workspace={workspace}
          path={'/items/' + item.key + '/links'}
          label="Add link"
          body={(d) => ({
            to: String(d.get('to')).toUpperCase(),
            kind: d.get('kind'),
          })}
        >
          <label>
            Item key
            <input name="to" required />
          </label>
          <label>
            Relationship
            <select name="kind">
              {[
                'relates',
                'blocks',
                'duplicates',
                'implements',
                'discovered_from',
              ].map((k) => (
                <option key={k} value={k}>
                  {k.replaceAll('_', ' ')}
                </option>
              ))}
            </select>
          </label>
        </ActionForm>
      </Dialog>
      <Dialog trigger="Delete item" title={'Delete ' + item.key + '?'}>
        <ActionForm
          item={item}
          workspace={workspace}
          path={'/items/' + item.key}
          method="DELETE"
          label="Delete item"
          body={() => undefined}
        >
          <p>
            The item leaves active lists. Its permanent link and history remain
            available.
          </p>
        </ActionForm>
      </Dialog>
    </div>
  );
}
