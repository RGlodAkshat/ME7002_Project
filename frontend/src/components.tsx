import type { ButtonHTMLAttributes, ReactNode } from 'react';

export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    fan: <><circle cx="12" cy="12" r="2"/><path d="M12 10c-1-5 1-7 3-7 2 1 2 4 0 7M14 12c5-1 7 1 7 3-1 2-4 2-7 0M12 14c1 5-1 7-3 7-2-1-2-4 0-7M10 12c-5 1-7-1-7-3 1-2 4-2 7 0"/></>,
    cart: <><circle cx="9" cy="20" r="1"/><circle cx="19" cy="20" r="1"/><path d="M3 4h2l2.5 11h11l2-7H7"/></>,
    worker: <><path d="M4 21v-2a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v2M8 7a4 4 0 0 0 8 0M6 7h12M8 7V5a4 4 0 0 1 8 0v2"/></>,
    gauge: <><path d="M20 13a8 8 0 1 0-16 0M12 13l4-4M4 17h16"/><circle cx="12" cy="13" r="1"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
    arrow: <><path d="m9 18 6-6-6-6"/></>,
    refresh: <><path d="M20 11a8 8 0 1 0-2 5M20 4v7h-7"/></>,
    camera: <><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3"/></>,
    alert: <><path d="M12 3 2.5 20h19z"/><path d="M12 9v4M12 17h.01"/></>,
    wifi: <><path d="M5 12.5a10 10 0 0 1 14 0M8 16a6 6 0 0 1 8 0M12 20h.01"/></>,
    machine: <><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 7h8v5H8zM8 17h.01M12 17h4"/></>,
    settings: <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1z"/></>,
    chat: <path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/>,
    logout: <><path d="M10 17l5-5-5-5M15 12H3M21 3v18h-6"/></>,
    box: <><path d="m3 7 9 5 9-5-9-4zM3 7v10l9 5 9-5V7M12 12v10"/></>,
  };
  return <svg aria-hidden="true" className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name] ?? paths.box}</svg>;
}

export function Button({ children, variant = 'primary', icon, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'ghost' | 'danger'; icon?: string }) {
  return <button type="button" {...props} className={`button button--${variant} ${props.className ?? ''}`}>{icon && <Icon name={icon} size={18}/>}<span>{children}</span></button>;
}

export function Status({ value }: { value?: string | null }) {
  const text = (value || 'unknown').replaceAll('_', ' ');
  return <span className={`status status--${(value || 'unknown').toLowerCase()}`}><span className="status__dot"/>{text}</span>;
}

export function Empty({ icon = 'box', title, body }: { icon?: string; title: string; body: string }) {
  return <div className="empty"><span className="empty__icon"><Icon name={icon} size={28}/></span><h3>{title}</h3><p>{body}</p></div>;
}

export function Loading() {
  return <div className="loading"><span/><span/><span/><em>Loading live data</em></div>;
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`card ${className}`}>{children}</section>;
}

export function PageHeader({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: ReactNode }) {
  return <header className="page-header"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p className="page-header__copy">{description}</p></div>{action}</header>;
}
