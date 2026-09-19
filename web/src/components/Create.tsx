import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { request, type Config, type Project, type Item } from '../api/client';
import { Dialog } from './ui/dialog';
export function Create({
  projects,
  workspace,
}: {
  projects: Project[];
  workspace: string;
}) {
  return (
    <Dialog trigger="Create item" title="Create item">
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
      <label>
        Project
        <select
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
          <label>
            Type
            <select
              value={selected?.key ?? ''}
              onChange={(e) => setType(e.target.value)}
            >
              {config.data?.types.map((t) => (
                <option key={t.key} value={t.key}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>
          <p className="muted">
            Initial status:{' '}
            {config.data?.statuses.find(
              (s) => s.key === selected?.initial_status,
            )?.name ?? selected?.initial_status}
          </p>
        </>
      )}
      <label>
        Title
        <input name="title" required maxLength={500} />
      </label>
      <label>
        Description
        <textarea name="body" placeholder="Write in Markdown" />
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button className="primary" disabled={pending || !selected}>
        {pending ? 'Creating…' : 'Create item'}
      </button>
    </form>
  );
}
