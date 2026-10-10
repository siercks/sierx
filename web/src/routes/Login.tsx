import { useState } from 'react';
import { bootstrap, request } from '../api/client';
import { Button } from '../components/ui/button';
export default function Login() {
  const state = bootstrap<{ auth_mode: string }>();
  const [error, setError] = useState(''),
    [pending, setPending] = useState(false);
  return (
    <div className="sx-app sx-auth-app">
    <main className="sx-main auth-page">
      <section className="sx-card sx-surface auth-card" aria-labelledby="login-heading">
        <a className="brand auth-brand" href="/" aria-label="Sierx home">
          <span className="brand-mark" aria-hidden="true">S</span>
          <span>Sierx</span>
        </a>
        <div className="auth-heading">
          <p className="eyebrow">Your workspace</p>
          <h1 id="login-heading" className="sx-main-title">Welcome back</h1>
          <p className="page-description">Sign in to continue to your work.</p>
        </div>
      {state.auth_mode === 'proxy' ? (
        <div className="alert alert-notice">
          Your organization manages sign-in. Open Sierx through your configured
          identity proxy.
        </div>
      ) : (
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            if (pending) return;
            const values = new FormData(e.currentTarget);
            setPending(true);
            setError('');
            try {
              await request('/auth/login', {
                method: 'POST',
                body: Object.fromEntries(values),
              });
              location.assign('/');
            } catch (err) {
              setError((err as Error).message);
              setPending(false);
            }
          }}
        >
          <label className="sx-field form-field">
            Email
            <input
              name="email"
              type="email"
              className="sx-control"
              autoComplete="username"
              required
              autoFocus
            />
          </label>
          <label className="sx-field form-field">
            Password
            <input
              name="password"
              type="password"
              className="sx-control"
              autoComplete="current-password"
              required
            />
          </label>
          <label className="sx-field form-field">
            Authenticator or recovery code
            <input
              name="code"
              className="sx-control"
              autoComplete="one-time-code"
              aria-describedby="code-help"
            />
          </label>
          <small id="code-help" className="field-hint">
            Leave this blank unless two-factor authentication is enabled for
            your account. Codes are ignored until enrollment is complete.
          </small>
          {error && (
            <p className="error" role="alert">
              {error} Check your email, password and code, then try again.
            </p>
          )}
          <Button variant="default" className="auth-submit" disabled={pending}>
            {pending ? 'Signing in…' : 'Sign in'}
          </Button>
        </form>
      )}
        <p className="auth-footnote">A clear place for your work.</p>
        <footer className="legal-footer">
          <a href="/privacy">Privacy</a>
          <a href="/copyright">Copyright</a>
          <a href="/third-party">Third-party notices</a>
        </footer>
      </section>
    </main>
    </div>
  );
}
