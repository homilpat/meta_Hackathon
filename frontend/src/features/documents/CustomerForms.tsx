import { useState } from 'react'
import { readable } from '../../api/client'
import { Badge, Card, Note, SectionTitle } from '../../components/ui'
import { useLoad } from '../../hooks/useLoad'
import { toBase64 } from '../intake/Intake'
import { say } from '../../labels'
import type { Ctx, J, Tone } from '../../types'

// §30.1 DOC-OUT-01..04: a customer's DOCX form, slots mapped to case fields (AI proposal, a person confirms),
// previewed with this case's own values and exported as a draft or, when nothing blocks it, the final file.
const ROUTE: Record<string, [string, Tone]> = { CONFIRMED: ['확정 매핑', 'green'], REUSABLE: ['같은 구조의 확정 매핑 재사용', 'blue'], NEEDS_REVIEW: ['매핑 검토 필요', 'amber'] }
const STATUS: Record<string, [string, Tone]> = { FILLED: ['채움', 'green'], MISSING: ['작성 필요', 'amber'], UNAPPROVED: ['미승인', 'red'], UNMAPPED: ['연결 안 함', 'slate'] }

export function CustomerForms({ ctx }: { ctx: Ctx }) {
  const list = useLoad<J[]>(ctx, '/customer-templates', [])
  const [tid, setTid] = useState<number | null>(null)
  const [t, setT] = useState<J>(null)
  const [view, setView] = useState<J>(null)
  const [prop, setProp] = useState<J>(null)
  const [map, setMap] = useState<Record<string, string | null>>({})
  const [req, setReq] = useState<string[]>([])
  const [fmt, setFmt] = useState<Record<string, string>>({})
  const [why, setWhy] = useState('')
  const [reg, setReg] = useState({ customer: '', name: '', reason: '' })
  const [file, setFile] = useState<File | null>(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const go = async (call: () => Promise<void>) => { if (busy) return; setBusy(true); try { await call() } catch { /* error bar */ } finally { setBusy(false) } }
  const open = (id: number) => go(async () => {
    const x: J = await ctx.api(`/customer-templates/${id}`)
    setTid(id); setT(x); setProp(null); setMsg('')
    const m = x.mapping?.mapping ?? {}
    setMap(Object.fromEntries(x.slots.map((s: J) => [s.id, m[s.id] ?? null]))); setReq(x.mapping?.required ?? []); setFmt(x.mapping?.formats ?? {})
    setView(ctx.cid && x.mapping ? await ctx.api(`/cases/${ctx.cid}/customer-templates/${id}/preview`).catch(() => null) : null)
  })
  const register = () => go(async () => {
    const x: J = await ctx.api('/customer-templates', 'POST', { ...reg, content_base64: await toBase64(file as File) }, true)
    ctx.refresh(); await open(x.template_id)
  })
  const ask = () => go(async () => {
    const out: J = await ctx.api(`/customer-templates/${tid}/proposals`, 'POST', {})
    setProp(out)
    if (out.proposal) { setMap(out.proposal.mapping); setFmt(out.proposal.formats ?? {}) }
  })
  const keep = () => go(async () => {
    await ctx.api(`/customer-templates/${tid}/mapping`, 'POST', { mapping: map, required: req, formats: fmt, proposal_id: prop?.proposal_id ?? null, reason: why }, true)
    setWhy(''); await open(tid as number)
  })
  const download = async (mode: string) => {
    const r = await fetch(`/cases/${ctx.cid}/customer-templates/${tid}/export?mode=${mode}`, { headers: { 'X-User': ctx.me.id } })
    if (!r.ok) { const j = await r.json().catch(() => ({})); setMsg(readable(r.status, j)); return }
    const name = decodeURIComponent(/filename\*=UTF-8''([^;]+)/.exec(r.headers.get('Content-Disposition') ?? '')?.[1] ?? `form_${mode}.docx`)
    const a = document.createElement('a')
    a.href = URL.createObjectURL(await r.blob()); a.download = name; a.click(); URL.revokeObjectURL(a.href)
    setMsg(`${name} · 매핑 v${r.headers.get('X-Mapping-Version')} · 사건 데이터 ${r.headers.get('X-Case-Data-Version')} · SHA-256 ${r.headers.get('X-File-SHA256')?.slice(0, 12)}`)
  }
  const author = ctx.me?.role === 'AUTHOR'
  const unresolved: string[] = prop?.proposal?.unresolved ?? []
  return <Card className="mt"><SectionTitle title="고객사 DOCX 양식" sub="양식의 빈칸을 사건 필드에 연결해 이 사건의 값으로 채웁니다. 완성본은 제출 필수 값이 모두 있고 승인된 값일 때만 출력됩니다."/>
    {author && <div className="row-gap wrap">
      <input className="input" aria-label="양식 고객사" placeholder="고객사" value={reg.customer} onChange={e => setReg({ ...reg, customer: e.target.value })}/>
      <input className="input" aria-label="양식 이름" placeholder="양식 이름" value={reg.name} onChange={e => setReg({ ...reg, name: e.target.value })}/>
      <input type="file" aria-label="양식 파일" accept=".docx" onChange={e => setFile(e.target.files?.[0] ?? null)}/>
      <input className="input" aria-label="양식 등록 사유" placeholder="등록 사유" value={reg.reason} onChange={e => setReg({ ...reg, reason: e.target.value })}/>
      <button className="button secondary" disabled={busy || !file || !reg.customer.trim() || !reg.name.trim() || !reg.reason.trim()} onClick={register}>양식 등록</button></div>}
    <p className="row-gap wrap">{(Array.isArray(list) ? list : []).map(x => <button key={x.template_id} className={`button ${x.template_id === tid ? 'primary' : 'secondary'}`} onClick={() => open(x.template_id)}>{x.customer} · {x.name} v{x.version}</button>)}</p>
    {t && <>
      <p className="row-gap wrap"><Badge tone={ROUTE[t.route]?.[1] ?? 'slate'}>{ROUTE[t.route]?.[0] ?? t.route}</Badge><span className="muted">칸 {t.slots.length}개 · {say(t.data_origin)}{t.mapping ? ` · 매핑 ${t.mapping.version}번째 확정본` : ''}</span>
        {author && <button className="button secondary" disabled={busy} onClick={ask}>AI 매핑 제안 받기</button>}</p>
      {prop && <p className="row-gap"><Badge tone={prop.status === 'OK' ? 'blue' : 'red'}>{prop.status === 'OK' ? 'AI 제안' : 'AI 제안 실패'}</Badge></p>}
      {prop?.issues?.map((i: J, n: number) => <Note key={n}>{i.message}</Note>)}
      <div className="table-wrap"><table><thead><tr><th>칸</th><th>라벨</th><th>사건 필드</th><th>서식</th><th>필수</th><th>이 사건의 값 · 출처</th></tr></thead><tbody>
        {t.slots.map((s: J) => { const v = view?.slots?.find((x: J) => x.id === s.id); return <tr key={s.id}>
          <td>{s.id}</td><td className="wrap">{s.label}{s.certain === false && <> <Badge tone="violet">빈칸인지 확인</Badge></>}{unresolved.includes(s.id) && <> <Badge tone="amber">미확정</Badge></>}{prop?.proposal?.reasons?.[s.id] && <div className="muted">{prop.proposal.reasons[s.id]}</div>}</td>
          <td><select className="input" aria-label={`${s.label} 필드`} value={map[s.id] ?? ''} disabled={!author} onChange={e => setMap({ ...map, [s.id]: e.target.value || null })}>
            <option value="">(연결 안 함)</option>{t.fields.map((f: J) => <option key={f.id} value={f.id}>{f.label} · {f.id}</option>)}</select></td>
          <td><select className="input" aria-label={`${s.label} 서식`} value={fmt[s.id] ?? 'AS_IS'} disabled={!author} onChange={e => setFmt({ ...fmt, [s.id]: e.target.value })}>
            {(t.formats ?? ['AS_IS']).map((f: string) => <option key={f} value={f}>{f}</option>)}</select></td>
          <td><input type="checkbox" aria-label={`${s.label} 필수`} checked={req.includes(s.id)} disabled={!author} onChange={e => setReq(e.target.checked ? [...req, s.id] : req.filter(x => x !== s.id))}/></td>
          <td className="wrap">{v ? <><Badge tone={STATUS[v.status]?.[1] ?? 'slate'}>{STATUS[v.status]?.[0] ?? v.status}</Badge> {v.shown && v.shown !== v.value ? <>{v.shown} <span className="muted">(원래 {v.value})</span></> : v.value ?? ''}{v.converted === false && <> <Badge tone="red">서식 변환 불가</Badge></>} <span className="muted" title={v.version ?? ''}>{v.source ?? ''}</span></> : <span className="muted">-</span>}</td></tr> })}
      </tbody></table></div>
      {author && <p className="row-gap wrap"><input className="input" aria-label="매핑 확정 사유" placeholder="확정 사유 (필수)" value={why} onChange={e => setWhy(e.target.value)}/>
        <button className="button primary" disabled={busy || !why.trim()} onClick={keep}>원본 칸·출처 확인 후 매핑 확정</button></p>}
      {ctx.cid && t.mapping && <>
        {view?.final_blocked_by?.map((b: J, n: number) => <Note key={n}>완성본 차단: {b.message}</Note>)}
        <p className="row-gap"><button className="button secondary" onClick={() => download('draft')}>초안 DOCX</button>
          <button className="button primary" disabled={!!view?.final_blocked_by?.length} onClick={() => download('final')}>완성본 DOCX</button>
          {view && <span className="muted">사건 데이터 버전 {view.case_data_version}</span>}</p></>}
      {msg && <p className="muted wrap" role="status">{msg}</p>}
    </>}
  </Card>
}
