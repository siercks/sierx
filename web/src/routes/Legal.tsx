import { useEffect } from 'react';
import { bootstrap } from '../api/client';

type Notice = Record<string, string>;
type Package = { name: string; version: string; license: string; purpose: string };
type Inventory = {
  runtime: Package[];
  build_tools: Package[];
  fonts: { bundled: { family: string; license: string; delivery: string; files: string[] }[]; third_party: { family: string; license: string; delivery: string; files: string[] }[]; device_fallbacks: string };
  operator_services: string;
  operator?: string;
};
type State = { route: 'privacy' | 'copyright' | 'third-party'; configured?: boolean; notice?: Notice; inventory?: Inventory };

function Footer() {
  return <footer className="legal-footer"><a href="/privacy">Privacy</a><a href="/copyright">Copyright</a><a href="/third-party">Third-party notices</a><a href="/login">Sign in</a></footer>;
}

function Setup({ children }: { children: React.ReactNode }) {
  return <section className="legal-setup"><h2>Instance operator setup required</h2><p>This page is not a completed instance notice. The operator must add accurate contact, retention, backup, and service details before providing this instance to others.</p>{children}</section>;
}

function Privacy({ notice, configured }: { notice: Notice; configured: boolean }) {
  return <>
    <h1>Privacy</h1>
    {configured ? <p>Operated by <strong>{notice.operator}</strong>. Notice version {notice.version}, effective {notice.effective_date}.</p> : <Setup><p>Set the instance notice values in the server environment. This page does not make unverified retention or provider promises.</p></Setup>}
    <h2>Information handled by Sierx</h2>
    <ul>
      <li>Account and profile information, including the identity used to sign in.</li>
      <li>Authentication records: password hashes for local sign-in, optional encrypted multi-factor configuration, and session records.</li>
      <li>Workspace content: item titles and descriptions, comments, links, workflow data, and event history.</li>
      <li>Preferences such as appearance and motion settings.</li>
      <li>Structured operational logs identify the actor and workspace for requests. Login rate limiting temporarily uses the connecting address in process memory.</li>
    </ul>
    <h2>Retention and backups</h2>
    {notice.retention ? <p>{notice.retention}</p> : <p>The operator has not configured this instance’s record-retention practices.</p>}
    {notice.backups ? <p>{notice.backups}</p> : <p>The operator has not configured backup retention and expiry details.</p>}
    <h2>Services used by this instance</h2>
    {notice.services ? <p>{notice.services}</p> : <p>The operator has not described this instance’s proxy, gateway, certificate, or other service providers.</p>}
    <h2>Contact</h2>
    {notice.contact ? <p>For privacy questions or requests, contact {notice.contact}.</p> : <p>The instance operator has not configured a privacy contact.</p>}
    <p>Requests about account access, correction, deactivation, or content handling must be reviewed by the instance operator. A soft-deleted item may remain in history, comments, links, or backups.</p>
  </>;
}

function Copyright({ notice, configured }: { notice: Notice; configured: boolean }) {
  return <>
    <h1>Copyright</h1>
    {configured ? <p>Operated by {notice.operator}.</p> : <Setup><p>Do not treat this software page as a registered agent designation. The instance operator must supply accurate agent and process details.</p></Setup>}
    <h2>Designated contact</h2><p>{notice.agent || 'No agent information has been configured.'}</p><p>{notice.contact || 'No copyright contact has been configured.'}</p>
    <h2>Submit a notice</h2><p>{notice.notice_process || 'The operator has not configured a notice procedure.'}</p>
    <h2>Counter-notice and restoration</h2><p>{notice.counter_notice_process || 'The operator has not configured a counter-notice procedure.'}</p>
    <h2>Repeat-infringer handling</h2><p>{notice.repeat_infringer_policy || 'The operator has not configured a repeat-infringer policy.'}</p>
  </>;
}

function ThirdParty({ inventory }: { inventory: Inventory }) {
  const rows = (entries: Package[]) => <div className="legal-table-wrap"><table><thead><tr><th scope="col">Component</th><th scope="col">Version</th><th scope="col">License</th><th scope="col">Use</th></tr></thead><tbody>{entries.map((entry) => <tr key={`${entry.name}@${entry.version}`}><td>{entry.name}</td><td>{entry.version}</td><td>{entry.license}</td><td>{entry.purpose}</td></tr>)}</tbody></table></div>;
  return <>
    <h1>Third-party notices</h1>
    {inventory.operator && <p>Instance operator: {inventory.operator}</p>}
    <p>This inventory is generated from the exact package lock, license inventory, and local font manifest used by the build.</p>
    <h2>Bundled runtime libraries</h2>{rows(inventory.runtime)}
    <h2>Build and validation tools</h2>{rows(inventory.build_tools)}
    <h2>Fonts</h2>
    {inventory.fonts.bundled.length ? <ul>{inventory.fonts.bundled.map((font) => <li key={font.family}>{font.family} — {font.license}; {font.delivery}.</li>)}</ul> : <p>No locally built fonts are listed.</p>}
    {inventory.fonts.third_party.length ? <ul>{inventory.fonts.third_party.map((font) => <li key={font.family}>{font.family} — {font.license}; {font.delivery}.</li>)}</ul> : <p>No third-party font files are bundled.</p>}
    <p>{inventory.fonts.device_fallbacks}</p>
    <h2>Operator-selected services</h2><p>{inventory.operator_services}</p>
  </>;
}

export default function Legal() {
  const state = bootstrap<State>();
  const title = state.route === 'third-party' ? 'Third-party notices' : state.route === 'copyright' ? 'Copyright' : 'Privacy';
  useEffect(() => { document.title = `${title} · Sierx`; }, [title]);
  return <div className="sx-app legal-app"><a className="skip" href="#main">Skip to content</a><header className="legal-header"><a className="brand" href="/">Sierx</a><Footer /></header><main id="main" className="sx-main legal-main" tabIndex={-1}>
    {state.route === 'privacy' && <Privacy notice={state.notice ?? {}} configured={!!state.configured} />}
    {state.route === 'copyright' && <Copyright notice={state.notice ?? {}} configured={!!state.configured} />}
    {state.route === 'third-party' && state.inventory && <ThirdParty inventory={state.inventory} />}
  </main><div className="legal-bottom"><Footer /></div></div>;
}
