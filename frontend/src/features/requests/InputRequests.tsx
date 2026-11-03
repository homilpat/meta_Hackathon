import { useState } from 'react'
import { Badge, Card, Note, SectionTitle } from '../../components/ui'
import { useLoad } from '../../hooks/useLoad'
import { say } from '../../labels'
import type { Ctx, J, Tone } from '../../types'

// §30.2 ASK-RESUME-01..03: a held server calculation asks for its missing input; the answer is a number a person
// enters or an original cell the server re-reads; resume re-checks everything and computes with a calculation id.
const TONE: Record<string, Tone> = { NEEDS_INPUT: 'amber', ANSWERED: 'blue', RESUMED: 'green' }
const SOURCE: Record<string, string> = { USER_ENTERED: '사용자 직접 입력', SOURCE_CELL: '원본 셀', CUSTOMER_REPORTED: '고객 보고', CHECKED: '검증된 내부 자료' }

export function InputRequests({ ctx }: { ctx: Ctx }) {
  const cid = ctx.cid
  const list = useLoad<J[]>(ctx, cid ? `/cases/${cid}/input-requests` : '', [])
  const [lot, setLot] = useState('')
  const [period, setPeriod] = useState('')
  const [last, setLast] = useState<J>(null)
  const [busy, setBusy] = useState(false)
  const go = async (call: () => Promise<void>) => { if (busy) return; setBusy(true); try { await call(); ctx.refresh() } catch { /* error bar */ } finally { setBusy(false) } }
  const start = () => go(async () => setLast(await ctx.api(`/cases/${cid}/calculations/held`, 'POST', { action: 'defect_rate', lot, period: period || null }, true)))
  if (!cid) return null
  return <Card><SectionTitle title="불량률 계산 · 누락값 확인" sub="입력이 없으면 계산을 보류하고 필요한 값만 묻습니다. 직접 입력과 원본 셀은 출처가 구분되고, 문서 증거로 승격되지 않습니다."/>
    <p className="row-gap wrap"><input className="input" aria-label="계산 LOT" placeholder="LOT (예: 0007)" value={lot} onChange={e => setLot(e.target.value)}/>
      <input className="input" aria-label="계산 기간" placeholder="기간 (선택)" value={period} onChange={e => setPeriod(e.target.value)}/>
      <button className="button primary" disabled={busy || !lot.trim()} onClick={start}>불량률 계산</button></p>
    {last?.status === 'COMPUTED' && <Result r={last}/>}
    {(Array.isArray(list) ? list : []).map(r => <Ask key={r.request_id} ctx={ctx} r={r} busy={busy} go={go}/>)}
  </Card>
}

function Result({ r }: { r: J }) {
  const part = (f: string) => r.inputs.filter((i: J) => i.field === f).map((i: J) => `${i.value}개(${SOURCE[i.source_type] ?? i.source_type})`).join(' + ')
  return <p className="wrap" title={`서버 계산 ${r.calculation.calculation_id} · 근거 ${r.inputs.map((i: J) => i.evidence_id).join(', ')}`}>
    <Badge tone="green">불량률 {r.rate_percent}%</Badge> LOT {r.lot}: 불량 {part('defective_qty')} ÷ 검사 {part('inspected_qty')}</p>
}

function Ask({ ctx, r, busy, go }: { ctx: Ctx; r: J; busy: boolean; go: (c: () => Promise<void>) => Promise<void> }) {
  const [kind, setKind] = useState('USER_ENTERED')
  const [value, setValue] = useState('')
  const [unit, setUnit] = useState('EA')
  const [loc, setLoc] = useState({ file_id: '', sheet: '', cell: '' })
  const [sug, setSug] = useState<J>(null)
  const [out, setOut] = useState<J>(null)
  const send = () => go(async () => setOut(await ctx.api(`/input-requests/${r.request_id}/answers`, 'POST', kind === 'USER_ENTERED'
    ? { kind, value: Number(value), unit } : { kind, file_id: Number(loc.file_id), sheet: loc.sheet, cell: loc.cell }, true)))
  const resume = () => go(async () => setOut(await ctx.api(`/input-requests/${r.request_id}/resume`, 'POST', {}, true)))
  const suggest = () => go(async () => setSug(await ctx.api(`/input-requests/${r.request_id}/suggestions`, 'POST', {})))
  const rejected = [...r.events].reverse().find((e: J) => e.kind === 'ANSWER_REJECTED' || e.kind === 'RESUME_HELD')
  return <div className="intake-card">
    <p className="row-gap wrap"><Badge tone={TONE[r.status] ?? 'slate'}>{say(r.status)}</Badge><span className="wrap">{r.question}</span></p>
    {r.status === 'RESUMED' ? <Result r={r.result}/> : <>
      <p className="row-gap wrap"><button className="button secondary" disabled={busy} onClick={suggest}>AI에게 값이 있을 곳 묻기</button>
        <span className="muted">열 헤더만 보냅니다. AI는 위치를 제안할 뿐 값을 정하지 않습니다.</span></p>
      {sug?.candidates?.map((x: J) => <p key={x.source_id} className="muted wrap">제안: {x.file} · {x.sheet} · {x.column}열 "{x.header}" — {x.reason}
        <button className="button secondary" onClick={() => { setKind('SOURCE_CELL'); setLoc({ ...loc, file_id: String(x.file_id), sheet: x.sheet }) }}>이 위치로 답하기</button></p>)}
      {sug && !sug.candidates?.length && <p className="muted">AI가 찾은 위치가 없습니다 ({sug.status}). 값을 직접 알려주세요.</p>}
      <p className="row-gap wrap"><select className="input" aria-label="답변 유형" value={kind} onChange={e => setKind(e.target.value)}>
        <option value="USER_ENTERED">숫자 직접 입력</option><option value="SOURCE_CELL">원본 셀 위치</option></select>
        {kind === 'USER_ENTERED' ? <><input className="input" aria-label="답변 값" placeholder="값" value={value} onChange={e => setValue(e.target.value)}/>
          <input className="input" aria-label="답변 단위" value={unit} onChange={e => setUnit(e.target.value)}/></>
          : <><input className="input" aria-label="파일 ID" placeholder="파일 ID" value={loc.file_id} onChange={e => setLoc({ ...loc, file_id: e.target.value })}/>
            <input className="input" aria-label="시트" placeholder="시트" value={loc.sheet} onChange={e => setLoc({ ...loc, sheet: e.target.value })}/>
            <input className="input" aria-label="셀" placeholder="셀 (예: B2)" value={loc.cell} onChange={e => setLoc({ ...loc, cell: e.target.value })}/></>}
        <button className="button secondary" disabled={busy} onClick={send}>답변</button>
        <button className="button primary" disabled={busy || r.status !== 'ANSWERED'} onClick={resume}>확인 후 계산 재개</button></p>
      {(out?.rejected || out?.held_reason || rejected) && <Note>{out?.rejected ?? out?.held_reason ?? rejected?.payload?.reason}</Note>}
    </>}
  </div>
}
