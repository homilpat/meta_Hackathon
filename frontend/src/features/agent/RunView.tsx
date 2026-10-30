import { useState } from 'react'
import { STATUS_TONE } from '../../constants'
import { Badge, Card, Cite, Icon, Note, SectionTitle } from '../../components/ui'
import { ExportButtons } from '../../components/ExportButtons'
import { ControlChart } from '../spc/Spc'
import { TASK } from '../queue/Queue'
import type { Ctx, J, Tone } from '../../types'

// Renders one persisted AgentRun exactly as the server returned it. Nothing here decides or claims a state.
export const RUN_TONE: Record<string, Tone> = {
  PLANNED: 'slate', RUNNING: 'blue', NEEDS_HUMAN: 'amber', BLOCKED: 'red', FAILED: 'red', COMPLETED: 'green',
}
export const RUN_LABEL: Record<string, string> = {
  PLANNED: '계획됨', RUNNING: '실행 중', NEEDS_HUMAN: '사람 확인 필요', BLOCKED: '차단됨', FAILED: '실패', COMPLETED: '완료',
}
const ITEM: Record<string, [string, Tone]> = {
  PENDING: ['대기', 'slate'], RUNNING: ['실행 중', 'blue'], DONE: ['완료', 'green'], ERROR: ['오류', 'red'], DENIED: ['거부됨', 'red'],
  NEEDS_HUMAN: ['사람 확인 필요', 'amber'], BLOCKED: ['차단됨', 'red'], FAILED: ['실패', 'red'], SKIPPED: ['건너뜀', 'slate'],
}

function PlanCard({ run }: { run: J }) {
  const plan: J[] = run.plan ?? []
  const done = plan.filter(i => i.status === 'DONE').length
  const [sel, setSel] = useState<number | null>(null)
  return <Card className="plan-card"><SectionTitle title="실행 계획" sub={`${plan.length}개 작업 · 플래너 ${run.planner} · 서버가 단계마다 실행·기록`} action={<b className="progress-text">{done} / {plan.length}</b>}/>
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
    case 'case_summary': return <div className="table-wrap"><table><thead><tr><th>LOT</th><th>스텐실</th><th>AOI</th><th>FAIL</th><th>미해소</th><th>근거</th></tr></thead><tbody>
      {r.lots.map((l: J) => <tr key={l.lot}><td><b className="id">{l.lot}</b></td><td>{l.stencil}</td><td>{l.aoi}</td><td>{l.fail}</td><td>{l.not_cleared}</td><td><Cite ids={[l.lot_ev]}/></td></tr>)}
    </tbody></table>{r.aoi_fail.slice(0, 5).map((f: J) => <p key={f.board} className="muted wrap">AOI FAIL {f.board} · {f.aoi[0]} <Cite ids={[f.aoi[1], ...(f.human ? [f.human[1]] : [])]}/>{f.human && ` · 사람 판정 ${f.human[0]}`}</p>)}</div>
    case 'data_integrity': return <><div className="row-gap">{Object.entries(r.issue_counts as Record<string, number>).map(([k, n]) => <Badge key={k} tone="amber">{k} {n}</Badge>)}</div>
      {r.issues.slice(0, 4).map((i: J, n: number) => <p key={n} className="muted wrap">{i.code} · {i.detail} <Cite ids={[i.evidence_id]}/></p>)}
      {!r.issues.length && <span className="muted">기록된 데이터 품질 이슈 없음</span>}</>
    case 'spc': return r.points ? <><ControlChart m={r}/>{r.first_alarm && <Badge tone="red">첫 경보 {r.first_alarm.lot} {r.first_alarm.panel}/{r.first_alarm.board} · {r.first_alarm.rules.join(', ')}</Badge>}
      <Note>관리도 신호는 통계 신호입니다. 불량 판정이나 원인 확정이 아닙니다.</Note></> : null
    case 'predictions': return <>{r.predictions.slice(0, 5).map((p: J) => <p key={p.evidence_id} className="muted">{p.target_key.join('/')} · 위험 {p.risk_score} (임계 {p.threshold}) {p.above_threshold && <Badge tone="amber">임계 초과</Badge>} <Cite ids={[p.evidence_id]}/></p>)}
      {r.top_explanation && <p className="muted wrap">SHAP <Cite ids={[r.top_explanation.evidence_id]}/> {Object.entries(r.top_explanation.contributions_log_odds).slice(0, 3).map(([k, v]) => `${k} ${v}`).join(' · ')}</p>}
      <Note>{r.note} SHAP은 모델 점수의 설명이며 물리적 원인이 아닙니다.</Note></>
    case 'evidence_gaps': return <>{r.hypotheses.map((h: J) => <p key={h.hypothesis_id} className="wrap"><Badge tone="violet">가설 #{h.hypothesis_id} {h.status}</Badge> {h.text} — <span className="muted">{h.gaps.join(' · ') || '공백 없음'}</span></p>)}
      {r.case_unknowns.map((u: J, i: number) => <p key={`u${i}`} className="muted wrap"><Badge tone="slate">UNKNOWN</Badge> {typeof u === 'string' ? u : u.text ?? JSON.stringify(u)}</p>)}
      {r.next_checks.map((c: J, i: number) => <p key={`c${i}`} className="muted wrap"><Badge tone="teal">다음 확인</Badge> {typeof c === 'string' ? c : c.check ?? JSON.stringify(c)}</p>)}</>
    case 'experience': return <><p><Badge tone={r.mode === 'KNOWN' ? 'green' : r.mode === 'ANALOGICAL' ? 'amber' : 'slate'}>{r.mode}</Badge> 추천 {r.recommendations.length}건 · 실패 사례 {r.negative_precedents.length}건</p><Note>{r.note}</Note></>
    case 'history': return <p className="muted wrap">{r.precedents.map((p: J) => p.historical_case_id).join(', ') || '적격 과거 사례 없음'} · 유사도는 인과 근거가 아닙니다.</p>
    case 'stages': return <><div className="row-gap">{r.stages.map((x: J) => <Badge key={x.kind} tone={STATUS_TONE[x.status] ?? 'slate'}>{x.step} {x.doc_type} {x.status ?? '미작성'}{!x.approval_open && ' · 잠금'}</Badge>)}</div>
      {r.closure && <p className="muted wrap">D8 종료 {r.closure.ready ? <Badge tone="green">조건 충족</Badge> : <Badge tone="amber">미충족</Badge>} {(r.closure.blocks ?? []).slice(0, 4).join(' · ')}</p>}
      <button className="citation" onClick={() => ctx.open(ctx.cid, '', 'eightd')}>D0~D8 화면 열기</button></>
    case 'exports': return <>{r.documents.map((d: J) => <div key={d.kind}><Badge tone="green">{d.doc_type} v{d.version} APPROVED</Badge>
      <ExportButtons user={ctx.me?.id} path={d.path} label={`${d.doc_type} 승인본`}/></div>)}
      {r.report && <ExportButtons user={ctx.me?.id} path={r.report} label="8D 종료 보고서"/>}
      {!r.documents.length && !r.report && <span className="muted">승인된 문서가 없어 내보낼 파일이 없습니다. 초안은 승인본으로 내보낼 수 없습니다.</span>}
      <Note>파일은 버튼을 누를 때 서버가 승인 해시를 다시 확인해 만듭니다. Agent는 파일을 미리 만들거나 대신 내려받지 않습니다.</Note></>
    case 'documents': return <>{r.documents.map((d: J) => <p key={d.kind}><Badge tone="teal">{d.doc_type} v{d.version}</Badge> <Badge tone={STATUS_TONE[d.status]}>{d.status}</Badge>
      {d.validation ? <> <Badge tone={d.validation.result === 'BLOCK' ? 'red' : d.validation.result === 'WARN' ? 'amber' : 'green'}>검증 {d.validation.result}{d.validation.stale ? ' · STALE' : ''}</Badge></> : <> <Badge tone="slate">미검증</Badge></>}
      {' '}<button className="citation" onClick={() => ctx.open(ctx.cid, `${d.kind}:${d.version}`)}>문서 열기</button></p>)}{!r.documents.length && <span className="muted">D2~D4 문서 없음</span>}</>
    case 'queue': return <>{r.mine.map((i: J, n: number) => <p key={n}><Badge tone={TASK[i.task]?.[1] ?? 'slate'}>{TASK[i.task]?.[0] ?? i.task}</Badge> {i.doc_type} v{i.version} · {i.owner ?? '부서'} <button className="citation" onClick={() => ctx.open(i.case_id, `${i.kind}:${i.version}`)}>열기</button></p>)}
      {!r.mine.length && <p className="muted">{r.user}의 이 사건 할 일 없음 · 부서({r.role}) {r.department.length}건</p>}</>
    case 'create_draft': case 'request_review': return <p><Badge tone="teal">{r.doc_type} v{r.version}</Badge> <Badge tone={STATUS_TONE[r.status]}>{r.status}</Badge>{r.status === 'DRAFT' && <> <Badge tone="slate">승인 아님</Badge></>} 주장 {r.claims.length}개
      {r.reviews?.length > 0 && ` · 검토자 ${r.reviews.map((x: J) => `${x.reviewer_id}(${x.state})`).join(', ')}`} <button className="citation" onClick={() => ctx.open(ctx.cid, `${s.args.kind}:${r.version}`)}>문서 열기</button></p>
    case 'validate_document': return <><p><Badge tone={r.result === 'BLOCK' ? 'red' : r.result === 'WARN' ? 'amber' : 'green'}>검증 {r.result}</Badge> 이슈 {r.issues.length}건{r.stale && <> <Badge tone="red">STALE</Badge></>}</p>
      {r.issues.slice(0, 6).map((i: J, n: number) => <p key={n} className="muted wrap"><Badge tone={i.severity === 'BLOCK' ? 'red' : 'amber'}>{i.code}</Badge> {i.claim_id ?? '문서'}: {i.message}</p>)}</>
    default: return null
  }
}

const TOOL_TITLE: Record<string, string> = {
  create_draft: '문서 초안 저장', validate_document: '문서 검증', request_review: '검토 요청',
}

function StepCard({ s, title, ctx }: { s: J; title: string; ctx: Ctx }) {
  const tone: Tone = s.status === 'OK' ? 'green' : 'red'
  return <Card className="tool-card"><div className="tool-top"><span className={`tool-icon ${s.kind === 'WRITE' ? 'violet' : ''}`}><Icon name={s.kind === 'WRITE' ? 'document' : 'database'}/></span>
    <div><b>{title}</b><small>#{s.seq} · {s.kind} · {s.tool} · {s.duration_ms}ms{s.http_status ? ` · HTTP ${s.http_status}` : ''}</small></div>
    <Badge tone={tone}>{s.status === 'OK' ? '서버 응답 확인' : s.status === 'DENIED' ? '거부됨' : '오류'}</Badge></div>
    <div className="tool-result">{s.status === 'OK' ? (StepBody({ s, ctx }) ?? <span className="muted">결과 없음</span>) : <span className="wrap">{s.error}</span>}</div>
    {s.audit_event_ids?.length > 0 && <button className="citation" onClick={() => ctx.open(ctx.cid, '', 'audit')}>감사 이벤트 {s.audit_event_ids.map((i: number) => `#${i}`).join(' ')}</button>}
  </Card>
}

export function PendingCard({ run, busy, onResume }: { run: J; busy: boolean; onResume: (confirm: boolean, reviewer?: string) => void }) {
  const p = run.pending
  const [who, setWho] = useState<string>(p?.candidates?.length === 1 ? p.candidates[0].user_id : '')
  if (!p || run.status !== 'NEEDS_HUMAN') return null
  return <Card className="missing-card"><div className="missing-icon"><Icon name="warning"/></div><div>
    {p.action === 'confirm_scope' && <><b>대상 사건 확인이 필요합니다</b><p>{p.question}</p>
      <div className="row-gap"><button className="button primary" disabled={busy} onClick={() => onResume(true)}>현재 사건 {run.case_id}로 진행</button><button className="button secondary" disabled={busy} onClick={() => onResume(false)}>취소</button></div></>}
    {p.action === 'request_review' && <><b>{p.kind.toUpperCase()} v{p.version} 검토 요청 확인</b>
      <p>검증 {p.validation}. 검토자({p.approver_role})를 선택하면 서버가 정책·배정·문서 해시를 다시 확인한 뒤 요청합니다. 이것은 승인이 아닙니다.</p>
      <fieldset className="row-gap" disabled={busy}><legend className="muted">검토자</legend>{p.candidates.map((c: J) => <label key={c.user_id} className="row-gap"><input type="radio" name={`rv-${run.run_id}`} value={c.user_id} checked={who === c.user_id} onChange={() => setWho(c.user_id)}/>{c.name} · {c.role}</label>)}</fieldset>
      <div className="row-gap mt"><button className="button primary" disabled={busy || !who} onClick={() => onResume(true, who)}>검토 요청 보내기</button><button className="button secondary" disabled={busy} onClick={() => onResume(false)}>보류</button></div></>}
    {p.action === 'await' && <><b>다른 담당자의 결정을 기다립니다</b><p>{p.kind.toUpperCase()} v{p.version} · {p.owner ?? `${p.owner_role} 부서`}. 결정 후 '다시 확인'을 누르면 서버 상태를 다시 읽고 이어갑니다.</p>
      <div className="handoff"><span>{p.owner ?? p.owner_role}</span><Badge tone="amber">응답 대기</Badge></div>
      <div className="row-gap mt"><button className="button secondary" disabled={busy} onClick={() => onResume(true)}>다시 확인</button></div></>}
  </div></Card>
}

export function RunView({ run, ctx, busy, onResume }: { run: J; ctx: Ctx; busy: boolean; onResume: (confirm: boolean, reviewer?: string) => void }) {
  const titles: Record<string, string> = Object.fromEntries((run.plan ?? []).map((p: J) => [p.tool, p.title]))
  return <div className="message agent-message"><div className="avatar muse"><Icon name="spark" size={17}/></div><div className="message-body">
    <div className="agent-label"><b>QualityOps Agent</b><Badge tone={RUN_TONE[run.status]}>{RUN_LABEL[run.status] ?? run.status}</Badge><span className="muted">run #{run.run_id} · {run.updated_at?.slice(0, 19)}</span></div>
    {(run.reply ?? []).map((l: J, i: number) => <p key={i} className="wrap">{l.text}{l.steps?.length > 0 && <span className="muted"> (step {l.steps.join(', ')})</span>}</p>)}
    <PlanCard run={run}/>
    <PendingCard key={run.pending?.token ?? 'none'} run={run} busy={busy} onResume={onResume}/>
    <div className="tool-grid">{(run.steps ?? []).map((s: J) => <StepCard key={s.seq} s={s} title={titles[s.tool] ?? TOOL_TITLE[s.tool] ?? s.tool} ctx={ctx}/>)}</div>
    <div className="agent-note"><Icon name="shield"/><p><b>사람의 검토가 필요한 결정은 사람이 내립니다.</b> Agent는 문서 승인, 근본원인 확정, 조치 실행 기록, 사건 종료를 하지 않으며 서버가 재조회로 확인한 상태만 알립니다.</p></div>
  </div></div>
}
