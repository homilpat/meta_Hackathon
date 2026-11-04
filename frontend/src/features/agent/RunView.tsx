import { useState } from 'react'
import { STATUS_TONE } from '../../constants'
import { Badge, Card, Cite, Icon, SectionTitle } from '../../components/ui'
import { ExportButtons } from '../../components/ExportButtons'
import { ControlChart } from '../spc/Spc'
import { TASK } from '../queue/Queue'
import { say, show, words } from '../../labels'
import type { Ctx, J, Tone } from '../../types'

// Renders one persisted AgentRun exactly as the server returned it. Nothing here decides or claims a state.
export const RUN_TONE: Record<string, Tone> = {
  PLANNED: 'slate', RUNNING: 'blue', NEEDS_HUMAN: 'amber', BLOCKED: 'red', FAILED: 'red', COMPLETED: 'green', PARTIAL: 'amber', CANCELLED: 'slate',
}
export const RUN_LABEL: Record<string, string> = {
  PLANNED: '계획됨', RUNNING: '실행 중', NEEDS_HUMAN: '사람 확인 필요', BLOCKED: '차단됨', FAILED: '실패', COMPLETED: '완료', PARTIAL: '부분 완료', CANCELLED: '취소됨',
}
const ITEM: Record<string, [string, Tone]> = {
  PENDING: ['대기', 'slate'], RUNNING: ['실행 중', 'blue'], DONE: ['완료', 'green'], ERROR: ['오류', 'red'], DENIED: ['거부됨', 'red'],
  NEEDS_HUMAN: ['사람 확인 필요', 'amber'], BLOCKED: ['차단됨', 'red'], FAILED: ['실패', 'red'], SKIPPED: ['건너뜀', 'slate'],
}

function PlanCard({ run }: { run: J }) {
  const plan: J[] = run.plan ?? []
  const done = plan.filter(i => i.status === 'DONE').length
  const [sel, setSel] = useState<number | null>(null)
  return <Card className="plan-card"><SectionTitle title="실행 계획" sub={`${plan.length}개 작업`} action={<b className="progress-text">{done} / {plan.length}</b>}/>
    <div className="plan-progress" role="progressbar" aria-valuemin={0} aria-valuemax={plan.length} aria-valuenow={done}><i style={{ width: `${plan.length ? done / plan.length * 100 : 0}%` }}/></div>
    {plan.map((p, i) => <button key={i} className={`plan-row ${sel === i ? 'selected' : ''}`} aria-expanded={sel === i} onClick={() => setSel(sel === i ? null : i)}>
      <span className={`step-status ${ITEM[p.status]?.[1] ?? 'slate'}`}>{p.status === 'DONE' ? <Icon name="check" size={13}/> : i + 1}</span>
      <span className="plan-text"><b>{p.title}</b>{sel === i && p.note && <small>{p.note}</small>}</span>
      <Badge tone={ITEM[p.status]?.[1]}>{ITEM[p.status]?.[0] ?? p.status}</Badge></button>)}
  </Card>
}

function StepBody({ s, ctx }: { s: J; ctx: Ctx }) {
  const r = s.result
  switch (s.tool) {
    case 'case_summary': return <div className="table-wrap"><table><thead><tr><th>LOT</th><th>스텐실</th><th>AOI</th><th>FAIL</th><th>미해소</th></tr></thead><tbody>
      {r.lots.map((l: J) => <tr key={l.lot}><td><b className="id">{l.lot}</b></td><td>{l.stencil}</td><td>{l.aoi}</td><td>{l.fail}</td><td>{l.not_cleared}</td></tr>)}
    </tbody></table>{r.aoi_fail.length > 0 && <p className="muted wrap">AOI 불합격 {r.aoi_fail.length}건 · {r.aoi_fail.slice(0, 5).map((f: J) => `${f.board}${f.human ? ` (${say(f.human[0])})` : ''}`).join(', ')}{r.aoi_fail.length > 5 ? ' 외' : ''}</p>}</div>
    case 'data_integrity': return <><div className="row-gap">{Object.entries(r.issue_counts as Record<string, number>).map(([k, n]) => <Badge key={k} tone="amber">{`${say(k)} ${n}`}</Badge>)}</div>
      {r.issues.slice(0, 4).map((i: J, n: number) => <p key={n} className="muted wrap">{words(i.detail)}</p>)}
      {!r.issues.length && <span className="muted">기록된 데이터 품질 이슈 없음</span>}</>
    case 'spc': return r.points ? <><ControlChart m={r}/>{r.first_alarm && <Badge tone="red">첫 경보 {r.first_alarm.lot} {r.first_alarm.panel}/{r.first_alarm.board} · {r.first_alarm.rules.join(', ')}</Badge>}</> : null
    case 'predictions': return <>{r.predictions.slice(0, 5).map((p: J) => <p key={p.evidence_id} className="muted">{p.target_key.join('/')} · 위험 점수 {p.risk_score} (기준 {p.threshold}) {p.above_threshold && <Badge tone="amber">기준 초과</Badge>}</p>)}
      {r.top_explanation && <p className="muted wrap">점수에 크게 작용한 값: {Object.entries(r.top_explanation.contributions_log_odds).slice(0, 3).map(([k, v]) => `${k} ${v}`).join(' · ')}</p>}</>
    case 'evidence_gaps': return <>{r.hypotheses.map((h: J) => <p key={h.hypothesis_id} className="wrap"><Badge tone="violet">{`가설 ${h.hypothesis_id} · ${say(h.status)}`}</Badge> {h.text} — <span className="muted">{h.gaps.map(words).join(' · ') || '빠진 근거 없음'}</span></p>)}
      {r.case_unknowns.map((u: J, i: number) => <p key={`u${i}`} className="muted wrap"><Badge tone="slate">알 수 없음</Badge> {typeof u === 'string' ? u : u.text ?? show(u)}</p>)}
      {r.next_checks.map((c: J, i: number) => <p key={`c${i}`} className="muted wrap"><Badge tone="teal">다음 확인</Badge> {words(typeof c === 'string' ? c : c.check ?? show(c))}</p>)}</>
    case 'experience': return <p><Badge tone={r.mode === 'KNOWN' ? 'green' : r.mode === 'ANALOGICAL' ? 'amber' : 'slate'}>{r.mode}</Badge> 추천 {r.recommendations.length}건 · 실패 사례 {r.negative_precedents.length}건</p>
    case 'history': return <p className="muted wrap">{r.precedents.length ? `비슷한 과거 사례 ${r.precedents.length}건: ${r.precedents.map((p: J) => p.historical_case_id).join(', ')}` : '비슷한 과거 사례 없음'}</p>
    case 'references': return <>{r.results.map((d: J) => <p key={d.ref} className="muted wrap"><Badge tone="slate">{d.kind}</Badge> {d.doc_number} rev {d.revision} · {d.title}</p>)}</>
    case 'stages': return <><div className="row-gap">{r.stages.map((x: J) => <Badge key={x.kind} tone={STATUS_TONE[x.status] ?? 'slate'}>{`${x.step} ${x.doc_type} ${x.status ? say(x.status) : '미작성'}${x.approval_open ? '' : ' · 잠금'}`}</Badge>)}</div>
      {r.closure && <p className="muted wrap">D8 종결 {r.closure.ready ? <Badge tone="green">조건 충족</Badge> : <Badge tone="amber">미충족</Badge>} {(r.closure.blocks ?? []).slice(0, 4).map(words).join(' · ')}</p>}
      <button className="citation" onClick={() => ctx.open(ctx.cid, '', 'eightd')}>D0~D8 화면 열기</button></>
    case 'exports': return <>{r.documents.map((d: J) => <div key={d.kind}><Badge tone="green">{`${d.doc_type} v${d.version} 승인됨`}</Badge>
      <ExportButtons user={ctx.me?.id} path={d.path} label={`${d.doc_type} 승인본`}/></div>)}
      {r.report && <ExportButtons user={ctx.me?.id} path={r.report} label="8D 종료 보고서"/>}
      {!r.documents.length && !r.report && <span className="muted">아직 승인된 문서가 없어 내려받을 파일이 없습니다.</span>}</>
    case 'documents': return <>{r.documents.map((d: J) => <p key={d.kind}><Badge tone="teal">{d.doc_type} v{d.version}</Badge> <Badge tone={STATUS_TONE[d.status]}>{d.status}</Badge>
      {d.validation ? <> <Badge tone={d.validation.result === 'BLOCK' ? 'red' : d.validation.result === 'WARN' ? 'amber' : 'green'}>{`검증 ${say(d.validation.result)}${d.validation.stale ? ' · 다시 검증 필요' : ''}`}</Badge></> : <> <Badge tone="slate">미검증</Badge></>}
      {' '}<button className="citation" onClick={() => ctx.open(ctx.cid, `${d.kind}:${d.version}`)}>문서 열기</button></p>)}{!r.documents.length && <span className="muted">D2~D4 문서 없음</span>}</>
    case 'queue': return <>{r.mine.map((i: J, n: number) => <p key={n}><Badge tone={TASK[i.task]?.[1] ?? 'slate'}>{TASK[i.task]?.[0] ?? i.task}</Badge> {i.doc_type} v{i.version} · {i.owner ?? '부서'} <button className="citation" onClick={() => ctx.open(i.case_id, `${i.kind}:${i.version}`)}>열기</button></p>)}
      {!r.mine.length && <p className="muted">{r.user}님의 이 사건 할 일은 없습니다 · 부서 할 일 {r.department.length}건</p>}</>
    case 'create_draft': case 'request_review': return <p><Badge tone="teal">{r.doc_type} v{r.version}</Badge> <Badge tone={STATUS_TONE[r.status]}>{r.status}</Badge> 주장 {r.claims.length}개
      {r.reviews?.length > 0 && ` · 검토자 ${r.reviews.map((x: J) => `${x.reviewer_id}(${say(x.state)})`).join(', ')}`} <button className="citation" onClick={() => ctx.open(ctx.cid, `${s.args.kind}:${r.version}`)}>문서 열기</button></p>
    case 'plan': return <p>{r.intents.length ? r.intents.map((i: string) => <Badge key={i} tone="violet">{INTENT[i] ?? i}</Badge>) : <Badge tone="amber">요청을 이해하지 못해 되물음</Badge>}</p>
    case 'summarize': return <p className="muted">위 답변을 작성했습니다</p>
    case 'fill_triage': return <TriageForm r={r} ctx={ctx}/>
    case 'validate_document': return <><p><Badge tone={r.result === 'BLOCK' ? 'red' : r.result === 'WARN' ? 'amber' : 'green'}>{`검증 ${say(r.result)}`}</Badge> 고칠 점 {r.issues.length}건{r.stale && <> <Badge tone="red">다시 검증 필요</Badge></>}</p>
      {r.issues.slice(0, 6).map((i: J, n: number) => <p key={n} className="muted wrap"><Badge tone={i.severity === 'BLOCK' ? 'red' : 'amber'}>{i.severity}</Badge> {i.claim_id ?? '문서'}: {words(i.message)}</p>)}</>
    case 'errors': return r.errors.length ? <>{r.errors.map((e: J, n: number) => <p key={n} className="wrap"><Badge tone="red">{e.at.slice(11, 16)}</Badge> <b>{e.action}</b> · {words(e.reason)} <span className="muted">→ {e.next}</span></p>)}</>
      : <span className="muted">최근에 막힌 요청이 없습니다</span>
    case 'previous_answer': return r.previous ? <><p className="muted wrap">앞 요청: {r.previous.goal}</p>{r.previous.answer.map((t: string, n: number) => <p key={n} className="wrap">{t}</p>)}</>
      : <span className="muted">이 사건에서 앞선 대화가 없습니다</span>
    default: return null
  }
}

const TOOL_TITLE: Record<string, string> = {
  create_draft: '문서 초안 저장', validate_document: '문서 검증', request_review: '검토 요청', fill_triage: 'D0 판정 양식 (제출 전)', plan: '요청 이해', summarize: '답변 작성',
}
const INTENT: Record<string, string> = { INVESTIGATE: '원인 조사', DRAFT_DOC: '문서 초안', TASKS: '할 일', STATUS: '진행 상태', EXPORT: '내려받기', TRIAGE: 'D0 판정', WHY_FAILED: '막힌 이유', EXPLAIN: '앞 답변 설명' }
export type Resume = (confirm: boolean, reviewer?: string, answer?: string) => void

// D0 form filled by the server's rules. Nothing is stored until a person with the D0 role submits it to /triage.
function TriageForm({ r, ctx }: { r: J; ctx: Ctx }) {
  const [f, setF] = useState<J>(r.fields)
  const [msg, setMsg] = useState('')
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  const submit = async () => {
    try { const t = await ctx.api(r.submit.path, 'POST', f); setMsg(`D0 판정을 기록했습니다: ${say(t.route)} · 심각도 ${say(t.severity)}`); ctx.refresh() }
    catch { setMsg('제출하지 못했습니다. 화면 위 메시지에 이유가 있습니다.') }
  }
  return <div>
    {r.basis.map((b: string) => <p key={b} className="muted wrap">· {b}</p>)}
    {r.notes.map((n: string) => <p key={n} className="wrap"><Badge tone="amber">확인</Badge> {n}</p>)}
    <label className="muted">경로 <select className="input" value={f.route} onChange={set('route')}>{['NCR_ONLY', 'FULL_8D', 'EMERGENCY_FULL_8D'].map(x => <option key={x} value={x}>{say(x)}</option>)}</select></label>
    <label className="muted">심각도 <select className="input" value={f.severity} onChange={set('severity')}>{['LOW', 'MEDIUM', 'HIGH'].map(x => <option key={x} value={x}>{say(x)}</option>)}</select></label>
    <p className="muted">신호 {say(f.signal_kind)} · 관측 {say(f.observed_defect)} · LOT {f.scope_lots.join(', ') || '-'}</p>
    <label className="muted">판정 사유<textarea className="input" rows={3} value={f.rationale} onChange={set('rationale')}/></label>
    <p className="muted">근거 <Cite ids={f.evidence_ids}/></p>
    <button className="button primary" disabled={!r.submit.can_submit} onClick={submit}>{r.submit.can_submit ? '검토 후 D0 판정 제출' : `${say(r.submit.role)}만 제출할 수 있습니다`}</button>
    {msg && <p className="wrap" role="status">{msg}</p>}
    <p className="muted">제출하기 전에는 기록되지 않습니다.</p>
  </div>
}

function StepCard({ s, title, ctx }: { s: J; title: string; ctx: Ctx }) {
  const tone: Tone = s.status === 'OK' ? 'green' : 'red'
  return <Card className="tool-card"><div className="tool-top"><span className={`tool-icon ${s.kind === 'READ' ? '' : 'violet'}`}><Icon name={s.kind === 'READ' ? 'database' : 'document'}/></span>
    <div><b>{title}</b><small>{s.kind === 'READ' ? '조회' : '작성'} · {(s.duration_ms / 1000).toFixed(1)}초</small></div>
    <Badge tone={tone}>{s.status === 'OK' ? '완료' : s.status === 'DENIED' ? '거부됨' : '오류'}</Badge></div>
    <div className="tool-result">{s.status === 'OK' ? (StepBody({ s, ctx }) ?? <span className="muted">결과 없음</span>) : <span className="wrap">{words(s.error ?? '')}</span>}</div>
  </Card>
}

export function PendingCard({ run, busy, onResume }: { run: J; busy: boolean; onResume: Resume }) {
  const p = run.pending
  const answered = (run.reply ?? []).some((l: J) => l.role === 'answer')  // the model already asked it in its own words
  const [who, setWho] = useState<string>(p?.candidates?.length === 1 ? p.candidates[0].user_id : '')
  const [answer, setAnswer] = useState('')
  if (!p || run.status !== 'NEEDS_HUMAN') return null
  return <Card className="missing-card"><div className="missing-icon"><Icon name="warning"/></div><div>
    {p.action === 'confirm_scope' && <><b>대상 사건 확인이 필요합니다</b>{!answered && <p>{p.question}</p>}
      <textarea className="input" aria-label="범위를 바꾸려면 새 조건 입력" placeholder="범위를 바꾸려면 입력 (예: 아니 L03으로)" rows={1} value={answer} disabled={busy} onChange={e => setAnswer(e.target.value)}/>
      <div className="row-gap mt"><button className="button primary" disabled={busy} onClick={() => onResume(true, undefined, answer.trim() || undefined)}>{answer.trim() ? '새 조건으로 다시 확인' : `현재 사건 ${run.case_id}로 진행`}</button><button className="button secondary" disabled={busy} onClick={() => onResume(false)}>취소</button></div></>}
    {p.action === 'confirm_partial' && <><b>일부만 할 수 있는 요청입니다</b>{!answered && <p>{p.question}</p>}
      <textarea className="input" aria-label="범위를 바꾸려면 새 조건 입력" placeholder="범위를 바꾸려면 입력 (예: 아니 L03으로)" rows={1} value={answer} disabled={busy} onChange={e => setAnswer(e.target.value)}/>
      <div className="row-gap mt"><button className="button primary" disabled={busy} onClick={() => onResume(true, undefined, answer.trim() || undefined)}>{answer.trim() ? '새 조건으로 다시 확인' : '지원 범위만 진행'}</button>
        <button className="button secondary" disabled={busy} onClick={() => onResume(false)}>취소</button></div></>}
    {p.action === 'request_review' && <><b>{p.kind.toUpperCase()} v{p.version} 검토를 요청할까요?</b>
      <p>검증 결과 {say(p.validation)}. 검토자를 고르면 검토 요청을 보냅니다.</p>
      <fieldset className="row-gap" disabled={busy}><legend className="muted">검토자</legend>{p.candidates.map((c: J) => <label key={c.user_id} className="row-gap"><input type="radio" name={`rv-${run.run_id}`} value={c.user_id} checked={who === c.user_id} onChange={() => setWho(c.user_id)}/>{c.name} · {say(c.role)}</label>)}</fieldset>
      <div className="row-gap mt"><button className="button primary" disabled={busy || !who} onClick={() => onResume(true, who)}>검토 요청 보내기</button><button className="button secondary" disabled={busy} onClick={() => onResume(false)}>보류</button></div></>}
    {p.action === 'await' && <><b>다른 담당자의 결정을 기다립니다</b><p>{p.kind.toUpperCase()} v{p.version} · {p.owner ?? `${say(p.owner_role)} 부서`}. 결정이 나면 '다시 확인'을 눌러 이어 가세요.</p>
      <div className="handoff"><span>{p.owner ?? say(p.owner_role)}</span><Badge tone="amber">응답 대기</Badge></div>
      <div className="row-gap mt"><button className="button secondary" disabled={busy} onClick={() => onResume(true)}>다시 확인</button></div></>}
    {p.action === 'clarify' && <><b>조금 더 알려 주세요</b>{!answered && <p>{p.question}</p>}
      <textarea className="input" aria-label="Agent 질문에 대한 답변" rows={2} value={answer} disabled={busy} onChange={e => setAnswer(e.target.value)}/>
      <div className="row-gap mt"><button className="button primary" disabled={busy || !answer.trim()} onClick={() => onResume(true, undefined, answer.trim())}>답변 보내기</button>
        <button className="button secondary" disabled={busy} onClick={() => onResume(false)}>그만두기</button></div></>}
    {p.action === 'offer_fill' && <><b>양식을 채워 드릴까요?</b>{!answered && <p>{p.question}</p>}
      <div className="row-gap mt"><button className="button primary" disabled={busy} onClick={() => onResume(true)}>예, 채워 주세요</button>
        <button className="button secondary" disabled={busy} onClick={() => onResume(false)}>아니요</button></div></>}
  </div></Card>
}

export function RunView({ run, ctx, busy, onResume }: { run: J; ctx: Ctx; busy: boolean; onResume: Resume }) {
  const titles: Record<string, string> = Object.fromEntries((run.plan ?? []).map((p: J) => [p.tool, p.title]))
  return <div className="message agent-message"><div className="avatar muse"><Icon name="spark" size={17}/></div><div className="message-body">
    <div className="agent-label"><b>QualityOps Agent</b><Badge tone={RUN_TONE[run.status]}>{RUN_LABEL[run.status] ?? run.status}</Badge><span className="muted">{run.updated_at?.slice(5, 16).replace('T', ' ')}</span></div>
    {/* the answer is the model's (role answer) or a system notice; the server's facts sit in the work log */}
    {(run.reply ?? []).filter((l: J) => l.role !== 'fact').map((l: J, i: number) => <p key={i} className={`wrap${l.folded ? ' muted' : ''}`}>{l.grade && <><Badge tone={l.grade === 'A' ? 'green' : l.grade === 'B' ? 'blue' : 'slate'}>{l.folded ? '참고 · ' : ''}근거 {l.grade}</Badge> </>}{l.text}{l.evidence?.length > 0 && <> <span className="muted">근거</span> <Cite ids={l.evidence}/></>}{l.sources?.length > 0 && <> <span className="muted">참고</span> <Cite ids={l.sources}/></>}{l.grade_label && <span className="muted"> ({l.grade_label})</span>}</p>)}
    <PendingCard key={run.pending?.token ?? 'none'} run={run} busy={busy} onResume={onResume}/>
    {/* the plan and every tool call stay one click away (review and audit), not in the way of the answer */}
    <details className="work-log"><summary>작업 과정 보기 · {(run.plan ?? []).length}단계{(run.steps ?? []).some((s: J) => s.status !== 'OK') ? ' · 막힌 단계 있음' : ''}</summary>
      {(run.reply ?? []).some((l: J) => l.role === 'fact') && <Card><SectionTitle title="답의 근거가 된 기록"/>
        <ul className="facts">{(run.reply ?? []).filter((l: J) => l.role === 'fact').map((l: J, i: number) => <li key={i} className="wrap">{words(l.text)}{l.evidence?.length > 0 && <> · <Cite ids={l.evidence}/></>}</li>)}</ul></Card>}
      <PlanCard run={run}/>
      <div className="tool-grid">{(run.steps ?? []).map((s: J) => <StepCard key={s.seq} s={s} title={titles[s.tool] ?? TOOL_TITLE[s.tool] ?? s.tool} ctx={ctx}/>)}</div></details>
  </div></div>
}
