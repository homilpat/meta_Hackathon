import { Stages } from '../../components/Stages'
import { Badge, Card, Empty, Icon, Page, SectionTitle } from '../../components/ui'
import { useLoad } from '../../hooks/useLoad'
import type { Ctx, J } from '../../types'

export function Dashboard({ ctx, cases, onNew }: { ctx: Ctx; cases: J[]; onNew: (line: boolean) => void }) {
  const p = (x: string) => ctx.cid ? `/cases/${ctx.cid}/${x}` : null
  const ev = useLoad<J[]>(ctx, p('evidence'), []), iss = useLoad<J[]>(ctx, p('data-issues'), [])
  const preds = useLoad<J[]>(ctx, p('predictions'), []), runs = useLoad<J[]>(ctx, p('investigations'), [])
  const docs = [useLoad<J[]>(ctx, p('ncr'), []), useLoad<J[]>(ctx, p('containment'), []), useLoad<J[]>(ctx, p('rca'), [])]
  const reval = docs.flat().filter(d => d.status === 'REVALIDATION_REQUIRED' || d.status === 'BASIS_CHANGED').length
  return <Page title="품질 운영 현황" desc="선택한 사건의 근거, 모델 출력, 문서 결재 상태를 확인합니다." action={ctx.me?.role === 'AUTHOR' && <span className="row-gap"><button className="button secondary" onClick={() => onNew(false)}>시험 사건 (소형)</button>
      <button className="button primary" onClick={() => onNew(true)}>시험 사건 (SMT 라인)</button></span>}>
    {!ctx.cid ? <Card><Empty>배정된 사건이 없습니다.</Empty></Card> : <>
      <div className="kpi-grid">
        {([['근거 기록', ev.length, 'teal'], ['데이터 품질 이슈', iss.length, iss.length ? 'amber' : 'green'], ['모델 예측', preds.length, 'blue'],
          ['AI 조사 실행', runs.length, 'violet'], ['재검토 필요 문서', reval, reval ? 'red' : 'green']] as const).map(x =>
          <Card key={x[0]}><span className="kpi-label">{x[0]}</span><div className="kpi-value">{x[1]} <i className={`dot ${x[2]}`}/></div></Card>)}
      </div>
      <Card><SectionTitle title="8D 결재 흐름"/><Stages ctx={ctx}/></Card>
    </>}
    <Card className="mt"><SectionTitle title="배정된 사건" sub={`${cases.length}건`}/><div className="table-wrap"><table><thead><tr><th>사건</th><th>분야</th><th>자료</th></tr></thead>
      <tbody>{cases.map(c => <tr key={c.case_id}><td><b className="id">{c.case_id}</b></td><td>{c.domain}</td><td><Badge tone="blue">{c.data_origin}</Badge></td></tr>)}</tbody></table></div></Card>
  </Page>
}
