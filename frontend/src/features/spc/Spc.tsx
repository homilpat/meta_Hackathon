import { useState } from 'react'
import { Badge, Card, Empty, Icon, Note, Page, SectionTitle } from '../../components/ui'
import { useLoad } from '../../hooks/useLoad'
import type { Ctx, J } from '../../types'

// X-bar chart: limits from the reference lot (phase I); signals in later lots open a case, they do not prove a defect.
export function ControlChart({ m }: { m: J }) {
  const pts = m.points as J[], L = m.limits, W = 960, H = 240, pad = 34
  const ys = [...pts.map(p => p.xbar), L.ucl, L.lcl], lo = Math.min(...ys) - 0.002, hi = Math.max(...ys) + 0.002
  const x = (i: number) => pad + (i / (pts.length - 1)) * (W - pad - 8), y = (v: number) => 8 + (hi - v) / (hi - lo) * (H - 30)
  const starts = pts.map((p, i) => [p.lot, i] as [string, number]).filter(([l], i) => !i || pts[i - 1].lot !== l)
  const hline = (v: number, label: string, dash: boolean) => <g key={label}><line x1={pad} x2={W - 8} y1={y(v)} y2={y(v)} stroke={dash ? 'var(--red)' : 'var(--slate)'} strokeDasharray={dash ? '5 4' : undefined} strokeWidth={1}/>
    <text x={2} y={y(v) + 3} fontSize={9} fill="var(--muted)">{label}</text></g>
  return <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto' }} role="img" aria-label="SPI X-bar control chart">
    {starts.map(([l, i]) => <g key={l}><line x1={x(i)} x2={x(i)} y1={4} y2={H - 20} stroke="var(--line)"/><text x={x(i) + 4} y={H - 6} fontSize={10} fill="var(--slate)">{l}{l === m.reference_lot ? ' (기준)' : ''}</text></g>)}
    {hline(L.ucl, 'UCL', true)}{hline(L.cl, 'CL', false)}{hline(L.lcl, 'LCL', true)}
    <polyline points={pts.map((p, i) => `${x(i)},${y(p.xbar)}`).join(' ')} fill="none" stroke="var(--blue)" strokeWidth={1.2} opacity={0.6}/>
    {pts.map((p, i) => <circle key={i} cx={x(i)} cy={y(p.xbar)} r={p.rules.length && p.phase === 'II' ? 3.6 : 2.4}
      fill={p.rules.length && p.phase === 'II' ? 'var(--red)' : 'var(--blue)'}><title>{`${p.panel}/${p.board} X̄ ${p.xbar} R ${p.r}${p.rules.length ? ' · ' + p.rules.join(', ') : ''}`}</title></circle>)}
  </svg>
}

export function Spc({ ctx }: { ctx: Ctx }) {
  const m = useLoad<J>(ctx, ctx.cid ? `/cases/${ctx.cid}/spc` : null, null)
  const [last, setLast] = useState<J>(null)
  const replay = async () => {
    const r = await ctx.api('/monitoring/line-replay', 'POST', { seed: 7 })
    setLast(r); if (r.case_id) ctx.open(r.case_id, '', 'spc')
  }
  const lead = last?.first_confirmed_defect_in_lot && Math.round((Date.parse(last.first_confirmed_defect_in_lot) - Date.parse(last.alarm.t)) / 60000)
  return <Page title="SPC 라인 모니터링" desc="SPI 솔더 체적을 보드 단위(핀 8개) X̄-R 관리도로 감시합니다. 기준 lot으로 관리한계를 잡고, 이후 lot의 Western Electric 규칙 위반이 첫 경보가 되면 사건을 자동으로 엽니다."
    action={ctx.me?.role === 'AUTHOR' && <button className="button primary" onClick={replay}>라인 이벤트 재생 → 경보 시 사건 자동 생성</button>}>
    {last && <div className="revision-alert"><Icon name="warning"/><div><b>{last.case_id ? `사건 ${last.case_id} 자동 생성` : '경보 없음'}</b><span>{last.detail}{lead != null && ` · 같은 lot의 첫 AOI 불량 확인보다 ${lead}분 먼저`}</span></div></div>}
    {!m ? <Card><Empty>현재 사건에 lot 추적 SPI 데이터가 없습니다. 작성자 계정으로 라인 이벤트를 재생하거나 SMT 라인 사건을 만드세요.</Empty></Card> : <>
      <Card className="mb"><SectionTitle title="X̄ 관리도 · SPI 체적 (mm³)" sub={`기준 lot ${m.reference_lot} · n=${m.n} · CL ${m.limits.cl} · LCL ${m.limits.lcl} · UCL ${m.limits.ucl} · R̄ ${m.limits.rbar}`}
        action={m.first_alarm && <Badge tone="red">첫 경보 {m.first_alarm.panel}/{m.first_alarm.board} · {m.first_alarm.rules.join(', ')}</Badge>}/>
        <ControlChart m={m}/>
        <Note>관리도 신호는 공정이 기준에서 벗어났다는 통계적 신호입니다. 불량 판정도 원인 확정도 아니며, 원인은 D4에서 공정 엔지니어가 검증 근거로만 확정합니다.</Note></Card>
      <Card><SectionTitle title="Lot별 공정능력 · 신호" sub={`가상 규격 ${m.spec[0]}–${m.spec[1]} mm³ · Cpk는 보드 내 산포(R̄/d2) 기준`}/><div className="table-wrap"><table><thead><tr><th>Lot</th><th>보드</th><th>평균 체적</th><th>Cpk</th><th>규칙 위반 보드</th><th>첫 신호</th></tr></thead><tbody>
        {Object.entries(m.lots as Record<string, J>).map(([l, v]) => <tr key={l}><td><b className="id">{l}</b>{l === m.reference_lot && ' (기준)'}</td><td>{v.boards}</td><td>{v.mean}</td>
          <td><Badge tone={v.cpk < 1.33 ? 'amber' : 'green'}>{v.cpk}</Badge></td><td>{v.alarms}</td>
          <td className="wrap">{v.first_alarm ? `${v.first_alarm.panel}/${v.first_alarm.board} · ${v.first_alarm.rules.map((r: string) => `${r} (${m.rules[r]})`).join(', ')}` : '-'}</td></tr>)}
      </tbody></table></div></Card></>}
  </Page>
}
