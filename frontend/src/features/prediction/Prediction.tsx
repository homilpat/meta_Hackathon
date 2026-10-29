import { useState } from 'react'
import { Badge, Card, Cite, Empty, Note, Page, SectionTitle } from '../../components/ui'
import { useLoad } from '../../hooks/useLoad'
import type { Ctx, J } from '../../types'

export function SteelReference({ ctx }: { ctx: Ctx }) {
  const r = useLoad<J>(ctx, '/reference-models/steel', null)
  if (!r) return null
  const m = r.metrics_test as Record<string, J>
  return <Card className="mt"><SectionTitle title="실제 공개 데이터 검증 · 강판 결함 유형 (REAL)" sub={`UCI Steel Plates Faults · ${r.rows.total}행 · 테스트 ${r.rows.test}행 · ${r.split}`} action={<Badge tone="blue">PCB 사건과 분리</Badge>}/>
    <Note>같은 방법(LightGBM + TreeSHAP + 기준선)을 실제 제조 검사 데이터에 적용한 결과입니다. 모든 행이 결함 판재라서 결함 <b>유형</b> 분류만 검증하며, 불량 검출률은 말하지 않습니다. 이 데이터는 사건이나 Meta 프롬프트에 들어가지 않습니다.</Note>
    <div className="table-wrap"><table><thead><tr><th>모델</th><th>정확도</th><th>macro F1</th><th>log loss</th></tr></thead><tbody>
      {Object.entries(m).map(([k, v]) => <tr key={k}><td><b>{k}</b></td><td>{v.accuracy}</td><td>{v.macro_f1}</td><td>{v.log_loss}</td></tr>)}</tbody></table></div>
    <div className="table-wrap"><table><thead><tr><th>결함 유형</th><th>F1</th><th>평균 |SHAP| 상위 특성 (모델 점수 설명, 원인 아님)</th></tr></thead><tbody>
      {Object.entries(r.lightgbm_per_class_f1 as Record<string, number>).map(([c, f]) => <tr key={c}><td>{c}</td><td>{f}</td>
        <td className="wrap">{(r.shap.top5_mean_abs_by_class[c] as [string, number][]).map(([n, v]) => `${n} ${v}`).join(' · ')}</td></tr>)}</tbody></table></div>
    <p className="muted">{r.attribution}</p></Card>
}

export function Prediction({ ctx }: { ctx: Ctx }) {
  const preds = useLoad<J[]>(ctx, `/cases/${ctx.cid}/predictions`, [])
  const [sel, setSel] = useState(0)
  const p = preds[Math.min(sel, preds.length - 1)]
  const score = async () => { await ctx.api('/models/train', 'POST', { seed: 11 }); await ctx.api(`/cases/${ctx.cid}/predictions`, 'POST', {}, true); ctx.refresh() }
  const contrib = p ? Object.entries(p.xai.contributions as Record<string, number>) : []
  const max = Math.max(1e-9, ...contrib.map(([, v]) => Math.abs(v)))
  return <Page title="품질 위험 예측 · XAI" desc="SPI 측정값만 입력으로 쓰는 위험 모델과 TreeSHAP 설명입니다." action={ctx.me?.role === 'AUTHOR' && <button className="button primary" onClick={score}>모델 학습 후 보드 점수 산출</button>}>
    {!p ? <Card><Empty>아직 예측이 없습니다.</Empty></Card> : <>
      <div className="context-strip"><div><span>보드</span><select value={sel} onChange={e => setSel(+e.target.value)}>{preds.map((x, i) => <option key={x.prediction_id} value={i}>{x.target_key.join('/')} · {x.evidence_id}</option>)}</select></div>
        <div><span>모델</span><b>{p.model.name} v{p.model.model_version_id} · {p.model.algorithm}</b></div><div><span>라벨</span><b>{p.model.label_kind}</b></div>
        <Badge tone={p.above_threshold ? 'amber' : 'green'}>{p.above_threshold ? '임계값 이상' : '임계값 미만'}</Badge></div>
      <div className="prediction-grid">
        <div className="stack">
          <Card><SectionTitle title="위험 점수" sub={`결정 임계값 ${p.threshold.toFixed(3)}`}/><div className="risk-panel"><div className="gauge"><svg viewBox="0 0 180 100"><path d="M20 90a70 70 0 0 1 140 0" className="gauge-bg"/><path d="M20 90a70 70 0 0 1 140 0" className="gauge-val" style={{ strokeDasharray: `${Math.round(220 * p.risk_score)} 220` }}/></svg><strong>{p.risk_score.toFixed(3)}</strong><span>모델 위험 점수</span></div></div></Card>
          <Card><SectionTitle title="SHAP 특성 기여도" sub={`기준값 ${p.xai.baseline.toFixed(3)} → 원점수 ${p.xai.raw_score.toFixed(3)} (log-odds) · 가법성 오차 ${p.xai.additivity_error.toExponential(1)}`}/>
            <div className="feature-list">{contrib.map(([k, v]) => { const tone = v >= 0 ? 'red' : 'blue'
              return <div className="feature" key={k}><span>{k} = {Number(p.features[k]).toFixed(4)}</span><div><i className={tone} style={{ width: `${Math.round(100 * Math.abs(v) / max)}%` }}/></div><b className={tone}>{v >= 0 ? '+' : ''}{v.toFixed(3)}</b></div> })}</div>
            <Note><b>해석 주의</b> {p.note}</Note></Card>
        </div>
        <Card className="evidence-side"><SectionTitle title="예측 근거 정보" sub="재현 가능한 실행 기록"/>
          {[['예측 Evidence', p.evidence_id], ['XAI Evidence', p.xai_evidence_id], ['XAI 방법', p.xai.method], ['입력 해시', `${p.input_sha256.slice(0, 16)}…`], ['모델 아티팩트', `${p.model.artifact_sha256.slice(0, 16)}…`], ['실행 시각', p.created_at.slice(0, 19)]].map(x =>
            <div className="detail-row" key={x[0]}><span>{x[0]}</span><b>{x[1]}</b></div>)}
          <div className="divider"/><SectionTitle title="입력 Evidence" sub={`${p.input_evidence_ids.length}개 SPI 행`}/><Cite ids={p.input_evidence_ids}/></Card>
      </div></>}
    <SteelReference ctx={ctx}/>
  </Page>
}
