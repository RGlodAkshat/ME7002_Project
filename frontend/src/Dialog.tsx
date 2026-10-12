import { useEffect, useId, useRef } from 'react';
import type { ReactNode } from 'react';

export function Dialog({ title, close, children }: { title: string; close: () => void; children: ReactNode }) {
  const ref = useRef<HTMLElement>(null); const titleId = useId();
  useEffect(() => {
    const previous = document.activeElement as HTMLElement; const original = document.body.style.overflow; document.body.style.overflow = 'hidden';
    const focusable = () => [...(ref.current?.querySelectorAll<HTMLElement>('button, input, select, textarea, a[href]') || [])].filter(element => !element.hasAttribute('disabled') && element.getBoundingClientRect().height > 0);
    focusable()[0]?.focus();
    const key = (event: KeyboardEvent) => { if ([...document.querySelectorAll('[role="dialog"]')].at(-1) !== ref.current) return; if (event.key === 'Escape') close(); if (event.key === 'Tab') { const items = focusable(); const first = items[0]; const last = items.at(-1); if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); } } };
    window.addEventListener('keydown', key);
    return () => { document.body.style.overflow = original; window.removeEventListener('keydown', key); previous?.focus(); };
  }, []);
  return <div className="dialog-backdrop"><section ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId} className="dialog"><header><h2 id={titleId}>{title}</h2><button className="icon-button" onClick={close} aria-label="Close dialog">×</button></header><div className="dialog-content">{children}</div></section></div>;
}
