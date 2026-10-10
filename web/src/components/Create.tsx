import { useEffect, useId, useState } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { request, type Config, type Project, type Item } from '../api/client';
import { Dialog } from './ui/dialog';
import { Button } from './ui/button';
export function Create({
  projects,
  workspace,
  defaultProject = '',
  projectsNextCursor = null,
  selectedProject,
}: {
  projects: Project[];
  workspace: string;
  defaultProject?: string;
  projectsNextCursor?: string | null;
  selectedProject?: Project | null;
}) {
  return (
    <Dialog
      trigger="Create item"
      title="Create item"
      triggerVariant="default"
    >
      <CreateForm projects={projects} workspace={workspace} defaultProject={defaultProject} projectsNextCursor={projectsNextCursor} selectedProject={selectedProject} />
    </Dialog>
  );
}
function CreateForm({
  projects,
  workspace,
  defaultProject,
  projectsNextCursor,
  selectedProject,
}: {
  projects: Project[];
  workspace: string;
  defaultProject: string;
  projectsNextCursor: string | null;
  selectedProject?: Project | null;
}) {
  const typeID = useId();
  const statusHintID = useId();
  const projectID = useId();
  const [projectSearch, setProjectSearch] = useState('');
  const [type, setType] = useState('');
  const projectPages = useInfiniteQuery({
    queryKey: [workspace, 'projects', projectSearch],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => request<{ data: Project[]; next_cursor: string | null }>(`/projects?${new URLSearchParams({ limit: '100', ...(projectSearch ? { search: projectSearch } : {}), ...(pageParam ? { cursor: pageParam } : {}) })}`, { signal }),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    initialData: projectSearch ? undefined : { pages: [{ data: projects, next_cursor: projectsNextCursor }], pageParams: [null] },
    enabled: !!projects.length || !!projectSearch,
  });
  const availableProjects = [...new Map([...(projectPages.data?.pages.flatMap((page) => page.data) ?? projects), ...(selectedProject ? [selectedProject] : [])].filter((item) => !item.archived_at).map((item) => [item.key_prefix, item])).values()];
  const activeProjects = availableProjects;
  const [project, setProject] = useState(
    defaultProject || (activeProjects.length === 1 ? activeProjects[0].key_prefix : ''),
  );
  useEffect(() => {
    setProject(defaultProject || (activeProjects.length === 1 ? activeProjects[0].key_prefix : ''));
    setType('');
  }, [defaultProject]);
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
      <div className="workflow-field">
        <label htmlFor={projectID}>Project</label>
        {(projects.length > 10 || projectsNextCursor !== null || !!projectSearch) && <input className="sx-control" type="search" value={projectSearch} onChange={(e) => setProjectSearch(e.target.value)} placeholder="Search projects" aria-label="Search projects" />}
        <select
          id={projectID}
          className="sx-control"
          value={project}
          onChange={(e) => {
            setProject(e.target.value);
            setType('');
          }}
          required
        >
          {project === '' && <option value="">Choose a project</option>}
          {activeProjects.map((p) => (
              <option key={p.key_prefix} value={p.key_prefix}>
                {p.name} ({p.key_prefix})
              </option>
            ))}
        </select>
        {projectPages.hasNextPage && <Button variant="ghost" type="button" disabled={projectPages.isFetchingNextPage} onClick={() => void projectPages.fetchNextPage()}>{projectPages.isFetchingNextPage ? 'Loading projects…' : 'Load more projects'}</Button>}
      </div>
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
