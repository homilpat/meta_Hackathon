import { useState } from 'react'
import { Badge, Card, Cite, Empty, Field, Note, Page, SectionTitle } from '../../components/ui'
import { useLoad } from '../../hooks/useLoad'
import type { Ctx, J, Tone } from '../../types'
import { toBase64 } from '../intake/Intake'

// Requests, replies, item review and responsibility (spec v5.8 §25). The server decides every transition; this
// screen only shows its state and sends a person's action with the version they looked at.
const STATE: Record<string, Tone> = { DRAFT: 'slate', OPEN: 'blue', SUBMITTED: 'amber', IN_REVIEW: 'amber', ACCEPTED: 'green', NEEDS_REVISION: 'red', REJECTED: 'red' }
const VERDICT: Record<string, Tone> = { SUPPORTED: 'green', MISSING: 'red', CONFLICTED: 'red', NEEDS_HUMAN: 'amber' }
const KIND: Record<string, string> = { SUPPLIER_CORRECTIVE_ACTION: '협력사 대책 요청', AUDIT_CORRECTIVE_EVIDENCE: '감사 시정 증거', CUSTOMER_REPLY: '고객 회신', INTERNAL: '사내 요청' }

export function Requests({ ctx }: { ctx: Ctx }) {
  const cid = ctx.cid
  const list = useLoad<J[]>(ctx, cid ? `/cases/${cid}/requests` : '', [])
  const resp = useLoad<J>(ctx, cid ? `/cases/${cid}/responsibilities` : '', null)
  const profile = useLoad<J>(ctx, cid ? `/cases/${cid}/profile` : '', null)
  const [busy, setBusy] = useState(false)
  const act = async (call: () => Promise<J>) => {
    if (busy) return
    setBusy(true)
    try { await call(); ctx.refresh() } catch { /* error bar shows the server's reason */ } finally { setBusy(false) }
  }
  const me = ctx.me?.id
  return <Page title="요청 · 회신 · 책임" desc="협력사·감사·고객 요청과 회신 버전, 항목별 검토, 담당·인수인계를 사건에 연결해 관리합니다. 회신 수용은 조치 실행·효과 입증·원인 확정·종결이 아닙니다.">
    <OriginForm ctx={ctx} busy={busy} act={act}/>
    {!cid ? <Card><Empty>사건을 선택하세요.</Empty></Card> : <>
      <Card><SectionTitle title={`사건 ${cid}`} sub={`출처 ${profile?.origin ?? '-'} · 채널 ${profile?.channel ?? '-'}`}/>
        {profile?.profile?.slice(-1).map((p: J) => <p key={p.version} className="muted wrap">프로필 v{p.version}: {Object.entries(p.details).map(([k, v]) => `${k}=${Array.isArray(v) ? v.join('/') : v}`).join(' · ')}</p>)}
        {resp && <><p>사건 책임자 <b>{resp.case_owner.user_id ?? '미지정'}</b>{resp.case_owner.pending_handover && <> · <Badge tone="amber">인수 대기 → {resp.case_owner.pending_handover.to}</Badge></>}</p>
          <p className="muted wrap">승인 역할: {Object.entries(resp.approvers).map(([s, r]) => `${s} ${r}`).join(' · ')} · 실행자 {resp.executors.map((x: J) => x.actor_id).join(', ') || '-'} · 효과 확인 {resp.effect_verifiers.map((x: J) => x.actor_id).join(', ') || '-'}</p>
          <Handover ctx={ctx} busy={busy} act={act} path={`/cases/${cid}/owner`} pending={resp.case_owner.pending_handover?.to} canPropose={resp.case_owner.user_id === me}/>
          <p className="muted">{resp.identity_note}</p></>}</Card>
      <NewRequest ctx={ctx} busy={busy} act={act}/>
      {list.map(r => <RequestCard key={r.request_id} ctx={ctx} r={r} busy={busy} act={act}/>)}
      {!list.length && <Card><Empty>이 사건의 요청이 없습니다.</Empty></Card>}
      {resp?.history?.length > 0 && <Card><SectionTitle title="책임 · 결정 이력" sub="append-only"/>{resp.history.map((e: J, n: number) =>
        <p key={n} className="muted wrap">{e.at?.slice(0, 19)} · {e.subject} {e.subject_id} · {e.event} · {e.actor_id}({e.actor_role}){e.from || e.to ? ` · ${e.from ?? '-'}→${e.to ?? '-'}` : ''}{e.version ? ` · v${e.version}` : ''}{e.reason ? ` · ${e.reason}` : ''}</p>)}</Card>}
    </>}
  </Page>
}

type Act = (call: () => Promise<J>) => Promise<void>

function OriginForm({ ctx, busy, act }: { ctx: Ctx; busy: boolean; act: Act }) {
  const [origin, setOrigin] = useState('SUPPLIER_NONCONFORMITY')
  const [text, setText] = useState('')
  const example = origin === 'SUPPLIER_NONCONFORMITY'
    ? '{"supplier": "", "part_number": "", "delivery_lots": [], "problem": "", "requested_measures": "", "reply_due_at": "2026-11-10T18:00:00+09:00"}'
    : '{"audit_source": "", "reference": "", "finding": "", "standard": "", "standard_version": "", "department": "", "required_evidence": [""], "correction_due_at": "2026-11-20T18:00:00+09:00"}'
  return <Card><SectionTitle title="협력사 부적합 · 감사 지적 사건 등록" sub="수동 입력(채널 MANUAL). 측정값은 만들지 않으며 사건은 D0 판정 대기로 시작합니다."/>
    <div className="row-gap"><select aria-label="사건 출처" value={origin} onChange={e => { setOrigin(e.target.value); setText('') }}><option value="SUPPLIER_NONCONFORMITY">협력사 부적합</option><option value="AUDIT_FINDING">감사 지적사항</option></select></div>
    <Field label="세부 항목 (JSON)"><textarea aria-label="사건 세부 항목" rows={3} value={text || example} onChange={e => setText(e.target.value)}/></Field>
    <button className="button secondary" disabled={busy} onClick={() => act(async () => {
      const out = await ctx.api('/origin-cases', 'POST', { origin, details: JSON.parse(text || example) }, true)
      ctx.open(out.case_id, '', 'requests')
    })}>사건 등록</button></Card>
}

function NewRequest({ ctx, busy, act }: { ctx: Ctx; busy: boolean; act: Act }) {
  const [f, setF] = useState({ kind: 'SUPPLIER_CORRECTIVE_ACTION', title: '', owner_id: ctx.me?.id ?? '', reviewer_id: '', due_at: '', due_tz: 'KST', items: '' })
  const set = (k: string) => (e: { target: { value: string } }) => setF(x => ({ ...x, [k]: e.target.value }))
  return <Card><SectionTitle title="요청 카드 만들기" sub="항목: 한 줄에 '요구사항 | 필요 증거 | 판정 기준'. 담당자·검토자는 사건에 배정된 서로 다른 사람"/>
    <div className="row-gap"><select aria-label="요청 종류" value={f.kind} onChange={set('kind')}>{Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
      <input aria-label="요청 제목" placeholder="제목" value={f.title} onChange={set('title')}/><input aria-label="담당자" placeholder="담당자 id" value={f.owner_id} onChange={set('owner_id')}/>
      <input aria-label="검토자" placeholder="검토자 id" value={f.reviewer_id} onChange={set('reviewer_id')}/><input aria-label="기한" placeholder="2026-11-10 18:00" value={f.due_at} onChange={set('due_at')}/>
      <input aria-label="시간대" value={f.due_tz} onChange={set('due_tz')}/></div>
    <Field label="요구 항목"><textarea aria-label="요구 항목" rows={3} value={f.items} onChange={set('items')}/></Field>
    <button className="button secondary" disabled={busy || !f.title || !f.items} onClick={() => act(() => ctx.api(`/cases/${ctx.cid}/requests`, 'POST', {
      ...f, items: f.items.split('\n').filter(Boolean).map(l => { const [requirement, required_evidence, criterion] = l.split('|').map(x => x.trim()); return { requirement, required_evidence, criterion } }),
    }, true))}>요청 저장 (DRAFT)</button></Card>
}

function Handover({ ctx, busy, act, path, pending, canPropose }: { ctx: Ctx; busy: boolean; act: Act; path: string; pending?: string; canPropose: boolean }) {
  const [to, setTo] = useState('')
  const [reason, setReason] = useState('')
  const me = ctx.me?.id
  if (pending && pending === me) return <div className="row-gap"><span>담당 인수 요청을 받았습니다.</span>
    <button className="button primary" disabled={busy} onClick={() => act(() => ctx.api(`${path}/handover/accept`, 'POST', { reason }, true))}>수락</button>
    <button className="button secondary" disabled={busy} onClick={() => act(() => ctx.api(`${path}/handover/decline`, 'POST', { reason }, true))}>거절</button>
    <input aria-label="응답 사유" placeholder="사유 (선택)" value={reason} onChange={e => setReason(e.target.value)}/></div>
  if (!canPropose || pending) return null
  return <div className="row-gap"><input aria-label="인수자" placeholder="인수자 id" value={to} onChange={e => setTo(e.target.value)}/>
    <input aria-label="인수인계 사유" placeholder="사유" value={reason} onChange={e => setReason(e.target.value)}/>
    <button className="button secondary" disabled={busy || !to || !reason} onClick={() => act(() => ctx.api(`${path}/handover`, 'POST', { to_user: to, reason }, true))}>인수인계 요청</button></div>
}

function RequestCard({ ctx, r, busy, act }: { ctx: Ctx; r: J; busy: boolean; act: Act }) {
  const [org, setOrg] = useState(r.external_party?.org ?? '')
  const [reason, setReason] = useState('')
  const [decision, setDecision] = useState('ACCEPTED')
  const [due, setDue] = useState('')
  const me = ctx.me?.id
  const cur = r.submissions.find((s: J) => s.current)
  const ai = [...r.reviews].reverse().find((v: J) => v.kind === 'AI' && v.submission_version === r.submission_version)
  const upload = (list: FileList | null) => list?.length && act(async () => {
    const files = await Promise.all([...list].map(async f => ({ name: f.name, content_base64: await toBase64(f) })))
    await ctx.api(`/requests/${r.request_id}/submissions`, 'POST', { files, submitted_by: { org } }, true)
  })
  const post = (path: string, body?: unknown) => act(() => ctx.api(`/requests/${r.request_id}${path}`, 'POST', body, true))
  return <Card><SectionTitle title={`#${r.request_id} ${r.title}`} sub={`${KIND[r.kind] ?? r.kind} · 기한 ${r.due_at} ${r.due_tz}${r.overdue ? ' · 기한 초과' : ''}`} action={<Badge tone={STATE[r.status]}>{r.status}</Badge>}/>
    <p className="muted">담당 {r.owner_id}{r.pending_owner_id ? ` (인수 대기 → ${r.pending_owner_id})` : ''} · 검토 {r.reviewer_id} · 외부 응답 주체 {r.external_party?.org ?? '-'} (시스템 외부 발송 없음)</p>
    <div className="table-wrap"><table><thead><tr><th>항목</th><th>요구사항</th><th>필요 증거</th><th>판정 기준</th><th>AI 의견 (결정 아님)</th></tr></thead><tbody>
      {r.items.map((i: J) => { const o = ai?.items.find((x: J) => x.item_id === i.item_id); return <tr key={i.item_id}><td>{i.item_id}</td><td className="wrap">{i.requirement}</td><td className="wrap">{i.required_evidence}</td><td className="wrap">{i.criterion}</td>
        <td className="wrap">{o ? <><Badge tone={VERDICT[o.verdict]}>{o.verdict}</Badge> {o.note} <Cite ids={o.sources.map((s: J) => s.element_id)}/></> : '-'}</td></tr> })}
    </tbody></table></div>
    {r.submissions.map((s: J) => <p key={s.version} className="muted wrap">회신 v{s.version}{s.current ? ' (현재)' : ''}: {s.files.map((f: J) => f.name).join(', ')} · 제출 {s.submitted_by.org} ({s.submitted_by.identity}) · 등록 {s.registered_by} · {s.created_at?.slice(0, 19)}</p>)}
    {ai && <p className="muted">AI 검토 모드 {ai.mode}{ai.model ? ` · ${ai.model}` : ''}{ai.reason ? ` · ${ai.reason}` : ''}</p>}
    <div className="row-gap">
      {r.status === 'DRAFT' && [r.created_by, r.owner_id].includes(me) && <button className="button primary" disabled={busy} onClick={() => post('/open')}>요청 등록</button>}
      {['OPEN', 'NEEDS_REVISION', 'SUBMITTED', 'IN_REVIEW'].includes(r.status) && r.owner_id === me && <>
        <input aria-label="외부 제출 조직" placeholder="제출 조직" value={org} onChange={e => setOrg(e.target.value)}/>
        <label className="button secondary">회신 업로드<input type="file" hidden multiple accept=".pdf,.docx,.xlsx,.csv" aria-label="회신 파일" disabled={busy || !org} onChange={e => upload(e.target.files)}/></label></>}
      {r.status === 'SUBMITTED' && r.reviewer_id === me && <button className="button primary" disabled={busy} onClick={() => post('/review-start')}>검토 시작</button>}
      {cur && [r.owner_id, r.reviewer_id].includes(me) && <button className="button secondary" disabled={busy} onClick={() => post('/ai-review')}>AI 항목 검토 요청</button>}
      {r.status === 'IN_REVIEW' && r.reviewer_id === me && cur && <>
        <select aria-label="결정" value={decision} onChange={e => setDecision(e.target.value)}><option value="ACCEPTED">수용</option><option value="NEEDS_REVISION">보완 요청</option><option value="REJECTED">반려</option></select>
        <input aria-label="결정 사유" placeholder="사유 (필수)" value={reason} onChange={e => setReason(e.target.value)}/>
        <button className="button primary" disabled={busy || !reason.trim()} onClick={() => post('/decisions', { submission_version: cur.version, files_sha256: cur.files_sha256, decision, reason })}>v{cur.version} 결정</button></>}
      {['DRAFT', 'OPEN', 'SUBMITTED', 'IN_REVIEW', 'NEEDS_REVISION'].includes(r.status) && [r.created_by, r.owner_id, r.reviewer_id].includes(me) && <>
        <input aria-label="새 기한" placeholder="새 기한 (예: 2026-11-10 18:00)" value={due} onChange={e => setDue(e.target.value)}/>
        <button className="button secondary" disabled={busy || !due || !reason.trim()} onClick={() => post('/due', { due_at: due, reason })}>기한 변경</button></>}
    </div>
    {['DRAFT', 'OPEN', 'SUBMITTED', 'IN_REVIEW', 'NEEDS_REVISION'].includes(r.status) && <Handover ctx={ctx} busy={busy} act={act} path={`/requests/${r.request_id}`} pending={r.pending_owner_id} canPropose={[r.owner_id, r.created_by].includes(me)}/>}
    <Note>{r.note}</Note>
  </Card>
}
