import { useEffect, useRef, useState } from 'react'
import { Badge, Card, Cite, Note, SectionTitle } from '../../components/ui'
import type { Ctx, J, Tone } from '../../types'

// Customer-document intake (spec v5.8 §23) inside the Agent chat. Every value shown comes from the server's draft;
// nothing becomes a case until a person confirms it here.
export const FIELD: Record<string, string> = {
  customer: '고객사', customer_contact: '고객 담당자', customer_ref: '고객 참조번호', part_number: '품번', lot: 'LOT',
  serial_range: '일련번호', issued_date: '문서 발행일', delivery_date: '납품일', found_date: '발견일', phenomenon: '현상',
  found_condition: '발견 조건', inspected_qty: '검사 수량', defective_qty: '불량 수량', qty_unit: '단위', request: '요청사항',
  reply_deadline: '회신 기한', customer_cause_claim: '고객 원인 추정',
}
const STATUS: Record<string, [string, Tone]> = {
  FOUND: ['원문 확인', 'green'], CONFLICT: ['문서 간 충돌', 'red'], NEEDS_CONFIRMATION: ['확인 필요', 'amber'],
  UNVERIFIED: ['근거 불일치', 'amber'], MISSING: ['미확인', 'slate'], USER_SET: ['사람 입력', 'blue'],
}
const MODE: Record<string, Tone> = { OK: 'green', PARTIAL: 'amber', FAILED: 'red', OFFLINE: 'slate', EDITED: 'blue' }

export const toBase64 = (f: File) => new Promise<string>((ok, bad) => {
  const r = new FileReader()
  r.onload = () => ok(String(r.result).split(',')[1] ?? '')
  r.onerror = () => bad(r.error)
  r.readAsDataURL(f)
})

const where = (s: J) => `${s.element_id}${s.page ? ` (p.${s.page})` : ''}`

export function IntakePanel({ ctx }: { ctx: Ctx }) {
  const [intakes, setIntakes] = useState<J[]>([])
  const [busy, setBusy] = useState('')
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => { ctx.api('/intakes').then((xs: J) => setIntakes(Array.isArray(xs) ? xs.filter(x => x?.intake_id) : [])).catch(() => setIntakes([])) }, [ctx.api, ctx.tick]) // eslint-disable-line react-hooks/exhaustive-deps

  const attach = async (list: FileList | null) => {
    if (!list?.length || busy) return
    setBusy(`업로드 중: ${[...list].map(f => f.name).join(', ')}`)
    try {
      const files = await Promise.all([...list].map(async f => ({ name: f.name, content_base64: await toBase64(f) })))
      const it = await ctx.api('/intakes', 'POST', { files }, true)
      setIntakes(xs => [it, ...xs])
    } catch { /* the shell's error bar shows the server's reason (size, type, macro, ...) */ } finally {
      setBusy(''); if (input.current) input.current.value = ''
    }
  }
  return <Card className="intake">
    <SectionTitle title="고객 문서 접수 (PDF · DOCX)" sub="사건을 고르지 않아도 첨부할 수 있습니다. 업로드·분석만으로는 사건이 만들어지지 않습니다."
      action={<label className="button secondary">{busy ? '처리 중…' : '문서 첨부'}<input ref={input} type="file" hidden multiple accept=".pdf,.docx"
        aria-label="고객 문서 첨부" disabled={!!busy} onChange={e => attach(e.target.files)}/></label>}/>
    {busy && <p className="muted">{busy}</p>}
    {intakes.slice(0, 3).map(i => <IntakeCard key={i.intake_id} ctx={ctx} intake={i}/>)}
  </Card>
}

export function IntakeCard({ ctx, intake }: { ctx: Ctx; intake: J }) {
  const [view, setView] = useState<J>(null)
  const [busy, setBusy] = useState(false)
  const [edits, setEdits] = useState<Record<string, { value: string; reason: string; element_id?: string; excerpt?: string }>>({})
  const [target, setTarget] = useState('NEW')
  const [cases, setCases] = useState<J[]>([])
  const [linked, setLinked] = useState<J>(null)
  const id = intake.intake_id
  useEffect(() => { ctx.api(`/intakes/${id}/draft`).then((v: J) => setView(v?.intake_id ? v : null)).catch(() => setView(null)) }, [id, ctx.api, ctx.tick]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { ctx.api('/cases').then((cs: J) => setCases(Array.isArray(cs) ? cs.filter(c => c?.case_id) : [])).catch(() => setCases([])) }, [ctx.api]) // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (call: () => Promise<J>) => {
    if (busy) return
    setBusy(true)
    try { return await call() } catch { return null } finally { setBusy(false) }
  }
  const analyze = () => run(async () => setView(await ctx.api(`/intakes/${id}/analyze`, 'POST', undefined, true)))
  const d = view?.draft
  const saveEdits = () => run(async () => {
    const changes = Object.entries(edits).filter(([, e]) => e.reason.trim()).map(([field, e]) => ({ field, ...e, value: e.value || null }))
    if (!changes.length) return
    setView(await ctx.api(`/intakes/${id}/draft/edits`, 'POST', { base_version: d.version, changes }, true)); setEdits({})
  })
  const confirm = () => run(async () => {
    const body = target === 'NEW' ? { base_version: d.version, action: 'NEW_CASE' } : { base_version: d.version, action: 'LINK_EXISTING', case_id: target }
    const out = await ctx.api(`/intakes/${id}/confirm`, 'POST', body, true)
    setLinked(out); ctx.refresh()
  })
  const pick = (field: string, c: J) => setEdits(e => ({ ...e, [field]: { value: c.value, reason: e[field]?.reason ?? '', element_id: c.sources[0]?.element_id, excerpt: c.sources[0]?.excerpt } }))
  const known = Object.values(d?.fields ?? {}).some((v: J) => v.value && ['FOUND', 'USER_SET'].includes(v.status))
  const open = Object.entries(d?.fields ?? {}).filter(([, v]: [string, J]) => ['CONFLICT', 'NEEDS_CONFIRMATION'].includes(v.status)).map(([k]) => FIELD[k] ?? k)

  return <div className="intake-card">
    <div className="row-gap"><b>접수 #{id}</b>{(view?.files ?? intake.files ?? []).map((f: J) => <span key={f.file_id}><Badge tone={f.data_origin === 'SYNTHETIC' ? 'teal' : 'slate'}>{f.name} · {f.data_origin}</Badge></span>)}</div>
    {view?.files?.map((f: J) => f.coverage && <p key={f.file_id} className="muted wrap">{f.name}: 본문 {f.coverage.text} · 표 {f.coverage.tables} · 이미지 {f.coverage.images} · 차트 {f.coverage.charts} · 스캔 {f.coverage.scan} · 렌더 {f.coverage.render}
      {f.coverage.tables_note && ` (${f.coverage.tables_note})`}{f.coverage.render_note && ` (${f.coverage.render_note})`}{f.checks?.active_content?.length > 0 && ` · 활성 콘텐츠 표시됨(실행 안 함)`}{f.checks?.external_links > 0 && ` · 외부 링크 ${f.checks.external_links}개(따라가지 않음)`}</p>)}
    {!d ? <button className="button primary" disabled={busy} onClick={analyze}>{busy ? '분석 중…' : '문서 분석'}</button> : <>
      <p className="row-gap"><Badge tone={MODE[d.status] ?? 'slate'}>{d.status}</Badge><span className="muted">v{d.version} · {d.mode}{d.model ? ` · ${d.model}` : ''}{d.prompt_version ? ` · prompt ${d.prompt_version}` : ''}</span>
        {d.mode === 'TEST_DOUBLE' && <Badge tone="amber">TEST_DOUBLE (Meta 아님)</Badge>}</p>
      {d.error && <Note>{d.error}</Note>}
      {d.withheld?.length > 0 && <Note>외부 전송 승인 안 된 파일은 모델에 보내지 않았습니다: {d.withheld.map((w: J) => w.name).join(', ')}</Note>}
      {d.documents?.length > 0 && <p className="muted">문서 분류: {d.documents.map((x: J) => `#${x.file_id} ${x.classes.join('+')}${x.needs_confirmation ? ' (확인 필요)' : ''}`).join(' · ')}</p>}
      <div className="table-wrap"><table><thead><tr><th>항목</th><th>상태</th><th>값</th><th>원문 위치 · 발췌</th><th>수정 (사유 필수)</th></tr></thead><tbody>
        {Object.entries(d.fields).map(([k, v]: [string, J]) => <tr key={k}><td>{FIELD[k] ?? k}{v.kind === 'HYPOTHESIS' && <> <Badge tone="violet">가설</Badge></>}</td>
          <td><Badge tone={STATUS[v.status]?.[1] ?? 'slate'}>{STATUS[v.status]?.[0] ?? v.status}</Badge></td>
          <td className="wrap">{v.value ?? '-'}{v.candidates?.map((c: J, n: number) => <div key={n}><button className="citation" onClick={() => pick(k, c)}>{c.value} 선택</button> <span className="muted">{c.sources.map(where).join(', ')}</span></div>)}</td>
          <td className="wrap">{v.sources?.map((s: J, n: number) => <div key={n}><Cite ids={[where(s)]}/> <span className="muted">"{s.excerpt}"</span></div>)}{v.edit && <span className="muted">{v.edit.by}: {v.edit.reason} ({v.edit.source_check})</span>}{v.rejected?.length > 0 && <span className="muted">제외: {v.rejected[0].problems.join('; ')}</span>}</td>
          <td><input aria-label={`${FIELD[k] ?? k} 값`} value={edits[k]?.value ?? ''} placeholder="새 값" onChange={e => setEdits(x => ({ ...x, [k]: { ...x[k], reason: x[k]?.reason ?? '', value: e.target.value } }))}/>
            <input aria-label={`${FIELD[k] ?? k} 수정 사유`} value={edits[k]?.reason ?? ''} placeholder="사유" onChange={e => setEdits(x => ({ ...x, [k]: { ...x[k], value: x[k]?.value ?? '', reason: e.target.value } }))}/></td></tr>)}
      </tbody></table></div>
      {Object.keys(edits).length > 0 && <button className="button secondary" disabled={busy} onClick={saveEdits}>수정 저장 (새 버전)</button>}
      {d.notes?.map((n: string) => <Note key={n}>{n}</Note>)}
      {d.flags?.map((x: J) => <Note key={x.element_id}>{x.element_id}: {x.note}</Note>)}
      {d.questions?.length > 0 && <div><b>확인이 필요한 질문</b>{d.questions.map((q: string) => <p key={q} className="wrap">· {q}</p>)}</div>}
      {d.links?.length > 0 && <div><b>그림·차트 맥락 (AI 해석, 결함 판정 아님)</b>{d.links.map((l: J, n: number) => <p key={n} className="muted wrap">{l.element_id}: {l.text}{l.ambiguous ? ' (모호)' : ''} <Cite ids={l.related_element_ids}/></p>)}</div>}
      {linked ? <Card className="handoff"><b>사건 {linked.case_id} {linked.intakes?.length ? '연결됨' : ''}</b>
        <p className="muted">출처 {linked.origin} · 채널 {linked.channel} · 책임자 {linked.owner_id ?? '미지정'} · D0 {linked.d0 === 'DONE' ? '완료' : '판정 대기'} · 배정 {linked.assignees.join(', ')}</p>
        {!linked.internal_data.linked && <Note>{linked.internal_data.note}</Note>}
        <button className="button primary" onClick={() => ctx.open(linked.case_id, '', 'eightd')}>D0 판정으로 이동</button></Card>
        : <div className="row-gap"><select aria-label="접수 대상" value={target} onChange={e => setTarget(e.target.value)}><option value="NEW">새 사건 생성</option>{cases.map(c => <option key={c.case_id} value={c.case_id}>기존 사건 {c.case_id}에 연결</option>)}</select>
          <button className="button primary" disabled={busy || open.length > 0 || (target === 'NEW' && !known)} onClick={confirm}>확인하고 {target === 'NEW' ? '사건 생성' : '연결'}</button>
          {open.length > 0 && <span className="muted">먼저 확인: {open.join(', ')}</span>}
          {target === 'NEW' && !known && <span className="muted">확인된 값이 없습니다: 원문을 보고 값을 입력하세요</span>}</div>}
    </>}
  </div>
}
