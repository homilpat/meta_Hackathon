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
  return <Page title="품질 운영 현황" desc="선택한 사건의 근거, 모델 출력, 문서 결재 상태를 확인합니다." action={ctx.me?.role === 'AUTHOR' && <span className="row-gap"><button className="button secondary" onClick={() => onNew(false)}>소형 픽스처 사건</button>
      <button className="button primary" onClick={() => onNew(true)}>SMT 라인 사건 (3 lot · 144 보드)</button></span>}>
    <div className="demo-notice"><Icon name="spark" size={15}/><b>합성 데이터</b><span>모든 제조 기록은 생성기로 만든 가상의 PCB 데이터(SYNTHETIC, SELF_GENERATED)이며 실제 제조 성과가 아닙니다.</span></div>
    <div className="capability-rail">
      <div><span className="capability-icon teal"><Icon name="database"/></span><p><b>근거 기반 문서</b><span>관측·계산 주장은 반드시 Evidence ID를 인용하고 서버가 검증합니다</span></p></div>
      <div><span className="capability-icon violet"><Icon name="spark"/></span><p><b>설명 가능한 AI</b><span>모델 점수와 SHAP은 설명일 뿐, 물리적 원인 확정이 아닙니다</span></p></div>
      <div><span className="capability-icon amber"><Icon name="nodes"/></span><p><b>변경 영향 추적</b><span>정정된 원천 행에 의존하는 문서만 재검토로 되돌립니다</span></p></div>
    </div>
    {!ctx.cid ? <Card><Empty>배정된 사건이 없습니다. 작성자 계정으로 새 합성 사건을 만드세요.</Empty></Card> : <>
      <div className="kpi-grid">
        {([['Evidence 행', ev.length, 'teal'], ['데이터 품질 이슈', iss.length, iss.length ? 'amber' : 'green'], ['모델 예측', preds.length, 'blue'],
          ['AI 조사 실행', runs.length, 'violet'], ['재검토 필요 문서', reval, reval ? 'red' : 'green']] as const).map(x =>
          <Card key={x[0]}><span className="kpi-label">{x[0]}</span><div className="kpi-value">{x[1]} <i className={`dot ${x[2]}`}/></div></Card>)}
      </div>
      <Card><SectionTitle title="8D 결재 흐름" sub="D2 문제 기술 → D3 임시조치 → D4 원인 분석 · 앞 단계 승인 전에는 결재할 수 없습니다"/><Stages ctx={ctx}/></Card>
    </>}
    <Card className="mt"><SectionTitle title="배정된 사건" sub={`${cases.length}건 · 현재 사용자 기준`}/><div className="table-wrap"><table><thead><tr><th>사건 ID</th><th>도메인</th><th>데이터 출처</th></tr></thead>
      <tbody>{cases.map(c => <tr key={c.case_id}><td><b className="id">{c.case_id}</b></td><td>{c.domain}</td><td><Badge tone="blue">{c.data_origin}</Badge></td></tr>)}</tbody></table></div></Card>
  </Page>
}
