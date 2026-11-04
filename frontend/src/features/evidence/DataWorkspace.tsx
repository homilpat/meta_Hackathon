import { Badge, Card, Icon, Page, SectionTitle } from '../../components/ui'
import { useLoad } from '../../hooks/useLoad'
import { say } from '../../labels'
import type { Ctx, J, Tone } from '../../types'

export function DataWorkspace({ ctx }: { ctx: Ctx }) {
  const p = (x: string) => `/cases/${ctx.cid}/${x}`
  const sources = useLoad<J[]>(ctx, p('sources'), []), issues = useLoad<J[]>(ctx, p('data-issues'), []), events = useLoad<J[]>(ctx, p('events'), [])
  const aoi = events.filter(e => e.entity_type === 'aoi_inspections')
  const human = (e: J) => events.find(h => h.entity_type === 'human_verifications' && h.entity_key.join('/') === e.entity_key.join('/') && h.record.inspection_id === e.record.inspection_id)
  const counts: Record<string, number> = {}
  for (const i of issues) counts[i.code] = (counts[i.code] || 0) + 1
  const lots = events.filter(e => e.entity_type === 'lots').map(l => {
    const panels = new Set(events.filter(e => e.entity_type === 'panels' && e.record.lot_id === l.record.lot_id).map(e => e.entity_key[0]))
    const fails = aoi.filter(e => panels.has(e.entity_key[0]) && e.record.result === 'FAIL')
    const ship = events.filter(e => e.entity_type === 'shipments' && e.record.lot_id === l.record.lot_id)
    return { l, panels: panels.size, aoi: aoi.filter(e => panels.has(e.entity_key[0])).length, fails: fails.length,
      open: fails.filter(e => human(e)?.record.result !== 'FALSE_ALARM').length, shipped: ship.filter(s => s.record.status === 'SHIPPED').length, wip: ship.filter(s => s.record.status !== 'SHIPPED').length }
  })
  return <Page title="제조 데이터 및 증거" desc="사건에 연결된 원본 자료와 검사 결과입니다.">
    <div className="source-grid">{sources.map(s => <Card key={s.asset_id}><div className="source-head"><div className="source-icon"><Icon name="database"/></div><Badge tone={s.supersedes_asset_id ? 'amber' : 'green'}>{s.supersedes_asset_id ? '정정본' : `v${s.source_version}`}</Badge></div>
      <b>{say(s.source_system)}</b><span className="muted">{say(s.data_origin)}</span></Card>)}</div>
    {lots.length > 0 && <Card className="mb"><SectionTitle title="LOT 추적" sub="미해소는 오검출로 판정되지 않은 AOI 불합격입니다"/><div className="table-wrap"><table><thead><tr><th>Lot</th><th>라인 / 스텐실 / 페이스트</th><th>패널</th><th>AOI 검사</th><th>FAIL</th><th>미해소</th><th>출하 / 재공</th></tr></thead><tbody>
      {lots.map(x => <tr key={x.l.event_id}><td><b className="id">{x.l.record.lot_id}</b></td><td>{x.l.record.line_id} · {x.l.record.stencil_id} · {x.l.record.paste_lot}</td><td>{x.panels}</td><td>{x.aoi}</td><td>{x.fails}</td>
        <td><Badge tone={x.open ? 'red' : 'green'}>{x.open}</Badge></td><td>{x.shipped} / {x.wip}</td></tr>)}</tbody></table></div></Card>}
    <div className="split-main">
      <Card><SectionTitle title="데이터 품질 이슈" action={<Badge tone={issues.length ? 'amber' : 'green'}>{issues.length}건</Badge>}/>
        <div className="meta-list">{Object.entries(counts).map(([k, n]) => <div key={k}><span>{say(k)}</span><b>{n}</b></div>)}</div></Card>
      <Card><SectionTitle title="검사 결과 비교" sub="AOI 판정과 작업자 확인 기록"/><div className="table-wrap"><table><thead><tr><th>패널/보드</th><th>검사 ID</th><th>AOI 결과</th><th>작업자 확인</th><th>구분</th></tr></thead><tbody>
        {aoi.map(e => { const h = human(e); const v = h?.record.result
          const [label, tone]: [string, Tone] = !h ? ['작업자 확인 없음', 'slate'] : e.record.result === 'FAIL' && v === 'FALSE_ALARM' ? ['판정 불일치 (오검출)', 'amber'] : e.record.result === 'FAIL' ? ['불량 확인', 'red'] : ['일치', 'green']
          return <tr key={e.event_id}><td><b>{e.entity_key.join('/')}</b></td><td>{e.record.inspection_id}</td><td>{say(e.record.result)}</td><td>{v ? say(v) : '-'}</td><td><Badge tone={tone}>{label}</Badge></td></tr> })}
      </tbody></table></div></Card>
    </div>
  </Page>
}
