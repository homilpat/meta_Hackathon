import { useState } from 'react'
import { Badge, Card, Field, Icon, Page, SectionTitle } from '../../components/ui'
import { useLoad } from '../../hooks/useLoad'
import type { Ctx, J, Tone } from '../../types'

export function Audit({ ctx }: { ctx: Ctx }) {
  const tl = useLoad<J[]>(ctx, ctx.cid ? `/cases/${ctx.cid}/timeline` : '', [])
  const chain = useLoad<J>(ctx, '/audit/verify', null)
  const policies: [string, string, Tone][] = [
    ['미배정 사건 접근', '배정되지 않은 사용자는 403', 'red'], ['외부 전송 제한', 'SYNTHETIC + APPROVED_FOR_EXTERNAL만 Meta로 전송, 그 외 전송 전 차단', 'green'],
    ['감사 기록 불변', 'approval_events · workflow_events 수정/삭제를 DB 트리거로 차단', 'blue'], ['오래된 버전 결재', '최신이 아니거나 해시가 다르면 409', 'amber'], ['AI 조사 쿼터', '사용자당 시간당 10회 초과 시 429', 'amber'], ['운영 한도 변경', 'AI 운영(AGENT_ADMIN)만 사유와 함께 변경, 이력은 추가만 가능', 'violet']]
  return <Page title="감사 및 보안" desc="사건 타임라인과 서버가 강제하는 정책입니다.">
    {chain && <div className={chain.ok ? 'immutable' : 'revision-alert'}><Icon name="shield"/><span><b>감사 해시 체인 {chain.ok ? '무결' : '불일치 발견'}</b> {chain.links}개 기록 검증 · 헤드 {chain.head_sha256.slice(0, 16)}…{!chain.ok && ` · ${chain.breaks.map((x: J) => `${x.table}#${x.row_id} ${x.problem}`).join(', ')}`}</span></div>}
    <div className="security-grid">{policies.map(x => <Card key={x[0]}><div className={`security-icon ${x[2]}`}><Icon name="shield"/></div><b>{x[0]}</b><span className="muted">{x[1]}</span><Badge tone={x[2]}>서버 정책</Badge></Card>)}</div>
    <Card><SectionTitle title="감사 이벤트" sub={`${tl.length}건 · 추가만 가능한 기록`}/><div className="table-wrap"><table><thead><tr><th>시각</th><th>행위자</th><th>이벤트</th><th>내용</th></tr></thead><tbody>
      {tl.map((t, i) => <tr key={i}><td>{t.at.slice(0, 19)}</td><td>{t.actor_id}</td><td><Badge tone={t.event.includes('REVALIDATION') ? 'red' : t.event.startsWith('BASIS') ? 'amber' : t.event === 'APPROVE' ? 'green' : 'slate'}>{t.event}</Badge></td><td className="wrap">{t.detail}</td></tr>)}
    </tbody></table></div></Card>
    <Limits ctx={ctx}/>
    <InspectionForms ctx={ctx}/>
  </Page>
}

const BASIS: Record<string, [string, Tone]> = { STANDARD: ['외부 기준', 'blue'], MEASURED: ['측정', 'green'], DERIVED: ['계산', 'teal'], DECISION: ['결정', 'violet'], DEFAULT: ['임의 기본값', 'amber'] }

// Operating limits with where each value comes from; only the AI operations department changes them, with a reason.
function Limits({ ctx }: { ctx: Ctx }) {
  const data = useLoad<J>(ctx, '/limits', null)
  const [form, setForm] = useState({ name: '', value: '', reason: '' })
  const admin = ctx.me?.role === data?.admin_role
  const save = async () => { try { await ctx.api(`/limits/${form.name}`, 'POST', { value: form.value, reason: form.reason }); setForm({ name: '', value: '', reason: '' }); ctx.refresh() } catch { /* error bar */ } }
  if (!data) return null
  return <Card><SectionTitle title="운영 한도" sub={`근거와 함께 공개 · 변경은 ${data.admin_role}만`}/><div className="table-wrap"><table><thead><tr><th>항목</th><th>값</th><th>단위</th><th>근거</th><th>출처</th><th>적용</th></tr></thead><tbody>
    {data.limits.map((l: J) => <tr key={l.name}><td>{l.name}</td><td><b>{String(l.value)}</b></td><td className="wrap">{l.unit}</td><td><Badge tone={BASIS[l.basis]?.[1] ?? 'slate'}>{BASIS[l.basis]?.[0] ?? l.basis}</Badge></td><td className="wrap muted">{l.source}</td><td>{l.set_by}{l.restart_required ? ' · 재시작 필요' : ''}</td></tr>)}
  </tbody></table></div>
    {admin && <div className="row-gap"><select aria-label="변경할 항목" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}><option value="">항목 선택</option>{data.limits.map((l: J) => <option key={l.name}>{l.name}</option>)}</select>
      <input aria-label="새 값" placeholder="새 값" value={form.value} onChange={e => setForm(f => ({ ...f, value: e.target.value }))}/>
      <input aria-label="변경 사유" placeholder="사유 (필수)" value={form.reason} onChange={e => setForm(f => ({ ...f, reason: e.target.value }))}/>
      <button className="button primary" disabled={!form.name || !form.value || !form.reason.trim()} onClick={save}>변경</button></div>}
    {admin && <LimitProposals ctx={ctx}/>}
    {data.history.length > 0 && <Field label="변경 이력">{data.history.map((h: J, i: number) => <span key={i} className="muted">{h.at.slice(0, 19)} · {h.actor_id} · {h.name} = {h.value} · {h.reason}</span>)}</Field>}</Card>
}

// v5.14 AI-CFG-04: Meta proposes from run statistics, the server replays each value on recorded runs, the admin decides.
const PSTATUS: Record<string, [string, Tone]> = { PROPOSED: ['검토 대기', 'amber'], APPROVED: ['승인·적용됨', 'green'], REJECTED: ['거절됨', 'slate'], INVALID: ['서버가 거부', 'red'] }
function LimitProposals({ ctx }: { ctx: Ctx }) {
  const list = useLoad<J[]>(ctx, '/limit-proposals', [])
  const [why, setWhy] = useState<Record<number, string>>({})
  const [busy, setBusy] = useState(false)
  const go = async (call: () => Promise<unknown>) => { if (busy) return; setBusy(true); try { await call(); ctx.refresh() } catch { /* error bar */ } finally { setBusy(false) } }
  const decide = (id: number, decision: string) => go(() => ctx.api(`/limit-proposals/${id}/decision`, 'POST', { decision, reason: why[id] ?? '' }))
  return <div className="mt"><p className="row-gap wrap"><b>AI 설정 변경 제안</b>
    <button className="button secondary" disabled={busy} onClick={() => go(() => ctx.api('/limit-proposals', 'POST', {}))}>최근 실행 기록으로 제안 받기</button>
    <span className="muted">AI는 제안만 합니다. 승인해야 적용됩니다.</span></p>
    {(Array.isArray(list) ? list : []).map(p => { const c = p.comparison ?? {}; return <div key={p.proposal_id} className="intake-card">
      <p className="row-gap wrap"><Badge tone={PSTATUS[p.status]?.[1] ?? 'slate'}>{PSTATUS[p.status]?.[0] ?? p.status}</Badge><b>{p.name}</b>
        <span>{p.current} → <b>{p.proposed}</b> {p.unit}</span><span className="muted">적용 범위: 전체</span></p>
      <p className="wrap">{p.reason}</p>
      {p.issue ? <p className="muted wrap">거부 이유: {p.issue}</p> : <p className="muted wrap">최근 {c.runs_compared}건에 적용했다면: 끊겼을 실행 {c.would_cut}건 (그중 성공했던 실행 {c.would_cut_validated}건) · 지금 상한에 걸려 실패한 실행 {c.stopped_at_current_cap}건</p>}
      {p.status === 'PROPOSED' && <p className="row-gap"><input className="input" aria-label={`제안 ${p.proposal_id} 판단 사유`} placeholder="판단 사유 (필수)" value={why[p.proposal_id] ?? ''} onChange={e => setWhy({ ...why, [p.proposal_id]: e.target.value })}/>
        <button className="button primary" disabled={busy || !(why[p.proposal_id] ?? '').trim()} onClick={() => decide(p.proposal_id, 'APPROVED')}>승인하고 적용</button>
        <button className="button secondary" disabled={busy || !(why[p.proposal_id] ?? '').trim()} onClick={() => decide(p.proposal_id, 'REJECTED')}>거절</button></p>}
      {p.decision && <p className="muted">{p.decision.by} · {p.decision.reason}</p>}</div> })}
  </div>
}

// Company inspection XLSX forms (spec §28): blanks to fill with a real form's header words; AI operations registers.
const FLABEL: Record<string, string> = { part_number: '품번', lot: 'LOT', inspected_on: '검사일', inspected_qty: '검사 수량', defective_qty: '불량 수량', item: '측정 항목', value: '측정값', unit: '단위' }

function InspectionForms({ ctx }: { ctx: Ctx }) {
  const data = useLoad<J>(ctx, '/inspection-forms', null)
  const [name, setName] = useState('')
  const [words, setWords] = useState<Record<string, string>>({})
  const [req, setReq] = useState<string[]>(['lot', 'inspected_qty', 'defective_qty'])
  const [reason, setReason] = useState('')
  const admin = ctx.me?.role === data?.admin_role
  if (!data) return null
  const save = async () => {
    const fields = Object.fromEntries(data.fields.map((k: string) => [k, (words[k] ?? '').split(',').map(w => w.trim()).filter(Boolean)]))
    try { await ctx.api('/inspection-forms', 'POST', { name, fields, required: req, reason }, true); setName(''); setWords({}); setReason(''); ctx.refresh() } catch { /* error bar */ }
  }
  return <Card><SectionTitle title="검사 결과 XLSX 양식" sub={`실제 회사 양식의 헤더 단어를 빈칸에 채워 등록합니다. 고치면 새 버전으로 남습니다. 등록: ${data.admin_role}`}/>
    {data.forms.map((f: J) => <p key={f.name} className="muted wrap"><b>{f.name}</b> v{f.version} {f.builtin ? '(기본 합성 양식)' : `· ${f.created_by} · ${f.reason}`} · 필수 {f.required.map((k: string) => FLABEL[k] ?? k).join(', ')} · {Object.entries(f.fields).map(([k, w]) => `${FLABEL[k] ?? k}: ${(w as string[]).join('/')}`).join(' · ')}</p>)}
    {admin ? <div className="mt">
      <Field label="양식 이름"><input className="input" aria-label="양식 이름" value={name} onChange={e => setName(e.target.value)}/></Field>
      {data.fields.map((k: string) => <div key={k} className="row-gap"><label className="row-gap"><input type="checkbox" aria-label={`${FLABEL[k] ?? k} 필수`} checked={req.includes(k)} onChange={e => setReq(e.target.checked ? [...req, k] : req.filter(x => x !== k))}/> 필수</label>
        <Field label={`${FLABEL[k] ?? k} 열의 헤더 단어 (쉼표로 구분, 비우면 사용 안 함)`}><input className="input" aria-label={`${FLABEL[k] ?? k} 헤더 단어`} value={words[k] ?? ''} onChange={e => setWords({ ...words, [k]: e.target.value })}/></Field></div>)}
      <Field label="등록 사유"><input className="input" aria-label="양식 등록 사유" value={reason} onChange={e => setReason(e.target.value)}/></Field>
      <button className="button primary" disabled={!name.trim() || !reason.trim()} onClick={save}>양식 등록 (새 버전)</button>
    </div> : <p className="muted">양식 등록·수정은 {data.admin_role} 역할만 할 수 있습니다.</p>}
  </Card>
}
