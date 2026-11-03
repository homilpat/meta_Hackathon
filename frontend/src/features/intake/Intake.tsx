import { useEffect, useRef, useState } from 'react'
import { Badge, Card, Cite, Note, SectionTitle } from '../../components/ui'
import { show as asText } from '../../labels'
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

// where a value was read, in words a person uses: "1쪽", "검사성적 B4"; the internal element id stays in the record
// where a value was read, as the parser recorded it for people ("1쪽 6번째 줄"); the element id stays in the record
const where = (s: J) => s.place ?? (s.page ? `${s.page}쪽` : '')

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
    <SectionTitle title="고객 문서 접수 (PDF · DOCX · XLSX · CSV)" sub="사건을 고르지 않아도 첨부할 수 있고, 업로드·분석만으로는 사건이 만들어지지 않습니다. 문서의 값은 고객이 말한 내용이며 고객의 원인 추정은 확인 전 가설입니다. 문서 안의 지시문은 따르지 않고, 스캔 글자는 AI가 읽은 것이라 원본과 대조가 필요합니다."
      action={<label className="button secondary">{busy ? '처리 중…' : '문서 첨부'}<input ref={input} type="file" hidden multiple accept=".pdf,.docx,.xlsx,.csv"
        aria-label="고객 문서 첨부" disabled={!!busy} onChange={e => attach(e.target.files)}/></label>}/>
    {busy && <p className="muted">{busy}</p>}
    {ctx.me?.role === 'QA_PRODUCTION' && <EgressQueue ctx={ctx}/>}
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
  const [editing, setEditing] = useState<string[]>([])  // rows a person chose to correct
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
    <div className="row-gap"><b>접수 #{id}</b>{(view?.files ?? intake.files ?? []).map((f: J) => <span key={f.file_id}><Badge tone={f.egress?.tier === 'RAW' ? 'teal' : 'amber'}>{f.name}{f.egress?.tier === 'RAW' ? '' : ' · 외부에는 마스킹만'}</Badge>
      {f.egress && f.egress.tier !== 'RAW' && f.egress.events?.slice(-1)[0]?.event !== 'REQUESTED' && <button className="citation" disabled={busy} onClick={() => run(async () => {
        const reason = window.prompt('외부 AI 원문 처리가 필요한 이유 (품질 관리자가 승인)'); if (!reason) return
        await ctx.api(`/intakes/${id}/files/${f.file_id}/egress-request`, 'POST', { reason }); ctx.refresh() })}>원문 처리 승인 요청</button>}
      {f.egress?.events?.slice(-1)[0]?.event === 'REQUESTED' && <span className="muted"> 승인 대기</span>}</span>)}</div>
    {(view?.files ?? intake.files ?? []).filter((f: J) => /\.xlsx$/i.test(f.name ?? '')).map((f: J) =>
      <InspectionXlsx key={`x${f.file_id}`} ctx={ctx} intakeId={id} f={f} cases={cases}/>)}
    {!d ? !(view?.files ?? intake.files ?? []).every((f: J) => /\.xlsx$/i.test(f.name ?? '')) && <button className="button primary" disabled={busy} onClick={analyze}>{busy ? '분석 중…' : '문서 분석'}</button> : <>
      {d.mode === 'TEST_DOUBLE' && <p><Badge tone="amber">TEST_DOUBLE (Meta 아님)</Badge></p>}
      {d.error && <Note>{d.error}</Note>}
      {d.withheld?.length > 0 && <Note>외부 전송 승인 안 된 파일은 모델에 보내지 않았습니다: {d.withheld.map((w: J) => w.name).join(', ')}</Note>}
      {d.egress?.unread?.elements > 0 && <Note>문서 일부만 읽었습니다 ({d.egress.unread.of - d.egress.unread.elements}/{d.egress.unread.of} 요소).{d.egress.unread.missing?.length > 0 && ` 찾지 못한 항목: ${d.egress.unread.missing.map((k: string) => FIELD[k] ?? k).join(', ')}.`} <button className="citation" disabled={busy} onClick={() => run(async () => setView(await ctx.api(`/intakes/${id}/analyze?read=WHOLE`, 'POST', undefined, true)))}>전체 읽기로 다시 분석</button></Note>}
      {d.egress?.files?.filter((x: J) => x.not_sent_from).map((x: J) => <Note key={x.file_id}>{x.name}: 비용 한도로 {x.not_sent_from}부터 {x.not_sent}개 요소는 모델에 보내지 않았습니다 (원문 위치로 직접 확인)</Note>)}
      <div className="table-wrap"><table><thead><tr><th>항목</th><th>상태</th><th>값</th><th>원문</th><th>수정</th></tr></thead><tbody>
        {Object.entries(d.fields).map(([k, v]: [string, J]) => <tr key={k}><td>{FIELD[k] ?? k}{v.kind === 'HYPOTHESIS' && <> <Badge tone="violet">가설</Badge></>}</td>
          <td><Badge tone={STATUS[v.status]?.[1] ?? 'slate'}>{STATUS[v.status]?.[0] ?? v.status}</Badge></td>
          <td className="wrap"><span data-no-ko>{v.value ?? '-'}</span>{v.candidates?.map((c: J, n: number) => <div key={n}><button className="citation" onClick={() => pick(k, c)}>{c.value} 선택</button> <span className="muted">{c.sources.map(where).filter(Boolean).join(', ')}</span></div>)}</td>
          <td className="wrap">{v.sources?.map((s: J, n: number) => <div key={n}><span className="muted" data-no-ko>"{s.excerpt}"</span>{where(s) && <span className="muted"> ({where(s)})</span>}</div>)}{v.edit && <span className="muted">{v.edit.by}: {v.edit.reason} ({v.edit.source_check})</span>}{v.rejected?.length > 0 && <span className="muted">제외: {v.rejected[0].problems.join('; ')}</span>}</td>
          <td>{!['CONFLICT', 'NEEDS_CONFIRMATION'].includes(v.status) && !editing.includes(k) && !edits[k]
            ? <button className="citation" onClick={() => setEditing(x => [...x, k])}>수정</button> : <>
            <input aria-label={`${FIELD[k] ?? k} 값`} value={edits[k]?.value ?? ''} placeholder="새 값" onChange={e => setEdits(x => ({ ...x, [k]: { ...x[k], reason: x[k]?.reason ?? '', value: e.target.value } }))}/>
            <input aria-label={`${FIELD[k] ?? k} 수정 사유`} value={edits[k]?.reason ?? ''} placeholder="사유" onChange={e => setEdits(x => ({ ...x, [k]: { ...x[k], value: x[k]?.value ?? '', reason: e.target.value } }))}/></>}</td></tr>)}
      </tbody></table></div>
      {Object.keys(edits).length > 0 && <button className="button secondary" disabled={busy} onClick={saveEdits}>수정 저장 (새 버전)</button>}
      {d.links?.length > 0 && <div><b>그림·차트 설명 (AI가 본 내용, 불량 판정 아님)</b>{d.links.map((l: J, n: number) => <p key={n} className="muted wrap">{l.place ? `${l.place}: ` : ''}{l.text}{l.ambiguous ? ' (불확실)' : ''}</p>)}</div>}
      {d.questions?.length > 0 && <div><b>확인이 필요한 질문</b>{d.questions.map((q: string) => <p key={q} className="wrap">· {q}</p>)}</div>}
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

// The quality manager's list of files waiting for an external-processing decision (who asked, why).
// Inspection-result XLSX (spec §28): the server suggests and checks; a person confirms columns and rows.
const XFIELD: Record<string, string> = { part_number: '품번', lot: 'LOT', inspected_on: '검사일', inspected_qty: '검사 수량', defective_qty: '불량 수량', item: '측정 항목', value: '측정값', unit: '단위' }
const LEVEL: Record<string, Tone> = { BLOCK: 'red', WARN: 'amber', INFO: 'slate' }
// §29: how the file was read — a mapping confirmed for this structure, a registered form, or an AI proposal to review
const ROUTE: Record<string, [string, Tone]> = { REUSED: ['저장된 매핑 재사용', 'green'], FORM: ['등록 양식', 'blue'], NEEDS_AI: ['AI 제안·검토 필요', 'amber'] }
const RECON: Record<string, Tone> = { MATCH: 'green', MISMATCH: 'red', MISSING: 'amber', AMBIGUOUS: 'amber', NOT_COMPARABLE: 'slate' }

function InspectionXlsx({ ctx, intakeId, f, cases }: { ctx: Ctx; intakeId: number; f: J; cases: J[] }) {
  const [v, setV] = useState<J>(null)
  const [inc, setInc] = useState<Record<number, boolean>>({})
  const [why, setWhy] = useState<Record<number, string>>({})
  const [caseId, setCaseId] = useState('')
  const [imp, setImp] = useState<J>(null)
  const [rec, setRec] = useState<J>(null)
  const [cmp, setCmp] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [prop, setProp] = useState<J>(null)
  const [conf, setConf] = useState<string[]>([])
  const [mapWhy, setMapWhy] = useState('')
  const go = async (call: () => Promise<void>) => { if (busy) return; setBusy(true); try { await call() } catch { /* the error bar shows the server's reason */ } finally { setBusy(false) } }
  const reviewing = v?.layout?.route === 'NEEDS_AI'
  const load = (mapping?: J, form?: string, table?: string) => go(async () => {
    const params = new URLSearchParams()
    if (mapping) params.set('mapping', JSON.stringify(mapping))
    const t = table ?? (reviewing && !form ? v.layout.table : undefined)
    if (t) params.set('table', t)
    else if (form ?? v?.form?.name) params.set('form', (form ?? v?.form?.name) as string)
    const q = params.toString() ? `?${params}` : ''
    show(await ctx.api(`/intakes/${intakeId}/files/${f.file_id}/inspection${q}`))
  })
  const show = (out: J) => {
    setV(out)
    setInc(Object.fromEntries(out.rows.map((x: J) => [x.row, !x.hidden && !x.issues.some((i: J) => i.level === 'BLOCK')])))
  }
  const ask = () => go(async () => {
    const out: J = await ctx.api(`/intakes/${intakeId}/files/${f.file_id}/inspection/proposals`, 'POST', {})
    setProp(out); setConf([]); show(out.preview)
  })
  const keep = () => go(async () => {
    const saved: J = await ctx.api(`/intakes/${intakeId}/files/${f.file_id}/inspection/mapping`, 'POST', {
      table: v.layout.table, mapping: v.mapping, confirmed: conf, proposal_id: prop?.proposal_id ?? null, reason: mapWhy }, true)
    setProp(null); setMapWhy('')
    show(await ctx.api(`/intakes/${intakeId}/files/${f.file_id}/inspection?form=${encodeURIComponent(saved.name)}`))
  })
  const reconcile = (id: number, fields: string[]) => go(async () => setRec(await ctx.api(`/cases/${caseId}/inspection-imports/${id}/reconciliation?comparable=${fields.join(',')}`)))
  const save = () => go(async () => {
    const include = v.rows.filter((x: J) => inc[x.row]).map((x: J) => x.row)
    const exclude = Object.fromEntries(v.rows.filter((x: J) => !inc[x.row]).map((x: J) => [String(x.row), why[x.row] ?? '']))
    const out: J = await ctx.api(`/cases/${caseId}/inspection-imports`, 'POST', { intake_id: intakeId, file_id: f.file_id, file_sha256: v.file_sha256,
      sheet: v.sheet, header_row: v.header_row, mapping: v.mapping, include_rows: include, exclude, form: v.form?.name ?? null }, true)
    setImp(out); ctx.refresh()
    setRec(await ctx.api(`/cases/${caseId}/inspection-imports/${out.import_id}/reconciliation`))
  })
  const unexplained = v?.rows.some((x: J) => !inc[x.row] && !(why[x.row] ?? '').trim())
  if (!v) return <p><button className="button secondary" disabled={busy} onClick={() => load()}>{f.name}: 검사 결과로 읽기</button></p>
  return <Card><SectionTitle title={`검사 결과 확인 · ${f.name}`} sub={`시트 ${v.sheet} · 헤더 ${v.header_row ?? '없음'}행 · 열 연결 규칙 ${v.mapping_version ?? '-'} · 추천은 제안이며 사람이 확인해야 연결됩니다`}/>
    {v.form && <p className="row-gap"><span className="muted">양식</span><select className="input" aria-label="검사 양식" value={v.form.name} disabled={busy} onChange={e => load(undefined, e.target.value)}>{(v.form.candidates ?? [v.form.name]).map((n: string) => <option key={n} value={n}>{n}</option>)}</select><span className="muted">v{v.form.version}{v.form.builtin ? ' · 기본 합성 양식' : ' · 등록 양식'}</span></p>}
    {v.layout && <p className="row-gap wrap"><Badge tone={ROUTE[v.layout.route]?.[1] ?? 'slate'}>{ROUTE[v.layout.route]?.[0] ?? v.layout.route}</Badge>
      {v.layout.reasons.map((r: J) => <span key={r.code + r.message} className="muted">{r.message}</span>)}</p>}
    {reviewing && <p className="row-gap wrap">
      {v.layout.tables.length > 1 && <select className="input" aria-label="표 후보" value={v.layout.table ?? ''} disabled={busy} onChange={e => load(undefined, undefined, e.target.value)}>
        <option value="">표 후보 선택</option>{v.layout.tables.map((t: J) => <option key={t.id} value={t.id}>{t.id} · {t.range}{t.header_rows.length > 1 ? ' · 다단 헤더' : ''}</option>)}</select>}
      <button className="button secondary" disabled={busy || !v.layout.tables.length} onClick={ask}>AI 열 연결 제안 받기</button>
      <span className="muted">헤더와 열 형식만 보냅니다 (셀 값은 보내지 않음). 제안은 서버가 검사하고 사람이 확인합니다.</span></p>}
    {prop && <div className="wrap"><p className="row-gap"><Badge tone={prop.status === 'OK' ? 'blue' : 'red'}>AI 제안 {prop.status}</Badge><span className="muted">{prop.mode} · {prop.model ?? '모델 없음'} · 제안 #{prop.proposal_id}</span></p>
      {prop.issues.map((i: J, n: number) => <Note key={n}>{i.message}</Note>)}
      {prop.proposal && Object.entries(prop.proposal.reasons).filter(([k]) => prop.proposal.mapping[k]).map(([k, why]) => <p key={k} className="muted">{XFIELD[k] ?? k} ← {prop.proposal.mapping[k]}열: {String(why)}</p>)}</div>}
    {reviewing && v.layout.uncertain?.map((u: J) => <div key={u.field} className="intake-card">
      <p className="row-gap wrap"><Badge tone="amber">확인 필요</Badge><b>{XFIELD[u.field] ?? u.field}</b> ← {u.column ? `${u.column}열 "${u.header}"` : '(미연결)'} · {u.why}</p>
      <table><thead><tr>{u.context.map((x: J) => <th key={x.column} className={x.column === u.column ? 'mark' : ''}>{x.column}: {x.header}</th>)}</tr></thead>
        <tbody>{(u.context[0]?.cells ?? []).map((_: J, n: number) => <tr key={n}>{u.context.map((x: J) => <td key={x.column}>{x.cells[n]?.cell} = {String(x.cells[n]?.raw ?? '')}</td>)}</tr>)}</tbody></table>
      <label className="row-gap"><input type="checkbox" aria-label={`${XFIELD[u.field] ?? u.field} 연결 확인`} checked={conf.includes(u.field)} onChange={e => setConf(e.target.checked ? [...conf, u.field] : conf.filter(x => x !== u.field))}/> 원본 셀을 보고 이 연결이 맞다고 확인함</label></div>)}
    {v.issues.map((i: J) => <Note key={i.code}>{i.message}</Note>)}
    <div className="row-gap wrap">{Object.keys(XFIELD).map(k => <label key={k} className="muted">{XFIELD[k]}{['lot', 'inspected_qty', 'defective_qty'].includes(k) ? ' *' : ''}
      <select className="input" aria-label={`${XFIELD[k]} 열`} value={v.mapping[k] ?? ''} disabled={busy} onChange={e => load({ ...v.mapping, [k]: e.target.value || null })}>
        <option value="">(연결 안 함)</option>{Object.entries(v.columns).map(([col, h]) => <option key={col} value={col}>{col}: {String(h)}</option>)}</select></label>)}</div>
    <table className="mt"><thead><tr><th>포함</th><th>행</th>{Object.keys(XFIELD).filter(k => v.mapping[k]).map(k => <th key={k}>{XFIELD[k]}</th>)}<th>확인 필요</th></tr></thead><tbody>
      {v.rows.map((x: J) => <tr key={x.row}><td><input type="checkbox" aria-label={`${x.row}행 포함`} checked={!!inc[x.row]} disabled={busy || x.issues.some((i: J) => i.level === 'BLOCK')} onChange={e => setInc({ ...inc, [x.row]: e.target.checked })}/></td>
        <td>{x.row}{x.hidden ? ' (숨김)' : ''}</td>
        {Object.keys(XFIELD).filter(k => v.mapping[k]).map(k => <td key={k} title={`${x.cells[k]?.cell} 원본 ${asText(x.cells[k]?.raw)} · 형식 ${x.cells[k]?.format}`}>{x.values[k] ?? <span className="muted">-</span>}</td>)}
        <td>{x.issues.map((i: J, n: number) => <div key={n}><Badge tone={LEVEL[i.level]}>{i.level}</Badge> <span className="muted">{i.cell} {i.message}</span></div>)}
          {!inc[x.row] && <input className="input" aria-label={`${x.row}행 제외 사유`} placeholder="제외 사유 (필수)" value={why[x.row] ?? ''} onChange={e => setWhy({ ...why, [x.row]: e.target.value })}/>}</td></tr>)}
    </tbody></table>
    {reviewing && v.layout.table && <p className="row-gap wrap">
      <input className="input" aria-label="열 연결 확인 사유" placeholder="확인 사유 (필수)" value={mapWhy} onChange={e => setMapWhy(e.target.value)}/>
      <button className="button primary" disabled={busy || !mapWhy.trim() || (v.layout.uncertain ?? []).some((u: J) => !conf.includes(u.field))} onClick={keep}>확인한 열 연결 저장 (같은 구조 파일에 재사용)</button></p>}
    {v.stopped_at_row && <Note>처리 시간 상한으로 {v.stopped_at_row}행부터 읽지 않았습니다. 전체를 읽은 것으로 표시하지 않습니다.</Note>}
    <div className="row-gap mt"><select className="input" aria-label="연결할 사건" value={caseId} onChange={e => setCaseId(e.target.value)}><option value="">연결할 사건 선택</option>{cases.map(c => <option key={c.case_id} value={c.case_id}>{c.case_id}</option>)}</select>
      <button className="button primary" disabled={busy || !caseId || unexplained || reviewing} onClick={save}>확인한 열·행으로 사건에 연결</button>
      {unexplained && <span className="muted">제외한 행마다 사유가 필요합니다 (분모를 남기기 위해)</span>}
      {reviewing && <span className="muted">열 연결을 확인·저장한 뒤 사건에 연결할 수 있습니다</span>}</div>
    {imp && <p className="muted">연결됨: 가져오기 #{imp.import_id} v{imp.version} · 포함 {imp.denominator.included}행 · 제외 {imp.denominator.excluded}행 · 근거 {imp.evidence_ids.length}건</p>}
    {rec && <><SectionTitle title="고객 문서 대조" sub="같은 의미·범위라고 확인한 수량만 비교합니다. 고객 수량은 내부 검사 사실로 바뀌지 않습니다."/>
      <div className="row-gap">{['inspected_qty', 'defective_qty'].map(k => <label key={k}><input type="checkbox" checked={cmp.includes(k)} onChange={e => { const next = e.target.checked ? [...cmp, k] : cmp.filter(x => x !== k); setCmp(next); reconcile(imp.import_id, next) }}/> {XFIELD[k]}: 같은 의미·검사 범위 확인</label>)}</div>
      {rec.items.map((i: J, n: number) => <p key={n} className="wrap"><Badge tone={RECON[i.status]}>{i.status}</Badge> {XFIELD[i.field] ?? i.field}{i.lot ? ` (LOT ${i.lot})` : ''}: 고객 {i.customer.map((c: J) => `${c.value} [${c.file ?? ''} ${c.element_id ?? ''}]`).join(', ') || '-'} · 검사 {i.inspection_value ?? i.inspection.map((x: J) => `${x.sheet}!${x.row}`).join(', ') ?? '-'}{i.reason ? ` · ${i.reason}` : ''}{i.calculation_id ? ` · 서버 합계 ${i.calculation_id}` : ''}</p>)}</>}
  </Card>
}

function EgressQueue({ ctx }: { ctx: Ctx }) {
  const [items, setItems] = useState<J[]>([])
  const [reason, setReason] = useState('')
  useEffect(() => { ctx.api('/egress-approvals').then((xs: J) => setItems(Array.isArray(xs) ? xs : [])).catch(() => setItems([])) }, [ctx.api, ctx.tick]) // eslint-disable-line react-hooks/exhaustive-deps
  const decide = async (fid: number, decision: string) => { try { await ctx.api(`/egress-approvals/${fid}`, 'POST', { decision, reason }); ctx.refresh() } catch { /* error bar */ } }
  if (!items.length) return null
  return <div className="intake-card"><b>외부 AI 원문 처리 승인 대기</b>
    <input aria-label="승인 사유" placeholder="판단 사유 (필수)" value={reason} onChange={e => setReason(e.target.value)}/>
    {items.map(x => <p key={x.file_id} className="row-gap wrap">{x.name} · 요청 {x.requested_by}: {x.reason}
      <button className="button primary" disabled={!reason.trim()} onClick={() => decide(x.file_id, 'APPROVED')}>승인</button>
      <button className="button secondary" disabled={!reason.trim()} onClick={() => decide(x.file_id, 'REJECTED')}>거절</button></p>)}</div>
}
