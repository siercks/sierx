import { useId, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { request, type Config, type Project, type Item } from '../api/client';
import { Dialog } from './ui/dialog';
import { Button } from './ui/button';
export function Create({
  projects,
  workspace,
}: {
  projects: Project[];
  workspace: string;
}) {
  return (
    <Dialog
      trigger="Create item"
      title="Create item"
      triggerVariant="default"
    >
      <CreateForm projects={projects} workspace={workspace} />
    </Dialog>
  );
}
function CreateForm({
  projects,
  workspace,
}: {
  projects: Project[];
  workspace: string;
}) {
  const typeID = useId();
  const statusHintID = useId();
  const [project, setProject] = useState(
    projects.find((p) => !p.archived_at)?.key_prefix ?? '',
  );
  const [type, setType] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const config = useQuery({
    queryKey: [workspace, 'config', project],
    queryFn: () => request<Config>(`/projects/${project}/config`),
    enabled: !!project,
  });
  const selected =
    config.data?.types.find((t) => t.key === type) ?? config.data?.types[0];
  return (
    <form
      className="workflow-form create-form"
      onSubmit={async (e) => {
        e.preventDefault();
        if (pending || !selected) return;
        const values = new FormData(e.currentTarget);
        setPending(true);
        setError('');
        try {
          const item = await request<Item>('/items', {
            method: 'POST',
            body: {
              project,
              type: selected.key,
              title: values.get('title'),
              body: values.get('body') || null,
            },
          });
          location.assign('/' + item.key);
        } catch (err) {
          setError((err as Error).message);
          setPending(false);
        }
      }}
    >
      {!projects.length && (
        <p>
          No projects are available. Ask your workspace administrator to create
          a project.
        </p>
      )}
      <div className="workflow-field-grid">
      <label className="workflow-field">
        Project
        <select
          className="sx-control"
          value={project}
          onChange={(e) => {
            setProject(e.target.value);
            setType('');
          }}
          required
        >
          {projects
            .filter((p) => !p.archived_at)
            .map((p) => (
              <option key={p.key_prefix} value={p.key_prefix}>
                {p.name} ({p.key_prefix})
              </option>
            ))}
        </select>
      </label>
      {config.isPending ? (
        <p role="status">Loading project configuration…</p>
      ) : config.error ? (
        <p role="alert">{config.error.message}</p>
      ) : (
        <>
          <div className="workflow-field">
            <label htmlFor={typeID}>Type</label>
            <select
              id={typeID}
              aria-describedby={statusHintID}
              className="sx-control"
              value={selected?.key ?? ''}
              onChange={(e) => setType(e.target.value)}
            >
              {config.data?.types.map((t) => (
                <option key={t.key} value={t.key}>
                  {t.name}
                </option>
              ))}
            </select>
            <span id={statusHintID} className="field-hint">
              Initial status:{' '}
              {config.data?.statuses.find(
                (s) => s.key === selected?.initial_status,
              )?.name ?? selected?.initial_status}
            </span>
          </div>
        </>
      )}
      </div>
      <label className="workflow-field workflow-field-full">
        Title
        <input className="sx-control" name="title" required maxLength={500} />
      </label>
      <label className="workflow-field workflow-field-full">
        Description
        <textarea className="sx-control" name="body" placeholder="Write in Markdown" />
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="workflow-form-actions">
        <Button variant="default" disabled={pending || !selected}>
        {pending ? 'Creating…' : 'Create item'}
        </Button>
      </div>
    </form>
  );
}
