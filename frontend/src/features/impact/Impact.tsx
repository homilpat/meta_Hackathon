import { useState } from 'react'
import { Badge, Card, Empty, Icon, Page, SectionTitle, evidenceName } from '../../components/ui'
import { say } from '../../labels'
import { useLoad } from '../../hooks/useLoad'
import type { Ctx, J } from '../../types'

export function Impact({ ctx }: { ctx: Ctx }) {
  const impacts = useLoad<J[]>(ctx, `/cases/${ctx.cid}/change-impact`, [])
  const sources = useLoad<J[]>(ctx, `/cases/${ctx.cid}/sources`, [])
  const events = useLoad<J[]>(ctx, `/cases/${ctx.cid}/events?entity_type=spi_measurements`, [])
  const rows = [...new Set(events.map(e => e.original_row_id))].sort()
  const [pick, setRow] = useState('SPI-P02-B01-1')
  const row = rows.includes(pick) ? pick : rows[0] ?? pick
  const line = sources.some(s => s.source_system === 'SYNTHETIC_LOTS')
  const imp = impacts[impacts.length - 1]
  const fix = async () => {
    const spi = sources.filter(s => s.source_system === 'SYNTHETIC_SPI_MEASUREMENTS')
    if (!spi.length) return
    const version = Math.max(...spi.map(s => s.source_version)) + 1
    const asset = await (await fetch(`/synthetic/7/spi-correction?row_id=${row}&version=${version}&line=${line}`)).json()
    await ctx.api(`/cases/${ctx.cid}/source-revisions`, 'POST', { asset, reason: `SPI 재측정 ${row}` }, true); ctx.refresh()
  }
  const col = (title: string, items: string[], tone: string) => <div className="graph-col"><small>{title}</small>{items.length ? items.map(i => <div className={`node-box ${tone}`} key={i}>{i}</div>) : <span className="muted">없음</span>}</div>
  return <Page title="증거 변경 영향 분석" desc="원본 기록이 정정되면, 그 기록을 쓴 문서만 다시 검토하도록 돌립니다."
    action={ctx.me?.role === 'AUTHOR' && <span className="row-gap"><select value={row} onChange={e => setRow(e.target.value)}>{rows.map(r => <option key={r}>{r}</option>)}</select><button className="button primary" onClick={fix}>SPI 정정 가져오기</button></span>}>
    {!imp ? <Card><Empty>아직 원본 정정 기록이 없습니다.</Empty></Card> : <>
      <div className="revision-alert"><Icon name="warning"/><div><b>{imp.reason}</b><span>{imp.actor_id} · {imp.created_at.slice(0, 19)}</span></div></div>
      <div className="impact-layout">
        <Card><SectionTitle title="문서 상태 변화" sub="정정 전 → 후"/>{imp.documents.length ? imp.documents.map((d: J) =>
          <div key={d.document_version_id} className="compare-row amber"><span>{d.doc_type} v{d.version}</span><del>{say(d.status_before)}</del><Icon name="arrow"/><b>{say(d.status_after)}</b></div>) : <Empty>이 행에 의존하는 문서가 없어 재검토 대상이 없습니다.</Empty>}
          {(imp.basis_changed ?? []).map((d: J) => <div key={d.document_version_id} className="compare-row amber"><span>{d.doc_type} v{d.version} (기반 변경)</span><del>{say(d.status_before)}</del><Icon name="arrow"/><b>{say(d.status_after)}</b></div>)}</Card>
        <Card className="graph-card"><SectionTitle title="영향 경로" sub="정정된 기록에서 문서까지"/><div className="graph-cols">
          {col('정정된 기록', imp.changed_evidence.map(evidenceName), 'affected')}{col('다시 계산된 예측', imp.derived, 'affected')}
          {col('주장', [...imp.claims].sort((a: string, b: string) => { const [, da, ca] = a.split(':'), [, db, cb] = b.split(':'); return +da - +db || +ca.slice(1) - +cb.slice(1) }).map((c: string) => { const [, id, cl] = c.split(':'); const d = imp.documents.find((x: J) => String(x.document_version_id) === id); return `${d ? `${d.doc_type} v${d.version}` : id} · ${cl}` }), 'critical')}
          {col('문서', imp.documents.map((d: J) => `${d.doc_type} v${d.version}`), 'affected')}</div></Card>
        <Card><SectionTitle title="정정 이력" action={<Badge tone="amber">{impacts.length}건</Badge>}/>{impacts.slice().reverse().map(i =>
          <div className="impact-item" key={i.impact_id}><b>{i.reason}</b><span>{i.created_at.slice(0, 16).replace('T', ' ')} · 문서 {i.documents.length}개 · 주장 {i.claims.length}개</span></div>)}</Card>
      </div></>}
  </Page>
}
