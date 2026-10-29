import type { ReactNode } from 'react'
import type { Tone } from '../types'

export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    grid: <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
    database: <><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7"/></>,
    chart: <><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></>,
    spark: <><path d="m12 2 1.7 6.3L20 10l-6.3 1.7L12 18l-1.7-6.3L4 10l6.3-1.7z"/><path d="m19 16 .7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7z"/></>,
    history: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/></>,
    document: <><path d="M6 2h9l4 4v16H6z"/><path d="M14 2v5h5M9 12h6M9 16h6"/></>,
    nodes: <><circle cx="5" cy="12" r="3"/><circle cx="19" cy="5" r="3"/><circle cx="19" cy="19" r="3"/><path d="m8 11 8-4M8 13l8 4"/></>,
    shield: <><path d="M12 2 20 5v6c0 5-3.4 9-8 11-4.6-2-8-6-8-11V5z"/><path d="m8 12 2.5 2.5L16 9"/></>,
    chevron: <path d="m9 18 6-6-6-6"/>,
    check: <path d="m5 12 4 4L19 6"/>,
    warning: <><path d="M12 3 2 21h20z"/><path d="M12 9v5M12 18h.01"/></>,
    arrow: <><path d="M5 12h14M14 7l5 5-5 5"/></>,
    pulse: <path d="M2 12h4l3-8 4 16 3-8h6"/>,
  }
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}
export const Badge = ({ children, tone = 'slate' }: { children: ReactNode; tone?: Tone }) => <span className={`badge badge-${tone}`}>{children}</span>
export const Card = ({ children, className = '' }: { children: ReactNode; className?: string }) => <section className={`card ${className}`}>{children}</section>
export const SectionTitle = ({ title, sub, action }: { title: string; sub?: string; action?: ReactNode }) =>
  <div className="section-title"><div><strong>{title}</strong>{sub && <span>{sub}</span>}</div>{action}</div>
export const Empty = ({ children }: { children: ReactNode }) => <p className="muted">{children}</p>
export const Note = ({ children }: { children: ReactNode }) => <div className="science-note"><Icon name="warning"/><span>{children}</span></div>
export const Cite = ({ ids }: { ids: string[] }) => <>{ids.length ? ids.map(i => <span className="citation" key={i}>{i}</span>) : <span className="muted">-</span>}</>

export function Page({ title, desc, action, children }: { title: string; desc: string; action?: ReactNode; children: ReactNode }) {
  return <main className="page"><div className="page-head"><div><h1>{title}</h1><p>{desc}</p></div>{action}</div>{children}</main>
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="muted" style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 8 }}>{label}{children}</label>
}
