import { useState } from 'react'
import { Badge, Card, Cite, Empty, Page, SectionTitle } from '../../components/ui'
import { useLoad } from '../../hooks/useLoad'
import type { Ctx, J } from '../../types'

export function SteelReference({ ctx }: { ctx: Ctx }) {
  const r = useLoad<J>(ctx, '/reference-models/steel', null)
  if (!r) return null
  const m = r.metrics_test as Record<string, J>
  return <Card className="mt"><SectionTitle title="공개 데이터로 본 예측 성능 · 강판 결함 유형" sub={`UCI Steel Plates Faults · ${r.rows.total}행 중 ${r.rows.test}행으로 시험`}/>
    <div className="table-wrap"><table><thead><tr><th>모델</th><th>정확도</th><th>macro F1</th><th>log loss</th></tr></thead><tbody>
      {Object.entries(m).map(([k, v]) => <tr key={k}><td><b>{k}</b></td><td>{v.accuracy}</td><td>{v.macro_f1}</td><td>{v.log_loss}</td></tr>)}</tbody></table></div>
    <div className="table-wrap"><table><thead><tr><th>결함 유형</th><th>F1</th><th>점수에 크게 작용한 값</th></tr></thead><tbody>
      {Object.entries(r.lightgbm_per_class_f1 as Record<string, number>).map(([c, f]) => <tr key={c}><td>{c}</td><td>{f}</td>
        <td className="wrap">{(r.shap.top5_mean_abs_by_class[c] as [string, number][]).map(([n, v]) => `${n} ${v}`).join(' · ')}</td></tr>)}</tbody></table></div>
</Card>
}

export function Prediction({ ctx }: { ctx: Ctx }) {
  const preds = useLoad<J[]>(ctx, `/cases/${ctx.cid}/predictions`, [])
  const [sel, setSel] = useState(0)
  const p = preds[Math.min(sel, preds.length - 1)]
  const score = async () => { await ctx.api('/models/train', 'POST', { seed: 11 }); await ctx.api(`/cases/${ctx.cid}/predictions`, 'POST', {}, true); ctx.refresh() }
  const contrib = p ? Object.entries(p.xai.contributions as Record<string, number>) : []
  const max = Math.max(1e-9, ...contrib.map(([, v]) => Math.abs(v)))
  return <Page title="품질 위험 예측" desc="SPI 측정값으로 보드별 불량 위험을 예측하고, 어떤 값이 점수를 올렸는지 보여 줍니다." action={ctx.me?.role === 'AUTHOR' && <button className="button primary" onClick={score}>모델 학습 후 보드 점수 산출</button>}>
    {!p ? <Card><Empty>아직 예측이 없습니다.</Empty></Card> : <>
      <div className="context-strip"><div><span>보드</span><select value={sel} onChange={e => setSel(+e.target.value)}>{preds.map((x, i) => <option key={x.prediction_id} value={i}>{x.target_key.join('/')}</option>)}</select></div>
        <div><span>모델</span><b>{p.model.algorithm}</b></div>
        <Badge tone={p.above_threshold ? 'amber' : 'green'}>{p.above_threshold ? '기준 이상' : '기준 미만'}</Badge></div>
      <div className="prediction-grid">
        <div className="stack">
          <Card><SectionTitle title="위험 점수" sub={`기준 ${p.threshold.toFixed(3)}`}/><div className="risk-panel"><div className="gauge"><svg viewBox="0 0 180 100"><path d="M20 90a70 70 0 0 1 140 0" className="gauge-bg"/><path d="M20 90a70 70 0 0 1 140 0" className="gauge-val" style={{ strokeDasharray: `${Math.round(220 * p.risk_score)} 220` }}/></svg><strong>{p.risk_score.toFixed(3)}</strong><span>모델 위험 점수</span></div></div></Card>
          <Card><SectionTitle title="점수에 작용한 값" sub="빨강은 점수를 올린 값, 파랑은 내린 값"/>
            <div className="feature-list">{contrib.map(([k, v]) => { const tone = v >= 0 ? 'red' : 'blue'
              return <div className="feature" key={k}><span>{k} = {Number(p.features[k]).toFixed(4)}</span><div><i className={tone} style={{ width: `${Math.round(100 * Math.abs(v) / max)}%` }}/></div><b className={tone}>{v >= 0 ? '+' : ''}{v.toFixed(3)}</b></div> })}</div></Card>
        </div>
        <Card className="evidence-side"><SectionTitle title="예측 정보"/>
          {[['모델', `${p.model.name} v${p.model.model_version_id}`], ['예측 시각', p.created_at.slice(0, 16).replace('T', ' ')]].map(x =>
            <div className="detail-row" key={x[0]}><span>{x[0]}</span><b>{x[1]}</b></div>)}
          <div className="divider"/><SectionTitle title="입력한 측정값"/><Cite ids={p.input_evidence_ids}/></Card>
      </div></>}
    <SteelReference ctx={ctx}/>
  </Page>
}
