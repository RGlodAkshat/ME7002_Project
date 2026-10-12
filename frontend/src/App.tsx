import { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import { api, setCsrf } from './api';
import { AdminPage } from './AdminPage';
import { OperatorPage } from './OperatorPage';
import { Button, Icon, Loading } from './components';
import type { Session } from './types';

const route = () => window.location.hash.replace(/^#\/?/, '') || 'login';
const ShopPage = lazy(() => import('./ShopPage').then(module => ({ default: module.ShopPage })));
export default function App() {
  const [view, setView] = useState(route);
  const [session, setSession] = useState<Session | null>(null);
  const [setup, setSetup] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const [toasts, setToasts] = useState<{ id: number; message: string; kind: string }[]>([]);
  const navigate = useCallback((next: string) => { window.location.hash = `/${next}`; setView(next); }, []);
  const notify = useCallback((message: string, kind: 'success' | 'error' = 'success') => {
    const id = Date.now() + Math.random();
    setToasts(current => [...current, { id, message, kind }]);
    window.setTimeout(() => setToasts(current => current.filter(item => item.id !== id)), 6000);
  }, []);
  const bootstrap = useCallback(async () => {
    setError('');
    try {
      const status = await api.authStatus(); setSetup(status.needs_setup);
      try { const value = await api.me(); setCsrf(value.csrf_token); setSession(value); } catch { setSession(null); setCsrf(''); }
      setReady(true);
    } catch (err) { setError((err as Error).message); }
  }, []);
  useEffect(() => { void bootstrap(); const onHash = () => setView(route()); window.addEventListener('hashchange', onHash); return () => window.removeEventListener('hashchange', onHash); }, [bootstrap]);
  useEffect(() => {
    if (!ready || view === 'shop') return;
    if (!session) { if (view !== 'login') navigate('login'); return; }
    if (view !== session.user.role) navigate(session.user.role);
  }, [view, session, ready, navigate]);
  const authenticated = (value: Session) => { setSession(value); setCsrf(value.csrf_token); setSetup(false); navigate(value.user.role); };
  const logout = async () => { try { await api.logout(); setSession(null); setCsrf(''); navigate('login'); } catch (err) { notify((err as Error).message, 'error'); } };
  return <>
    {!ready ? <div className="startup"><Brand/>{error ? <div className="error-panel" role="alert"><p>{error}</p><Button onClick={bootstrap}>Try again</Button></div> : <Loading/>}</div> : view === 'shop' ? <Suspense fallback={<Loading/>}><ShopPage notify={notify}/></Suspense> : session && view === 'admin' && session.user.role === 'admin' ? <AdminPage user={session.user} logout={logout} notify={notify}/> : session && view === 'operator' && session.user.role === 'operator' ? <OperatorPage user={session.user} logout={logout} notify={notify}/> : <Login setup={setup} authenticated={authenticated}/>}
    <div className="toast-stack" aria-live="polite">{toasts.map(toast => <div className={`toast toast--${toast.kind}`} key={toast.id}><Icon name={toast.kind === 'success' ? 'check' : 'alert'}/><span>{toast.message}</span><button aria-label="Dismiss notification" onClick={() => setToasts(current => current.filter(item => item.id !== toast.id))}>×</button></div>)}</div>
  </>;
}

export function Brand({ light = false, href = '#/login' }: { light?: boolean; href?: string }) { return <a href={href} className={`brand ${light ? 'brand--light' : ''}`} aria-label="ForgeGuide home"><span className="brand__mark"><Icon name="box" size={23}/></span><b>ForgeGuide</b></a>; }

function Login({ setup, authenticated }: { setup: boolean; authenticated: (value: Session) => void }) {
  const [name, setName] = useState(''); const [email, setEmail] = useState(''); const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const submit = async (event: React.FormEvent) => { event.preventDefault(); setBusy(true); setError(''); try { authenticated(setup ? await api.setup(name, email, password) : await api.login(email, password)); } catch (err) { setError((err as Error).message); } finally { setBusy(false); } };
  return <main className="login-page"><div className="login-intro"><Brand light/><div><p className="eyebrow">Manufacturing, connected.</p><h1>Clear instructions.<br/>Confident work.</h1><p>One shared manufacturing model. The right tools for every role.</p></div><small>ForgeGuide · Manufacturing platform</small></div><section className="login-form"><div className="login-form__inner"><p className="eyebrow">{setup ? 'Welcome to your workspace' : 'Your manufacturing workspace'}</p><h2>{setup ? 'Create the first administrator' : 'Sign in'}</h2><p className="muted">{setup ? 'Set up your administrator account, then configure your manufacturing environment.' : 'Use your work account to continue.'}</p><form onSubmit={submit}>{setup && <label>Name<input autoComplete="name" required value={name} onChange={e => setName(e.target.value)}/></label>}<label>Email<input type="email" autoComplete="username" required value={email} onChange={e => setEmail(e.target.value)}/></label><label>Password<input type="password" autoComplete={setup ? 'new-password' : 'current-password'} required minLength={setup ? 10 : undefined} value={password} onChange={e => setPassword(e.target.value)}/>{setup && <small>Use at least 10 characters.</small>}</label>{error && <p className="inline-error" role="alert">{error}</p>}<Button type="submit" disabled={busy}>{busy ? 'Please wait…' : setup ? 'Create workspace account' : 'Sign in'}</Button></form><a className="text-link" href="#/shop">Visit the product store <span aria-hidden="true">↗</span></a></div></section></main>;
}
