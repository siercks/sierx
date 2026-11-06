import { useRef, useState } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { APIError, bootstrap, cache, request, type Me, type Page } from '../api/client';
import { Shell } from '../components/Shell';
import { Button } from '../components/ui/button';

type Member = { id: string; display_name: string; email: string; role: string; is_active: boolean };
type State = { me: Me; auth_mode: string; members: Page<Member> };
type Credential = { name: string; email: string; password: string; created: boolean; uncertain: boolean };

function generatePassword() {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...bytes)).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '');
}

export default function Admin() {
  const [state] = useState(() => bootstrap<State>());
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [search, setSearch] = useState('');
  const [pending, setPending] = useState(false);
  const inFlight = useRef(false);
  const [credential, setCredential] = useState<Credential | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const members = useInfiniteQuery({
    queryKey: [state.me.workspace_id, 'admin-members', search], initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => request<Page<Member>>(`/admin/members?${new URLSearchParams({ limit: '100', ...(search ? { q: search } : {}), ...(pageParam ? { cursor: pageParam } : {}) })}`, { signal }),
    initialData: search ? undefined : { pages: [state.members], pageParams: [null] },
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  async function addMember(details: Credential) {
    if (inFlight.current) return;
    inFlight.current = true;
    setCredential(details); setPending(true); setError(''); setNotice('');
    try {
      await request<Member>('/admin/members', { method: 'POST', body: { display_name: details.name, email: details.email, initial_password: details.password } });
      setCredential({ ...details, created: true });
      setNotice(`${details.name} was added as a Member.`);
      void cache.invalidateQueries({ queryKey: [state.me.workspace_id, 'admin-members'] });
      void cache.invalidateQueries({ queryKey: [state.me.workspace_id, 'members'] });
    } catch (cause) {
      if (cause instanceof APIError && cause.problem.status < 500 && !details.uncertain) {
        setCredential(null);
        setError(cause.message);
      } else {
        setCredential({ ...details, uncertain: true });
        setError((cause as Error).message + ' Check the member list before retrying: the request may have completed. Keep the login details below until you confirm the result.');
      }
      void cache.invalidateQueries({ queryKey: [state.me.workspace_id, 'admin-members'] });
    } finally { inFlight.current = false; setPending(false); }
  }
  return <Shell me={state.me} authMode={state.auth_mode}>
    <h1>Administrator Home</h1>
    <p>Manage access to this workspace and open its settings.</p>
    <p><a href="/settings">Workspace settings and item workflows</a></p>
    <section className="card admin-section" aria-labelledby="add-member-heading">
      <h2 id="add-member-heading">Add Member</h2>
      <p>New members can work on items and be assigned work. They do not receive administrator access.</p>
      {state.auth_mode === 'local' ? <>
        <form className="workflow-form" onSubmit={(event) => {
          event.preventDefault();
          if (inFlight.current || credential) return;
          void addMember({ name: name.trim(), email: email.trim().toLowerCase(), password: generatePassword(), created: false, uncertain: false });
        }}>
          <fieldset className="workflow-fields" disabled={pending || !!credential}>
            <legend>Member details</legend>
            <label>Display name<input className="sx-control" value={name} maxLength={200} required autoComplete="off" onChange={(event) => setName(event.target.value)} /></label>
            <label>Email address<input className="sx-control" type="email" value={email} maxLength={320} required autoComplete="off" onChange={(event) => setEmail(event.target.value)} /></label>
            <Button>{pending ? 'Adding member…' : 'Add Member'}</Button>
          </fieldset>
        </form>
        {credential && <section className="alert alert-notice member-credentials" aria-labelledby="member-login-heading">
          <h3 id="member-login-heading">Member login details</h3>
          {!credential.created && <p>{pending ? 'Adding the member. Wait for confirmation before sharing these details.' : 'Member creation is not confirmed. Check the member list before sharing these details.'}</p>}
          <p>{credential.email}</p>
          <p>Save these details privately before closing this section. This password is available here for this setup only. Share it directly with the member.</p>
          <label>Initial password<input className="sx-control" type={revealed ? 'text' : 'password'} value={credential.password} readOnly autoComplete="off" spellCheck={false} /></label>
          <div className="toolbar">
            <Button type="button" variant="outline" aria-pressed={revealed} onClick={() => setRevealed(!revealed)}>{revealed ? 'Hide password' : 'Show password'}</Button>
            <Button type="button" variant="outline" onClick={async () => {
              try { await navigator.clipboard.writeText(credential.password); setNotice('Password copied. Save it privately.'); }
              catch { setNotice('Select the password field and copy it manually.'); setRevealed(true); }
            }}>Copy password</Button>
            {!credential.created && !pending && <Button type="button" variant="outline" onClick={() => void addMember(credential)}>Retry adding member</Button>}
            <Button type="button" disabled={pending} onClick={() => { setCredential(null); setRevealed(false); setName(''); setEmail(''); setError(''); setNotice('Login details closed.'); }}>I saved the login details</Button>
          </div>
        </section>}
      </> : <p>Proxy sign-in accounts require operator provisioning. Local member passwords cannot be created in this mode.</p>}
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
    </section>
    <section className="card admin-section" aria-labelledby="workspace-members-heading">
      <h2 id="workspace-members-heading">Workspace members</h2>
      <label>Find a member<input className="sx-control" type="search" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
      {members.error && <p role="alert">{members.error.message}</p>}
      {members.isPending && <p role="status">Loading members…</p>}
      <ul className="admin-member-list">{members.data?.pages.flatMap((page) => page.data).map((member) => <li key={member.id}>
        <strong>{member.display_name}</strong><span>{member.email}</span>
        <span>Role: {member.role === 'admin' ? 'Administrator' : 'Member'}</span><span>{member.is_active ? 'Active' : 'Inactive'}</span>
      </li>)}</ul>
      {members.data?.pages.every((page) => page.data.length === 0) && <p>No members match this search.</p>}
      {members.hasNextPage && <Button type="button" disabled={members.isFetchingNextPage} onClick={() => void members.fetchNextPage()}>Load more members</Button>}
    </section>
  </Shell>;
}
