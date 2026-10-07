import { useEffect, useState, type ReactNode } from 'react';
import { cache, request, bootstrap, type Me } from '../api/client';

import { startFeed } from '../api/feed';
import { Button } from './ui/button';

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
    <div className="app-shell">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <header className="app-header">
        <div className="brand-group">
          <a className="brand" href="/" aria-label="Sierx home">
            <span className="brand-mark" aria-hidden="true">
              S
            </span>
            <span>Sierx</span>
          </a>
          <span className="header-divider" aria-hidden="true" />
          <a className="workspace-link" href="/">
            Workspace
          </a>
        </div>
        <div className="header-tools">
          <label className="preference-field">
            <span>Theme</span>
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
          <label className="preference-field">
            <span>Motion</span>
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
          <div className="user-menu">
            <span className="user-avatar" aria-hidden="true">
              {me.display_name.slice(0, 1).toUpperCase()}
            </span>
            <span className="user-name">{me.display_name}</span>
            {authMode === 'local' && (
              <Button
                variant="ghost"
                size="sm"
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
              </Button>
            )}
          </div>
        </div>
      </header>
      <main id="main" className="app-main" tabIndex={-1}>
        {error && (
          <p className="alert alert-error" role="alert">
            {error}
          </p>
        )}
        {expired && (
          <div className="alert alert-notice" role="alert">
            Your session expired. Keep this page open to preserve your draft.{' '}
            <a href="/login" target="_blank" rel="noopener noreferrer">
              Sign in in a new tab
            </a>
            , then{' '}
            <Button
              variant="outline"
              size="sm"
              onClick={() => void resume()}
            >
                Continue this session
            </Button>{' '}
            and retry your action.
          </div>
        )}
        {children}
      </main>
    </div>
  );
}
