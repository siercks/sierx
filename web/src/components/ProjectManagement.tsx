import { useState } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { APIError, request, type Member, type Project } from '../api/client';
import { Button } from './ui/button';
import { Dialog } from './ui/dialog';

function MemberPicker({ workspace, value, onChange, enabled }: { workspace: string; value: string; onChange: (id: string) => void; enabled: boolean }) {
  const [search, setSearch] = useState('');
  const members = useInfiniteQuery({
    queryKey: [workspace, 'members', search],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => request<{ data: Member[]; next_cursor: string | null }>(`/members?${new URLSearchParams({ limit: '100', ...(search ? { q: search } : {}), ...(pageParam ? { cursor: pageParam } : {}) })}`, { signal }),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled,
  });
  const data = members.data?.pages.flatMap((page) => page.data) ?? [];
  return <div className="workflow-field">
    <label>Organizational owner (optional)</label>
    <p className="field-hint">This describes who is accountable for the project. Workspace permissions still control access.</p>
    <input className="sx-control" type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search active members" aria-label="Search active members" />
    <select className="sx-control" value={value} onChange={(event) => onChange(event.target.value)}>
      <option value="">No owner</option>
      {data.map((member) => <option key={member.id} value={member.id}>{member.display_name}</option>)}
    </select>
    {members.error && <p role="alert">{members.error.message}</p>}
    {members.hasNextPage && <Button variant="ghost" type="button" disabled={members.isFetchingNextPage} onClick={() => void members.fetchNextPage()}>{members.isFetchingNextPage ? 'Loading…' : 'Load more members'}</Button>}
  </div>;
}

function ProjectForm({ project, workspace, onSaved, enabled }: { project?: Project; workspace: string; onSaved: (project: Project) => void; enabled: boolean }) {
  const [name, setName] = useState(project?.name ?? '');
  const [prefix, setPrefix] = useState('');
  const [kind, setKind] = useState<Project['kind']>('delivery');
  const [owner, setOwner] = useState(project?.owner?.id ?? '');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const [conflict, setConflict] = useState<Project | null>(null);
  const [applyDraft, setApplyDraft] = useState(false);
  const create = !project;
  return <form className="workflow-form" onSubmit={async (event) => {
    event.preventDefault();
    if (pending) return;
    setPending(true); setError('');
    try {
      const saved = create
        ? await request<Project>('/projects', { method: 'POST', body: { name, key_prefix: prefix, kind, owner_id: owner || null } })
        : await request<Project>(`/projects/${project.key_prefix}`, { method: 'PATCH', version: conflict?.version ?? project.version, body: { name, owner_id: owner || null } });
      onSaved(saved);
    } catch (cause) {
      if (cause instanceof APIError && cause.problem.current_project) {
        setConflict(cause.problem.current_project);
        setApplyDraft(false);
        setError('This project changed while you were editing. Compare the latest values before applying your draft.');
        setPending(false);
        return;
      }
      setError((cause as Error).message);
      setPending(false);
    }
  }}>
    {create ? <>
      <label className="workflow-field">Project name<input className="sx-control" value={name} onChange={(event) => setName(event.target.value)} maxLength={200} required /></label>
      <label className="workflow-field">Key prefix<input className="sx-control" value={prefix} onChange={(event) => setPrefix(event.target.value.toUpperCase())} minLength={2} maxLength={10} pattern="[A-Z][A-Z0-9]{1,9}" required /><span className="field-hint">Uppercase letters and numbers, starting with a letter.</span></label>
      <label className="workflow-field">Project kind<select className="sx-control" value={kind} onChange={(event) => setKind(event.target.value as Project['kind'])}><option value="delivery">Delivery</option><option value="discovery">Discovery</option><option value="portfolio">Portfolio</option></select></label>
    </> : <>
      <label className="workflow-field">Project name<input className="sx-control" value={name} onChange={(event) => setName(event.target.value)} maxLength={200} required /></label>
      <p className="field-hint">Key prefix {project.key_prefix} · {project.kind}</p>
    </>}
    <MemberPicker workspace={workspace} value={owner} onChange={setOwner} enabled={enabled} />
    {conflict && <section className="alert alert-notice" aria-labelledby="project-conflict-heading">
      <h3 id="project-conflict-heading">Latest saved project</h3>
      <p>Name: {conflict.name} · owner: {conflict.owner?.display_name ?? 'none'} · version {conflict.version}</p>
      <label><input type="checkbox" checked={applyDraft} onChange={(event) => setApplyDraft(event.target.checked)} /> I compared these values and want to apply my draft on top of version {conflict.version}.</label>
    </section>}
    {error && <p className="alert alert-error" role="alert">{error}</p>}
    <div className="workflow-form-actions"><Button disabled={pending || (!!conflict && !applyDraft)}>{pending ? 'Saving…' : create ? 'Create project' : conflict ? 'Apply compared draft' : 'Save project'}</Button></div>
  </form>;
}

export function ProjectManagement({ project, workspace, onSaved, onDismiss }: { project?: Project; workspace: string; onSaved: (project: Project) => void; onDismiss: () => void }) {
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  function saved(value: Project) { setCreateOpen(false); setEditOpen(false); onSaved(value); }
  return <div className="project-management-actions">
    <Dialog trigger="Create project" title="Create project" open={createOpen} onOpenChange={setCreateOpen}><ProjectForm workspace={workspace} onSaved={saved} enabled={createOpen} /></Dialog>
    {project && <Dialog trigger="Edit project" title={`Edit ${project.name}`} open={editOpen} onOpenChange={setEditOpen}><ProjectForm key={`${project.id}:${project.version}`} project={project} workspace={workspace} onSaved={saved} enabled={editOpen} /></Dialog>}
    <Button variant="ghost" onClick={onDismiss}>Close project management</Button>
  </div>;
}
