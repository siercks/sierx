import { useState } from 'react';
import { bootstrap, request } from '../api/client';
export default function Login() {
  const state = bootstrap<{ auth_mode: string }>();
  const [error, setError] = useState(''),
    [pending, setPending] = useState(false);
  return (
    <main className="login">
      <h1>Sign in to Sierx</h1>
      <p className="muted">A clear place for your work.</p>
      {state.auth_mode === 'proxy' ? (
        <p>
          Your organization manages sign-in. Open Sierx through your configured
          identity proxy.
        </p>
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
          <label>
            Email
            <input
              name="email"
              type="email"
              autoComplete="username"
              required
              autoFocus
            />
          </label>
          <label>
            Password
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
            />
          </label>
          <label>
            Authenticator or recovery code
            <input
              name="code"
              autoComplete="one-time-code"
              aria-describedby="code-help"
            />
          </label>
          <small id="code-help">
            Enter a code if two-factor authentication is enabled for your
            account.
          </small>
          {error && (
            <p className="error" role="alert">
              {error} Check your email, password and code, then try again.
            </p>
          )}
          <button className="primary" disabled={pending}>
            {pending ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      )}
    </main>
  );
}
