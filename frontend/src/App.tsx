import { useCallback, useEffect, useState } from 'react';
import { CustomerPage } from './CustomerPage';
import { OperatorPage } from './OperatorPage';
import { SupervisorPage } from './SupervisorPage';
import { Icon } from './components';
import { useSocket } from './useSocket';

type View = 'customer' | 'operator' | 'supervisor';
type Toast = { id: number; message: string; kind: 'success' | 'error' };

const viewMeta: Record<View, { label: string; icon: string; context: string }> = {
  customer: { label: 'Customer', icon: 'cart', context: 'Product Studio' },
  operator: { label: 'Operator', icon: 'worker', context: 'Work Guidance' },
  supervisor: { label: 'Supervisor', icon: 'gauge', context: 'Control Room' },
};

export default function App() {
  const [view, setView] = useState<View>(() => (window.location.hash.slice(1) as View) || 'customer');
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [mobileNav, setMobileNav] = useState(false);
  const notify = useCallback((message: string, kind: 'success' | 'error' = 'success') => {
    const id = Date.now() + Math.random(); setToasts(current => [...current, { id, message, kind }]);
    window.setTimeout(() => setToasts(current => current.filter(item => item.id !== id)), 4500);
  }, []);
  const onEvent = useCallback((event: Record<string, unknown>) => {
    setRefreshKey(value => value + 1);
    const message = typeof event.message === 'string' ? event.message : undefined;
    if (message) notify(message);
  }, [notify]);
  const connected = useSocket(onEvent);

  useEffect(() => {
    const onHash = () => { const next = window.location.hash.slice(1); if (next in viewMeta) setView(next as View); };
    window.addEventListener('hashchange', onHash); return () => window.removeEventListener('hashchange', onHash);
  }, []);
  useEffect(() => {
    document.body.classList.toggle('nav-open', mobileNav);
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') setMobileNav(false); };
    window.addEventListener('keydown', closeOnEscape);
    return () => { document.body.classList.remove('nav-open'); window.removeEventListener('keydown', closeOnEscape); };
  }, [mobileNav]);
  const navigate = (next: View) => { window.location.hash = next; setView(next); setMobileNav(false); };

  return <div className="app-shell">
    <aside id="primary-navigation" className={`sidebar ${mobileNav ? 'sidebar--open' : ''}`}>
      <div className="brand"><span className="brand__mark"><Icon name="fan" size={27}/></span><span><b>ForgeGuide</b><small>Smart Manufacturing Lab</small></span></div>
      <div className="sidebar__context"><small>Workspace</small><strong>{viewMeta[view].context}</strong></div>
      <nav className="primary-nav" aria-label="Role views">{(Object.entries(viewMeta) as [View, typeof viewMeta[View]][]).map(([key, item]) => <button key={key} className={view === key ? 'active' : ''} aria-current={view === key ? 'page' : undefined} onClick={() => navigate(key)}><Icon name={item.icon}/><span>{item.label}</span>{view === key && <i/>}</button>)}</nav>
      <div className="sidebar__bottom"><div className={`connection ${connected ? 'online' : ''}`}><span/><div><b>{connected ? 'Live updates on' : 'Reconnecting'}</b><small>{connected ? 'WebSocket connected' : 'Waiting for backend'}</small></div></div><div className="lab-id"><span>SM</span><div><b>Demo Workspace</b><small>IIT Bombay</small></div></div></div>
    </aside>
    {mobileNav && <button className="nav-scrim" aria-label="Close navigation" onClick={() => setMobileNav(false)}/>}
    <div className="app-main">
      <header className="topbar"><button className="mobile-menu" onClick={() => setMobileNav(true)} aria-label="Open navigation" aria-expanded={mobileNav} aria-controls="primary-navigation"><span/><span/><span/></button><div className="topbar__title"><span>{viewMeta[view].context}</span><small>/</small><b>{viewMeta[view].label}</b></div><div className="topbar__right"><span className={`live-pill ${connected ? 'online' : ''}`}><i/>{connected ? 'System live' : 'Offline'}</span><time>{new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date())}</time></div></header>
      <main className="content">{view === 'customer' && <CustomerPage notify={notify}/>} {view === 'operator' && <OperatorPage notify={notify} refreshKey={refreshKey}/>} {view === 'supervisor' && <SupervisorPage notify={notify} refreshKey={refreshKey}/>}</main>
      <footer>Smart Operator Guidance · Proof of Concept</footer>
    </div>
    <div className="toast-stack" aria-live="polite">{toasts.map(toast => <div className={`toast toast--${toast.kind}`} key={toast.id}><Icon name={toast.kind === 'success' ? 'check' : 'alert'}/><span>{toast.message}</span><button onClick={() => setToasts(current => current.filter(item => item.id !== toast.id))}>×</button></div>)}</div>
  </div>;
}
