import { STATUS_TONE } from '../../constants'
import { Badge, Icon } from '../../components/ui'
import { useLoad } from '../../hooks/useLoad'
import { APPROVAL_TASKS, TASK } from '../queue/Queue'
import { say, words } from '../../labels'
import type { Ctx, J } from '../../types'

// The active case as the server sees it now: 8D state, evidence quality, my open work. Same reads as the detail screens.
export function ContextPanel({ ctx, go }: { ctx: Ctx; go: (view: string) => void }) {
  const p = (x: string) => ctx.cid ? `/cases/${ctx.cid}/${x}` : null
  const stages = useLoad<J[]>(ctx, p('stages'), [])
  const quality = useLoad<J>(ctx, p('evidence-quality'), null)
  const mine = useLoad<J[]>(ctx, '/queue?scope=mine', []).filter(i => i.case_id === ctx.cid)
  const dept = useLoad<J[]>(ctx, '/queue?scope=department', []).filter(i => i.case_id === ctx.cid)
  const approvals = dept.filter(i => APPROVAL_TASKS.includes(i.task))
  const blocked = stages.filter(s => s.blocked_by)
  if (!ctx.cid) return <aside className="context-panel" aria-label="사건 컨텍스트"><p className="muted">배정된 사건이 없습니다.</p></aside>
  return <aside className="context-panel" aria-label="사건 컨텍스트">
    <div className="context-title"><span>현재 사건</span><b>{ctx.cid}</b></div>
    <div className="context-section"><b>8D 문서 단계</b>{stages.map(s => <div key={s.kind} className="context-row"><span>{s.step} {s.doc_type}</span>
      <Badge tone={STATUS_TONE[s.status] ?? 'slate'}>{s.status ? `v${s.version} ${say(s.status)}` : '미작성'}</Badge></div>)}
      <button className="link-button" onClick={() => go('eightd')}>D0~D8 전체 보기 <Icon name="arrow" size={13}/></button></div>
    <div className="context-section"><b>근거 기록 상태</b>{quality ? <div className="evidence-counts">{Object.entries(quality.counts as Record<string, number>).map(([k, v]) =>
      <span key={k}><b>{v}</b>{say(k)}</span>)}</div> : <p className="muted">조회 불가</p>}
      <button className="link-button" onClick={() => go('data')}>증거 · 데이터 열기 <Icon name="arrow" size={13}/></button></div>
    <div className="context-section"><b>내 할 일 <Badge tone={mine.length ? 'amber' : 'slate'}>{mine.length}</Badge></b>
      {mine.slice(0, 4).map((i, n) => <button key={n} className="context-item" onClick={() => ctx.open(i.case_id, `${i.kind}:${i.version}`)}><Icon name="check"/>
        <span><strong>{i.doc_type} v{i.version}</strong>{TASK[i.task]?.[0] ?? i.task}</span></button>)}
      <button className="link-button" onClick={() => go('my')}>내 할 일 전체 <Icon name="arrow" size={13}/></button></div>
    <div className="context-section"><b>승인 대기 <Badge tone={approvals.length ? 'amber' : 'slate'}>{approvals.length}</Badge></b>
      {approvals.slice(0, 4).map((i, n) => <button key={n} className="context-item" onClick={() => ctx.open(i.case_id, `${i.kind}:${i.version}`)}><Icon name="shield"/>
        <span><strong>{i.doc_type} v{i.version}</strong>{TASK[i.task]?.[0]} · {i.owner ?? '부서'}</span></button>)}</div>
    {blocked.length > 0 && <div className="blocker"><Icon name="warning"/><span><b>아직 결재할 수 없는 문서 {blocked.length}건</b>{blocked.map(s => `${s.doc_type}: ${words(s.blocked_by)}`).join(' · ')}</span></div>}
  </aside>
}
