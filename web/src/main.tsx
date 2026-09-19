import React, { Suspense } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { cache } from './api/client';
import { routes } from './routes/table';
import List from './routes/List';
import './themes/app.css';
const Login = React.lazy(() => import('./routes/Login'));
const Item = React.lazy(() => import('./routes/Item'));
const path = location.pathname;
const Route =
  path === routes[0].path ? List : path === routes[1].path ? Login : Item;
class Boundary extends React.Component<
  { children: React.ReactNode },
  { error: string }
> {
  state = { error: '' };
  static getDerivedStateFromError(e: Error) {
    return { error: e.message };
  }
  render() {
    return this.state.error ? (
      <main>
        <h1>Sierx could not load</h1>
        <p role="alert">{this.state.error}</p>
        <a href={location.href}>Reload page</a>
      </main>
    ) : (
      this.props.children
    );
  }
}
createRoot(document.getElementById('root')!).render(
  <Boundary>
    <QueryClientProvider client={cache}>
      <Suspense fallback={<p role="status">Loading Sierx…</p>}>
        <Route />
      </Suspense>
    </QueryClientProvider>
  </Boundary>,
);
