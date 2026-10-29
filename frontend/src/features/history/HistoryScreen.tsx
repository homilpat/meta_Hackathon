import { Badge, Card, Empty, Icon, Note, Page, SectionTitle } from '../../components/ui'
import { useLoad } from '../../hooks/useLoad'
import type { Ctx, J } from '../../types'

export function HistoryScreen({ ctx }: { ctx: Ctx }) {
  const on = useLoad<J>(ctx, `/cases/${ctx.cid}/next-evidence?history_mode=on`, null)
  const off = useLoad<J>(ctx, `/cases/${ctx.cid}/next-evidence?history_mode=off`, null)
  const link = async (id: string, decision: string) => { await ctx.api(`/cases/${ctx.cid}/history/links`, 'POST', { historical_case_id: id, decision, note: 'UI' }); ctx.refresh() }
  const checks = (n: J) => n?.next_checks?.length ? n.next_checks.map((c: J, i: number) => <div className="rec-row" key={c.check}><b className="rank">{i + 1}</b><div><strong>{c.check}</strong><span>{c.what} · {c.who}</span><small>{c.reason}</small></div></div>) : <Empty>판별력 있는 확인 항목 없음</Empty>
  if (!on || !off) return <Page title="과거 품질 사례" desc="불러오는 중…"><span/></Page>
  return <Page title="과거 품질 사례 기반 조사" desc="합성 선례 은행에서 적격 사례만 검색해 다음 확인 항목을 정합니다.">
    <div className="history-summary"><div><span>상태</span><b>{on.status}</b></div><div><span>적격 선례</span><b>{on.precedents.length}건</b></div><div><span>사용된 선례</span><b>{on.precedents_used.join(', ') || '-'}</b></div><Badge tone="violet">History OFF / ON 비교</Badge></div>
    <div className="history-layout">
      <Card><SectionTitle title="History OFF" sub="현재 사건 근거만"/>{checks(off)}</Card>
      <Card className="learning-panel"><SectionTitle title="History ON" sub="적격 선례 반영"/>{checks(on)}
        {on.warnings.map((w: J) => <div className="insight bad" key={w.text}><Icon name="warning"/><div><b>과거 조치를 그대로 반복하지 마세요</b><span>{w.text}</span></div></div>)}
        <Note>유사도는 후보를 고르는 기준일 뿐 현재 사건의 인과관계를 확정하지 않습니다.</Note></Card>
      <div className="stack">{on.precedents.map((p: J) => <Card key={p.historical_case_id} className="history-card"><div className="history-head"><b>{p.historical_case_id} v{p.snapshot_version}</b>
        {ctx.me?.role === 'AUTHOR' && <span><button className="citation" onClick={() => link(p.historical_case_id, 'ACCEPTED')}>사용</button> <button className="citation" onClick={() => link(p.historical_case_id, 'REJECTED')}>제외</button></span>}</div>
        <strong>{p.why_similar.join('; ')}</strong><div className="history-detail">{p.outcomes.map((o: J, i: number) => <span key={i}>{o.check}: {o.check_status}{o.action && <b>{o.action}: {o.outcome_status}</b>}</span>)}</div>
        {p.limitations.length > 0 && <p className="muted">{p.limitations.join('; ')}</p>}</Card>)}</div>
    </div>
  </Page>
}
