import { Badge, Card, Empty, Icon, Page, SectionTitle } from '../../components/ui'
import { useLoad } from '../../hooks/useLoad'
import { say, words } from '../../labels'
import type { Ctx, J } from '../../types'

export function HistoryScreen({ ctx }: { ctx: Ctx }) {
  const on = useLoad<J>(ctx, `/cases/${ctx.cid}/next-evidence?history_mode=on`, null)
  const off = useLoad<J>(ctx, `/cases/${ctx.cid}/next-evidence?history_mode=off`, null)
  const link = async (id: string, decision: string) => { await ctx.api(`/cases/${ctx.cid}/history/links`, 'POST', { historical_case_id: id, decision, note: 'UI' }); ctx.refresh() }
  const checks = (n: J) => n?.next_checks?.length ? n.next_checks.map((c: J, i: number) => <div className="rec-row" key={c.check}><b className="rank">{i + 1}</b><div><strong>{say(c.check)}</strong><span>{words(c.what)} · {say(c.who)}</span><small>{words(c.reason)}</small></div></div>) : <Empty>확인할 항목이 없습니다</Empty>
  if (!on || !off) return <Page title="과거 품질 사례" desc="불러오는 중…"><span/></Page>
  return <Page title="과거 품질 사례" desc="이 사건과 비슷한 과거 사례를 찾아, 다음에 무엇을 확인할지 정합니다.">
    <div className="history-summary"><div><span>비슷한 과거 사례</span><b>{on.precedents.length}건</b></div><div><span>참고한 사례</span><b>{on.precedents_used.join(', ') || '-'}</b></div></div>
    <div className="history-layout">
      <Card><SectionTitle title="이 사건 기록만 볼 때" sub="다음에 확인할 것"/>{checks(off)}</Card>
      <Card className="learning-panel"><SectionTitle title="과거 사례도 참고할 때" sub="다음에 확인할 것"/>{checks(on)}
        {on.warnings.map((w: J) => <div className="insight bad" key={w.text}><Icon name="warning"/><div><b>과거에 효과가 없던 조치입니다</b><span>{words(w.text)}</span></div></div>)}</Card>
      <div className="stack">{on.precedents.map((p: J) => <Card key={p.historical_case_id} className="history-card"><div className="history-head"><b>{p.historical_case_id}</b>
        {p.negative_precedent && <Badge tone="red">효과 없던 조치 있음</Badge>}
        {ctx.me?.role === 'AUTHOR' && <span><button className="citation" onClick={() => link(p.historical_case_id, 'ACCEPTED')}>참고</button> <button className="citation" onClick={() => link(p.historical_case_id, 'REJECTED')}>제외</button></span>}</div>
        <ul className="facts">{p.why_similar.map((w: string) => <li key={w} className="wrap">{words(w)}</li>)}</ul>
        <div className="history-detail">{p.outcomes.map((o: J, i: number) => <span key={i}>{say(o.check)}: {say(o.check_status)}{o.action && <b>{say(o.action)}: {say(o.outcome_status)}</b>}</span>)}</div>
        {p.limitations.length > 0 && <p className="muted">{p.limitations.join('; ')}</p>}</Card>)}</div>
    </div>
  </Page>
}
