import { useEffect, useState } from 'react'
import { Badge, Card, Note, SectionTitle } from '../../components/ui'
import { say, show, words } from '../../labels'
import type { Ctx, J } from '../../types'

const RESULT_TONE: Record<string, 'green' | 'amber' | 'red'> = { PASS: 'green', WARN: 'amber', BLOCK: 'red' }

function DiffList({ diff }: { diff: J[] }) {
  if (!diff.length) return <p className="muted">변경 없음</p>
  return <div className="stack">{diff.map((x: J) => <div key={x.claim_id + x.change} className="detail-row wrap">
    <span><Badge tone={x.change === 'REMOVED' ? 'red' : x.change === 'ADDED' ? 'green' : 'amber'}>{x.change}</Badge> {x.claim_id}</span>
    <b className="wrap">{x.change === 'CHANGED' ? Object.entries(x.fields as Record<string, unknown[]>).map(([f, [a, b]]) => `${f}: ${show(a)} → ${show(b)}`).join(' · ')
      : (x.after ?? x.before)?.text}</b></div>)}</div>
}

// G9: every save is a new version re-validated by the server; an AI suggestion is only a proposal until submitted.
export function DocEditor({ ctx, d, latest, onSaved }: { ctx: Ctx; d: J; latest: boolean; onSaved: (v: number) => void }) {
  const base = `/cases/${ctx.cid}/${d.kind}/${d.version}`
  const [cid, setCid] = useState('')
  const [text, setText] = useState('')
  const [value, setValue] = useState('')
  const [unit, setUnit] = useState('')
  const [ev, setEv] = useState('')
  const [reason, setReason] = useState('')
  const [instruction, setInstruction] = useState('')
  const [proposal, setProposal] = useState<J | null>(null)
  const [diff, setDiff] = useState<J | null>(null)
  const [check, setCheck] = useState<J | null>(null)
  useEffect(() => {
    setProposal(null); setCheck(null); setDiff(null)
    ctx.api(`${base}/validation`).then(setCheck).catch(() => setCheck(null))
    if (d.version > 1) ctx.api(`${base}/diff`).then(setDiff).catch(() => setDiff(null))
  }, [base, ctx.tick]) // eslint-disable-line react-hooks/exhaustive-deps
  const pick = (id: string) => {
    const c = d.claims.find((x: J) => x.claim_id === id)
    setCid(id); setText(c?.text ?? ''); setValue(c?.value == null ? '' : String(c.value)); setUnit(c?.unit ?? ''); setEv((c?.evidence_ids ?? []).join(', '))
  }
  const save = async (changes: J[], ai = false) => {
    const r = await ctx.api(`${base}/edits`, 'POST', { expected_sha256: d.content_sha256, reason, changes, ai_proposal: ai }, true)
    setProposal(null); setReason(''); onSaved(r.version); ctx.refresh()
  }
  const manual = () => {
    const c = d.claims.find((x: J) => x.claim_id === cid)
    const ch: J = { claim_id: cid }
    if (text !== c.text) ch.text = text
    if (value !== (c.value == null ? '' : String(c.value))) ch.value = value === '' ? null : Number(value)
    if (unit !== (c.unit ?? '')) ch.unit = unit || null
    const ids = ev.split(',').map(s => s.trim()).filter(Boolean)
    if (ids.join(',') !== c.evidence_ids.join(',')) ch.evidence_ids = ids
    return save([ch])
  }
  const author = ctx.me?.role === 'AUTHOR'
  return <Card><SectionTitle title="문서 편집" sub="저장하면 새 버전이 되고 다시 검증합니다"/>
    {check ? <div className="detail-row"><span>검증 결과</span>
      <span><Badge tone={RESULT_TONE[check.result]}>{check.result}</Badge>{check.stale && <> <Badge tone="red">다시 검증 필요</Badge></>}</span></div>
      : <p className="muted">아직 검증하지 않은 버전</p>}
    {check?.stale && <Note>{check.stale_reasons.map(words).join(' · ')} — 다시 검증해야 승인할 수 있습니다.</Note>}
    {check?.issues?.length > 0 && <ul className="muted wrap">{check.issues.map((i: J, n: number) => <li key={n}>[{say(i.severity)}] {i.claim_id ?? '문서'}: {words(i.message)}</li>)}</ul>}
    <button className="button secondary full" onClick={async () => { setCheck(await ctx.api(`${base}/validate`, 'POST', {})); ctx.refresh() }}>검증 실행</button>
    {diff && <><p className="muted mt">v{diff.from} → v{diff.to} 변경</p><DiffList diff={diff.diff}/></>}
    {author && latest && <>
      <select className="mt" value={cid} onChange={e => pick(e.target.value)} aria-label="편집할 주장"><option value="">편집할 주장 선택</option>{d.claims.map((c: J) => <option key={c.claim_id} value={c.claim_id}>{c.claim_id} · {c.text.slice(0, 40)}</option>)}</select>
      {cid && <>
        <textarea className="input" aria-label="주장 문장" value={text} onChange={e => setText(e.target.value)}/>
        <div className="dual"><input className="input" aria-label="값" placeholder="값" value={value} onChange={e => setValue(e.target.value)}/><input className="input" aria-label="단위" placeholder="단위" value={unit} onChange={e => setUnit(e.target.value)}/></div>
        <input className="input" aria-label="근거 ID" placeholder="근거 기록 ID (쉼표 구분)" value={ev} onChange={e => setEv(e.target.value)}/></>}
      <input className="input" aria-label="수정 사유" placeholder="수정 사유 (5자 이상)" value={reason} onChange={e => setReason(e.target.value)}/>
      <button className="button primary full" disabled={!cid || reason.trim().length < 5} onClick={manual}>새 버전으로 저장</button>
      <input className="input mt" aria-label="AI 지시" placeholder="AI 수정 제안 요청 (예: 더 간결하게)" value={instruction} onChange={e => setInstruction(e.target.value)}/>
      <button className="button secondary full" disabled={instruction.trim().length < 3} onClick={async () => setProposal(await ctx.api(`${base}/edit-proposals`, 'POST', { instruction }))}>AI 제안 받기 (적용 안 됨)</button>
      {proposal && <><p className="muted">AI 제안입니다. 수락하면 새 버전으로 저장됩니다.</p><DiffList diff={proposal.diff}/>
        <button className="button success full" disabled={!proposal.changes.length || reason.trim().length < 5} onClick={() => save(proposal.changes, true)}>제안 수락하여 저장</button></>}</>}
  </Card>
}
