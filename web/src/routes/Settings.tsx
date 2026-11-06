import { useState } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { APIError, bootstrap, cache, request, type Config, type Me, type Page, type Project, type Workspace } from '../api/client';
import { Shell } from '../components/Shell';
import { Button } from '../components/ui/button';

type State = { me: Me; auth_mode: string; workspace: Workspace; projects: Page<Project> };
type Status = Config['statuses'][number];
const categories = [['open', 'Not started'], ['active', 'In progress'], ['done', 'Completed'], ['cancelled', 'Cancelled']];
const suggestions: Status[] = [
  { key: 'unassigned', name: 'Unassigned', category: 'open' },
  { key: 'planned', name: 'Planned', category: 'open' },
  { key: 'on_hold', name: 'On Hold', category: 'active' },
  { key: 'blocked', name: 'Blocked', category: 'active' },
  { key: 'completed', name: 'Completed', category: 'done' },
];

function WorkspaceForm({ initial }: { initial: Workspace }) {
  const [current, setCurrent] = useState(initial);
  const [name, setName] = useState(initial.name);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [pending, setPending] = useState(false);
  const [conflict, setConflict] = useState<Workspace | null>(null);
  return <section className="card">
    <h2>Workspace details</h2>
    <p className="muted">Workspace identifier: {initial.slug}</p>
    <form className="workflow-form" onSubmit={async (event) => {
      event.preventDefault(); if (pending || conflict) return;
      setPending(true); setError(''); setSuccess('');
      try { const saved = await request<Workspace>('/workspace', { method: 'PATCH', version: current.version, body: { name } }); setCurrent(saved); setName(saved.name); setSuccess('Workspace details saved.'); }
      catch (cause) { setError((cause as Error).message); if (cause instanceof APIError && cause.problem.current_workspace) setConflict(cause.problem.current_workspace); }
      finally { setPending(false); }
    }}>
      <label>Workspace name<input className="sx-control" value={name} maxLength={200} required disabled={pending} onChange={(event) => setName(event.target.value)} /></label>
      {conflict && <section className="alert alert-notice"><p>Latest saved name: {conflict.name}. Your draft is still in the field above.</p><Button type="button" onClick={() => { setCurrent(conflict); setName(conflict.name); setConflict(null); setError(''); }}>Replace draft with latest workspace details</Button></section>}
      {error && <p role="alert">{error}</p>}
      {success && <p role="status">{success}</p>}
      <Button disabled={pending || !!conflict}>{pending ? 'Saving…' : 'Save workspace'}</Button>
    </form>
  </section>;
}

function WorkflowEditor({ config, project, onSaved }: { config: Config; project: string; onSaved: (saved: Config) => void }) {
  const [statuses, setStatuses] = useState(config.statuses);
  const [transitions, setTransitions] = useState(config.transitions);
  const [initial, setInitial] = useState(Object.fromEntries(config.types.map((type) => [type.key, type.initial_status])));
  const [from, setFrom] = useState(config.statuses[0]?.key ?? '');
  const [name, setName] = useState('');
  const [key, setKey] = useState('');
  const [category, setCategory] = useState('open');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const [conflict, setConflict] = useState<Config | null>(null);
  const [review, setReview] = useState(false);
  const names = new Map(statuses.map((status) => [status.key, status.name]));
  const required = ['assignee', 'points', 'start_date', 'due_date', ...config.fields.map((field) => 'fields.' + field.key)];
  function move(index: number, direction: number) {
    const next = [...statuses]; [next[index], next[index + direction]] = [next[index + direction], next[index]]; setStatuses(next); setReview(false);
  }
  function addStatus() {
    if (!name.trim() || !/^[a-z][a-z0-9_-]{0,39}$/.test(key) || statuses.some((status) => status.key === key || status.name.toLowerCase() === name.trim().toLowerCase()) || statuses.length >= 50) { setError('Enter a unique name and lowercase status key. A workflow supports up to 50 statuses.'); return; }
    setStatuses([...statuses, { key, name: name.trim(), category }]); setName(''); setKey(''); setError(''); setReview(false);
  }
  return <form className="workflow-form" onSubmit={async (event) => {
    event.preventDefault(); if (pending || conflict || !review) return;
    setPending(true); setError('');
    try { onSaved(await request<Config>(`/projects/${project}/config`, { method: 'PUT', version: config.version, body: { statuses, transitions, initial_statuses: initial } })); }
    catch (cause) { setError((cause as Error).message); if (cause instanceof APIError && cause.problem.current_config) setConflict(cause.problem.current_config); }
    finally { setPending(false); }
  }}>
    <fieldset disabled={pending} className="workflow-fields">
      <legend>Item workflow</legend>
      <p>These statuses describe items in {project}. Saving publishes a new workflow version. Existing item status and history are preserved; future transitions use the saved flow.</p>
      <h3>Statuses and display order</h3>
      <ol className="workflow-flow">
        {statuses.map((status, index) => <li className="card" key={status.key}>
          <strong>{status.name}</strong> <span className="muted">({status.category})</span>
          <p>→ {(transitions[status.key] ?? []).map((arc) => names.get(arc.to_key)).join(', ') || 'No outgoing transitions'}</p>
          <div className="toolbar">
            <Button type="button" size="sm" disabled={index === 0} onClick={() => move(index, -1)} aria-label={`Move ${status.name} earlier`}>Move earlier</Button>
            <Button type="button" size="sm" disabled={index === statuses.length - 1} onClick={() => move(index, 1)} aria-label={`Move ${status.name} later`}>Move later</Button>
            <Button type="button" size="sm" aria-pressed={from === status.key} onClick={() => setFrom(status.key)} aria-label={`Edit transitions from ${status.name}`}>Edit transitions</Button>
          </div>
        </li>)}
      </ol>
      <p className="field-hint">Existing status definitions are retained for history. Add a new status when you need a different name or category.</p>
      <div className="workflow-field-grid">
        <label>Status name<input className="sx-control" value={name} maxLength={80} onChange={(event) => { setName(event.target.value); setKey(event.target.value.toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').slice(0, 40)); }} /></label>
        <label>Status key<input className="sx-control" value={key} maxLength={40} onChange={(event) => setKey(event.target.value)} /></label>
        <label>Status category<select className="sx-control" value={category} onChange={(event) => setCategory(event.target.value)}>{categories.map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></label>
      </div>
      <div className="toolbar">
        <Button type="button" onClick={addStatus}>Add status</Button>
        <Button type="button" disabled={statuses.length >= 50} onClick={() => { setStatuses([...statuses, ...suggestions.filter((status) => !statuses.some((existing) => existing.key === status.key || existing.name.toLowerCase() === status.name.toLowerCase())).slice(0, 50 - statuses.length)]); setReview(false); }}>Add suggested statuses</Button>
      </div>
      <p className="field-hint">Suggested additions: Unassigned, Planned, On Hold, Blocked and Completed. To Do and In Progress already exist. Assignment is separate: an Unassigned status does not clear the assignee. Choose incoming and outgoing transitions below before saving.</p>
      <h3>Allowed transitions</h3>
      <label>From status<select className="sx-control" value={from} onChange={(event) => setFrom(event.target.value)}>{statuses.map((status) => <option key={status.key} value={status.key}>{status.name}</option>)}</select></label>
      {statuses.filter((status) => status.key !== from).map((status) => {
        const arc = transitions[from]?.find((entry) => entry.to_key === status.key);
        return <div key={status.key} className="card">
          <label className="check-label"><input type="checkbox" checked={!!arc} onChange={(event) => { const next = (transitions[from] ?? []).filter((entry) => entry.to_key !== status.key); setTransitions({ ...transitions, [from]: event.target.checked ? [...next, { to_key: status.key, requires: [] }] : next }); setReview(false); }} /> Allow {names.get(from)} → {status.name}</label>
          {arc && <details><summary>Required fields before moving to {status.name}</summary>{[...new Set([...required, ...arc.requires])].map((field) => <label className="check-label" key={field}><input type="checkbox" checked={arc.requires.includes(field)} onChange={(event) => { setTransitions({ ...transitions, [from]: transitions[from].map((entry) => entry.to_key === status.key ? { ...entry, requires: event.target.checked ? [...entry.requires, field] : entry.requires.filter((value) => value !== field) } : entry) }); setReview(false); }} /> {field.replace('fields.', '').replaceAll('_', ' ')}</label>)}</details>}
        </div>;
      })}
      <h3>Initial status for new items</h3>
      {config.types.map((type) => <label key={type.key}>{type.name} initial status<select className="sx-control" value={initial[type.key]} onChange={(event) => { setInitial({ ...initial, [type.key]: event.target.value }); setReview(false); }}>{statuses.map((status) => <option key={status.key} value={status.key}>{status.name}</option>)}</select></label>)}
      <label className="check-label"><input type="checkbox" checked={review} onChange={(event) => setReview(event.target.checked)} /> I reviewed this flow and its required fields for {project}.</label>
    </fieldset>
    {conflict && <section className="alert alert-notice"><p>Latest saved version: {conflict.version}. Your draft is preserved above.</p><Button type="button" onClick={() => onSaved(conflict)}>Replace draft with latest workflow</Button></section>}
    {error && <p role="alert">{error}</p>}
    <Button disabled={pending || !!conflict || !review}>{pending ? 'Saving…' : 'Save workflow'}</Button>
  </form>;
}

export default function Settings() {
  const state = useState(() => bootstrap<State>())[0];
  const [project, setProject] = useState('');
  const [search, setSearch] = useState('');
  const [saved, setSaved] = useState('');
  const [loaded, setLoaded] = useState<Config | null>(null);
  const projects = useInfiniteQuery({
    queryKey: [state.me.workspace_id, 'settings-projects', search], initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => request<Page<Project>>(`/projects?${new URLSearchParams({ limit: '100', ...(search ? { search } : {}), ...(pageParam ? { cursor: pageParam } : {}) })}`, { signal }),
    initialData: search ? undefined : { pages: [state.projects], pageParams: [null] }, getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  const config = useQuery({ queryKey: [state.me.workspace_id, 'config', project], queryFn: ({ signal }) => request<Config>(`/projects/${project}/config`, { signal }), enabled: !!project });
  const active = loaded ?? config.data;
  return <Shell me={state.me} authMode={state.auth_mode}>
    <h1>Workspace settings</h1>
    <WorkspaceForm initial={state.workspace} />
    <section className="card">
      <h2>Project item workflows</h2>
      <label>Find a project<input type="search" className="sx-control" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
      <label>Workflow project<select className="sx-control" value={project} onChange={(event) => { setProject(event.target.value); setLoaded(null); setSaved(''); }}><option value="">Choose a project</option>{[...new Map((projects.data?.pages.flatMap((page) => page.data) ?? []).map((entry) => [entry.key_prefix, entry])).values()].map((entry) => <option key={entry.id} value={entry.key_prefix}>{entry.name} ({entry.key_prefix})</option>)}</select></label>
      {projects.hasNextPage && <Button type="button" disabled={projects.isFetchingNextPage} onClick={() => void projects.fetchNextPage()}>Load more projects</Button>}
      {projects.error && <p role="alert">{projects.error.message}</p>}
      {project && config.isPending && <p role="status">Loading workflow…</p>}
      {config.error && <p role="alert">{config.error.message}</p>}
      {saved && <p role="status">{saved}</p>}
      {project && active && <WorkflowEditor key={`${project}:${active.version}`} config={active} project={project} onSaved={(next) => { cache.setQueryData([state.me.workspace_id, 'config', project], next); setLoaded(next); setSaved(`Workflow version ${next.version} loaded.`); }} />}
    </section>
  </Shell>;
}
