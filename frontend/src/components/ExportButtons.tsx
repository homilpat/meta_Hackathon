import { useState } from 'react'
import { readable } from '../api/client'

// G10: download the server's DOCX/PDF export (X-User header, so not a plain link). A 409 explains why it is refused.
export function ExportButtons({ user, path, label }: { user: string; path: string; label: string }) {
  const [msg, setMsg] = useState('')
  const get = async (format: string) => {
    const r = await fetch(`${path}${path.includes('?') ? '&' : '?'}format=${format}`, { headers: { 'X-User': user } })
    if (!r.ok) { const j = await r.json().catch(() => ({})); setMsg(readable(r.status, j)); return }
    const name = /filename="([^"]+)"/.exec(r.headers.get('Content-Disposition') ?? '')?.[1] ?? `export.${format}`
    const a = document.createElement('a')
    a.href = URL.createObjectURL(await r.blob()); a.download = name; a.click(); URL.revokeObjectURL(a.href)
    setMsg(`${name} · 검증 필드 ${r.headers.get('X-Fields-Checked')}개 · SHA-256 ${r.headers.get('X-File-SHA256')?.slice(0, 12)}`)
  }
  return <div className="mt"><span className="row-gap">
    <button className="button secondary" onClick={() => get('docx')}>{label} DOCX</button>
    <button className="button secondary" onClick={() => get('pdf')}>{label} PDF</button></span>
    {msg && <p className="muted wrap" role="status">{msg}</p>}</div>
}
