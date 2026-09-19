import { useEffect, useState, type ReactNode } from 'react';
import { cache, request, bootstrap, type Me } from '../api/client';

import { startFeed } from '../api/feed';

export function Shell({
  me,
  authMode,
  children,
}: {
  me: Me;
  authMode: string;
  children: ReactNode;
}) {
  const [theme, setTheme] = useState(me.theme);
  const [motion, setMotion] = useState(
    me.reduced_motion === null
      ? 'system'
      : me.reduced_motion
        ? 'reduce'
        : 'full',
  );
  const [error, setError] = useState('');
  const [expired, setExpired] = useState(false);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    const handler = () => {
      setExpired(true);
      cache.cancelQueries();
    };
    const resumed = () => setExpired(false);
    window.addEventListener('sierx:expired', handler);
    window.addEventListener('sierx:resumed', resumed);
    return () => {
      window.removeEventListener('sierx:expired', handler);
      window.removeEventListener('sierx:resumed', resumed);
    };
  }, []);
  useEffect(
    () =>
      startFeed({
        sequence: String(
          bootstrap<{ change_seq: number | bigint }>().change_seq ?? 0,
        ),
        active: () => !expired && !document.hidden && document.hasFocus(),
        fetchPage: (seq) => request(`/changes?since_seq=${seq}&limit=200`),
        invalidate: () =>
          cache.invalidateQueries({ queryKey: [me.workspace_id] }),
      }),
    [me.workspace_id, expired],
  );
  async function resume() {
    try {
      await request('/me');
      setExpired(false);
      setError('');
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function preference(nextTheme: string, nextMotion: string) {
    setSaving(true);
    setError('');
    try {
      const saved = await request<Me>('/me', {
        method: 'PATCH',
        body: {
          theme: nextTheme,
          reduced_motion:
            nextMotion === 'system' ? null : nextMotion === 'reduce',
        },
      });
      setTheme(saved.theme);
      setMotion(nextMotion);
      document.documentElement.dataset.theme = saved.theme;
      document.documentElement.dataset.motion = nextMotion;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <header>
        <a href="/">Sierx</a>
        <div className="toolbar">
          <label>
            Theme
            <select
              value={theme}
              disabled={saving}
              onChange={(e) => void preference(e.target.value, motion)}
            >
              {['system', 'light', 'dark', 'light-hc', 'dark-hc'].map((v) => (
                <option key={v} value={v}>
                  {
                    {
                      system: 'System',
                      light: 'Light',
                      dark: 'Dark',
                      'light-hc': 'Light high contrast',
                      'dark-hc': 'Dark high contrast',
                    }[v]
                  }
                </option>
              ))}
            </select>
          </label>
          <label>
            Motion
            <select
              value={motion}
              disabled={saving}
              onChange={(e) => void preference(theme, e.target.value)}
            >
              <option value="system">Follow system</option>
              <option value="reduce">Reduce motion</option>
              <option value="full">Full motion</option>
            </select>
          </label>
          {authMode === 'local' && (
            <button
              onClick={async () => {
                try {
                  await request('/auth/logout', { method: 'POST' });
                  cache.clear();
                  location.assign('/login');
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              Sign out
            </button>
          )}
        </div>
      </header>
      <main id="main" tabIndex={-1}>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {expired && (
          <div className="notice" role="alert">
            Your session expired. Keep this page open to preserve your draft.{' '}
            <a href="/login" target="_blank" rel="noopener noreferrer">
              Sign in in a new tab
            </a>
            , then{' '}
            <button onClick={() => void resume()}>Continue this session</button>{' '}
            and retry your action.
          </div>
        )}
        {children}
      </main>
    </>
  );
}
