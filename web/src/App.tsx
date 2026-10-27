import { useCallback, useEffect, useState, type ReactNode } from 'react'

// Every value on screen comes from the QualityOps API. Nothing here is a hard-coded result.
type Tone = 'teal' | 'green' | 'amber' | 'red' | 'blue' | 'slate' | 'violet'
type J = any // eslint-disable-line @typescript-eslint/no-explicit-any

const USERS = [
  ['alice', '작성자 Alice', 'AUTHOR'], ['dave', '작성자 Dave', 'AUTHOR'], ['bob', 'NCR 검토자 Bob', 'REVIEWER'],
  ['carol', 'NCR 검토자 Carol', 'REVIEWER'], ['erin', 'QA/생산 Erin', 'QA_PRODUCTION'], ['frank', '공정 엔지니어 Frank', 'PROCESS_ENGINEER'],
] as const
const KINDS = [['ncr', 'NCR', 'D2 부적합 보고서', 'bob'], ['containment', 'CONTAINMENT', 'D3 임시조치 계획', 'erin'], ['rca', 'RCA', 'D4 원인 가설', 'frank']] as const
const APPROVER_ROLE: Record<string, string> = { NCR: 'REVIEWER', CONTAINMENT: 'QA_PRODUCTION', RCA: 'PROCESS_ENGINEER' }

const nav = [
  ['dashboard', '개요', 'grid'], ['queue', '할 일', 'check'], ['data', '제조 데이터 · 증거', 'database'], ['prediction', '품질 예측 · XAI', 'chart'],
  ['investigation', 'AI 품질 조사', 'spark'], ['history', '과거 품질 사례', 'history'], ['reports', '문서 · 결재', 'document'],
  ['impact', '변경 영향 분석', 'nodes'], ['audit', '감사 · 보안', 'shield'],
] as const

const CLASS_TONE: Record<string, Tone> = { OBSERVED: 'green', CALCULATED: 'blue', HYPOTHESIS: 'violet', UNKNOWN: 'slate', PROPOSAL: 'teal' }
const STATUS_TONE: Record<string, Tone> = {
  DRAFT: 'slate', IN_REVIEW: 'amber', APPROVED: 'green', REJECTED: 'red', INFO_REQUESTED: 'amber', SUPERSEDED: 'slate',
  REVALIDATION_REQUIRED: 'red', BASIS_CHANGED: 'amber', VALIDATED: 'green', VALIDATION_FAILED: 'red', FAILED: 'red', JSON_ERROR: 'red', LIMIT_EXCEEDED: 'amber',
}

const uid = () => crypto.randomUUID()

function Icon({ name, size = 18 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    grid: <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
    database: <><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7"/></>,
    chart: <><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></>,
    spark: <><path d="m12 2 1.7 6.3L20 10l-6.3 1.7L12 18l-1.7-6.3L4 10l6.3-1.7z"/><path d="m19 16 .7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7z"/></>,
    history: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/></>,
    document: <><path d="M6 2h9l4 4v16H6z"/><path d="M14 2v5h5M9 12h6M9 16h6"/></>,
    nodes: <><circle cx="5" cy="12" r="3"/><circle cx="19" cy="5" r="3"/><circle cx="19" cy="19" r="3"/><path d="m8 11 8-4M8 13l8 4"/></>,
    shield: <><path d="M12 2 20 5v6c0 5-3.4 9-8 11-4.6-2-8-6-8-11V5z"/><path d="m8 12 2.5 2.5L16 9"/></>,
    chevron: <path d="m9 18 6-6-6-6"/>,
    check: <path d="m5 12 4 4L19 6"/>,
    warning: <><path d="M12 3 2 21h20z"/><path d="M12 9v5M12 18h.01"/></>,
    arrow: <><path d="M5 12h14M14 7l5 5-5 5"/></>,
  }
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}
const Badge = ({ children, tone = 'slate' }: { children: ReactNode; tone?: Tone }) => <span className={`badge badge-${tone}`}>{children}</span>
const Card = ({ children, className = '' }: { children: ReactNode; className?: string }) => <section className={`card ${className}`}>{children}</section>
const SectionTitle = ({ title, sub, action }: { title: string; sub?: string; action?: ReactNode }) =>
  <div className="section-title"><div><strong>{title}</strong>{sub && <span>{sub}</span>}</div>{action}</div>
const Empty = ({ children }: { children: ReactNode }) => <p className="muted">{children}</p>
const Note = ({ children }: { children: ReactNode }) => <div className="science-note"><Icon name="warning"/><span>{children}</span></div>
const Cite = ({ ids }: { ids: string[] }) => <>{ids.length ? ids.map(i => <span className="citation" key={i}>{i}</span>) : <span className="muted">-</span>}</>

function Page({ title, desc, action, children }: { title: string; desc: string; action?: ReactNode; children: ReactNode }) {
  return <main className="page"><div className="page-head"><div><h1>{title}</h1><p>{desc}</p></div>{action}</div>{children}</main>
}

type Ctx = { cid: string; me: J; api: (path: string, method?: string, body?: unknown, idem?: boolean) => Promise<J>; refresh: () => void; tick: number
  open: (cid: string, sel: string) => void; focus: string }

function useLoad<T>(ctx: Ctx, path: string | null, init: T): T {
  const [v, setV] = useState<T>(init)
  useEffect(() => { // reload per user/case; ignore a late answer from a previous user or case
    let live = true
    if (path) ctx.api(path).then(x => live && setV(x)).catch(() => live && setV(init))
    return () => { live = false }
  }, [path, ctx.tick, ctx.api]) // eslint-disable-line react-hooks/exhaustive-deps
  return v
}

// 8D order from the API: drafts can be written ahead, review/approval opens only after the step before is APPROVED.
function Stages({ ctx }: { ctx: Ctx }) {
  const st = useLoad<J[]>(ctx, `/cases/${ctx.cid}/stages`, [])
  return <div className="report-steps">{st.map(s => {
    const done = s.status === 'APPROVED'
    return <div key={s.kind} title={s.blocked_by ?? ''} className={done ? 'done' : s.approval_open ? 'active' : 'future'}><i>{done ? <Icon name="check" size={13}/> : s.step}</i>
      <span>{KINDS.find(k => k[0] === s.kind)![2]}</span><small>{s.version ? `v${s.version} · ${s.status}` : '미작성'}{!s.approval_open && ' · 결재 잠금 (앞 단계 미승인)'}</small></div>
  })}</div>
}

const TASK: Record<string, [string, Tone]> = {
  REVIEW: ['결재 검토', 'amber'], BASIS_CHECK: ['기반 변경 확인', 'amber'], SEND_FOR_REVIEW: ['검토 요청 가능', 'teal'],
  WAITING_UPSTREAM: ['앞 단계 승인 대기', 'slate'], REDRAFT: ['재작성 필요', 'red'], ANSWER_COMMENT: ['코멘트 답변', 'violet'],
}

function Queue({ ctx }: { ctx: Ctx }) {
  const [scope, setScope] = useState<'department' | 'mine'>('mine')
  const items = useLoad<J[]>(ctx, `/queue?scope=${scope}`, [])
  const role = ctx.me?.role
  return <Page title={scope === 'mine' ? '내 할 일' : '부서 할 일'} desc={scope === 'mine'
    ? `${ctx.me?.id ?? '-'}님이 담당자인 일: 지정된 검토, 내가 승인한 문서의 기반 확인, 내 문서의 재작성·코멘트 답변.`
    : `${role ?? '-'} 역할 전체가 볼 일입니다. 배정된 사건 기준이며, 담당자가 비어 있으면 부서 누구나 처리할 수 있습니다.`}
    action={<span className="row-gap"><button className={`button ${scope === 'mine' ? 'primary' : 'secondary'}`} onClick={() => setScope('mine')}>내 할 일</button>
      <button className={`button ${scope === 'department' ? 'primary' : 'secondary'}`} onClick={() => setScope('department')}>부서 할 일</button></span>}>
    <Card><SectionTitle title="열린 작업" sub={`${items.length}건`}/><div className="table-wrap"><table><thead><tr><th>사건</th><th>문서</th><th>상태</th><th>할 일</th><th>담당</th><th>내용</th><th/></tr></thead><tbody>
      {items.map((i, n) => <tr key={n}><td><b className="id">{i.case_id}</b></td><td>{i.doc_type} v{i.version}</td><td><Badge tone={STATUS_TONE[i.status]}>{i.status}</Badge></td>
        <td><Badge tone={TASK[i.task]?.[1] ?? 'slate'}>{TASK[i.task]?.[0] ?? i.task}</Badge></td><td>{i.owner ?? '부서'}</td><td className="wrap">{i.detail || '-'}</td>
        <td><button className="citation" onClick={() => ctx.open(i.case_id, `${i.kind}:${i.version}`)}>열기</button></td></tr>)}
    </tbody></table></div>{!items.length && <Empty>열린 작업이 없습니다.</Empty>}</Card>
  </Page>
}

function Dashboard({ ctx, cases, onNew }: { ctx: Ctx; cases: J[]; onNew: () => void }) {
  const p = (x: string) => ctx.cid ? `/cases/${ctx.cid}/${x}` : null
  const ev = useLoad<J[]>(ctx, p('evidence'), []), iss = useLoad<J[]>(ctx, p('data-issues'), [])
  const preds = useLoad<J[]>(ctx, p('predictions'), []), runs = useLoad<J[]>(ctx, p('investigations'), [])
  const docs = [useLoad<J[]>(ctx, p('ncr'), []), useLoad<J[]>(ctx, p('containment'), []), useLoad<J[]>(ctx, p('rca'), [])]
  const reval = docs.flat().filter(d => d.status === 'REVALIDATION_REQUIRED' || d.status === 'BASIS_CHANGED').length
  return <Page title="품질 운영 현황" desc="선택한 사건의 근거, 모델 출력, 문서 결재 상태를 확인합니다." action={ctx.me?.role === 'AUTHOR' && <button className="button primary" onClick={onNew}>새 합성 PCB 사건 생성</button>}>
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

function DataWorkspace({ ctx }: { ctx: Ctx }) {
  const p = (x: string) => `/cases/${ctx.cid}/${x}`
  const sources = useLoad<J[]>(ctx, p('sources'), []), issues = useLoad<J[]>(ctx, p('data-issues'), []), events = useLoad<J[]>(ctx, p('events'), [])
  const aoi = events.filter(e => e.entity_type === 'aoi_inspections')
  const human = (e: J) => events.find(h => h.entity_type === 'human_verifications' && h.entity_key.join('/') === e.entity_key.join('/') && h.record.inspection_id === e.record.inspection_id)
  const counts: Record<string, number> = {}
  for (const i of issues) counts[i.code] = (counts[i.code] || 0) + 1
  return <Page title="제조 데이터 및 증거" desc="원천 자산의 버전·해시·권리 정보와 검사 결과를 확인합니다.">
    <div className="source-grid">{sources.map(s => <Card key={s.asset_id}><div className="source-head"><div className="source-icon"><Icon name="database"/></div><Badge tone={s.supersedes_asset_id ? 'amber' : 'green'}>{s.supersedes_asset_id ? '정정본' : `v${s.source_version}`}</Badge></div>
      <b>{s.source_system}</b><span className="muted">{s.asset_id}</span><span className="muted">{s.license_id} · {s.data_origin} · {s.sensitivity}</span><span className="muted">sha256 {s.content_sha256.slice(0, 12)}…</span></Card>)}</div>
    <div className="split-main">
      <Card><SectionTitle title="데이터 품질 이슈" sub="결정적 규칙으로 탐지 · 원인 판단 아님" action={<Badge tone={issues.length ? 'amber' : 'green'}>{issues.length}건</Badge>}/>
        <div className="meta-list">{Object.entries(counts).map(([k, n]) => <div key={k}><span>{k}</span><b>{n}</b></div>)}</div></Card>
      <Card><SectionTitle title="검사 결과 비교" sub="AOI 판정과 작업자 확인 기록"/><div className="table-wrap"><table><thead><tr><th>패널/보드</th><th>검사 ID</th><th>AOI 결과</th><th>작업자 확인</th><th>구분</th></tr></thead><tbody>
        {aoi.map(e => { const h = human(e); const v = h?.record.result
          const [label, tone]: [string, Tone] = !h ? ['작업자 확인 없음', 'slate'] : e.record.result === 'FAIL' && v === 'FALSE_ALARM' ? ['판정 불일치 (오검출)', 'amber'] : e.record.result === 'FAIL' ? ['불량 확인', 'red'] : ['일치', 'green']
          return <tr key={e.event_id}><td><b>{e.entity_key.join('/')}</b></td><td>{e.record.inspection_id}</td><td>{e.record.result}</td><td>{v ?? '-'}</td><td><Badge tone={tone}>{label}</Badge></td></tr> })}
      </tbody></table></div></Card>
    </div>
  </Page>
}

function SteelReference({ ctx }: { ctx: Ctx }) {
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

function Prediction({ ctx }: { ctx: Ctx }) {
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

function Investigation({ ctx, provider }: { ctx: Ctx; provider: J }) {
  const runs = useLoad<J[]>(ctx, `/cases/${ctx.cid}/investigations`, [])
  const [history, setHistory] = useState(true)
  const r = runs[runs.length - 1]
  const author = ctx.me?.role === 'AUTHOR'
  const run = async () => { await ctx.api(`/cases/${ctx.cid}/investigations`, 'POST', { use_history: history }, true); ctx.refresh() }
  const draft = async (k: string) => { await ctx.api(`/cases/${ctx.cid}/${k}`, 'POST', { investigation_run_id: r.run_id }, true); ctx.refresh() }
  return <Page title="AI 품질 조사" desc="Meta 모델이 읽기 전용 도구로 근거를 조회하고, 서버가 보고서를 검증합니다.">
    <div className="hero-banner"><div className="hero-icon"><Icon name="spark" size={22}/></div><div><b>{provider?.configured ? `LIVE · ${provider.model}` : `${provider?.model ?? 'Meta'} · 키 미설정`}</b>
      <span>{provider?.configured ? 'SYNTHETIC·외부 승인 데이터만 전송됩니다. 결론 승인과 원인 확정은 사람이 합니다.' : 'MODEL_API_KEY가 없어 조사를 실행할 수 없습니다. 대체(목) 응답은 없습니다.'}</span></div>
      <label className="muted"><input type="checkbox" checked={history} onChange={e => setHistory(e.target.checked)}/> 과거 사례 사용 (History ON)</label>
      <button className="button primary" disabled={!author || !provider?.configured} onClick={run}>조사 실행</button></div>
    {!r ? <Card><Empty>이 사건의 조사 실행 기록이 없습니다.</Empty></Card> : <div className="workbench">
      <div className="stack"><Card><SectionTitle title="실행 정보"/>{[['실행', `Run ${r.run_id}`], ['모드', r.mode === 'LIVE' ? 'LIVE Meta 호출' : 'TEST DOUBLE (Meta 아님)'], ['모델', r.model], ['History', r.history], ['라운드', r.rounds], ['토큰', `${r.prompt_tokens}/${r.completion_tokens}`]].map(x =>
        <div className="detail-row" key={x[0]}><span>{x[0]}</span><b>{x[1]}</b></div>)}<div className="divider"/><Badge tone={STATUS_TONE[r.status] ?? 'slate'}>{r.status}</Badge>{r.error && <p className="muted">{r.error}</p>}</Card></div>
      <div className="stack center-col">
        <Card className="ai-summary"><div className="ai-head"><div className="hero-icon"><Icon name="spark"/></div><div><b>조사 요약</b><span>{r.started_at.slice(0, 19)} · 도구 호출 {r.tool_calls.length}회</span></div></div><p>{r.report?.summary ?? '보고서 없음'}</p></Card>
        <Card><SectionTitle title="도구 실행 타임라인" sub="결과 본문 대신 해시만 기록"/><div className="tool-timeline">{r.tool_calls.map((c: J, i: number) =>
          <div className="tool-item" key={i}><i className={c.ok ? 'green' : 'amber'}>{c.ok && <Icon name="check" size={12}/>}</i><time>R{c.round}</time><div><b>{c.tool_name}</b><span>{c.ok ? `sha256 ${c.result_sha256?.slice(0, 12)}…` : c.error}</span></div></div>)}</div></Card>
        {r.report?.next_evidence_requests?.length > 0 && <Card className="recommend"><SectionTitle title="다음 증거 요청" sub="조치 권고가 아닌 확인 요청"/>{r.report.next_evidence_requests.map((n: J, i: number) =>
          <div className="rec-row" key={i}><b className="rank">{i + 1}</b><div><strong>{n.check}</strong><span>{n.reason}</span><small>{[...(n.evidence_ids ?? []), ...(n.precedent_ids ?? [])].join(' · ')}</small></div></div>)}</Card>}
      </div>
      <div className="stack">
        <Card><SectionTitle title="주장별 근거 수준"/>{(r.report?.findings ?? []).map((f: J, i: number) =>
          <div className="claim" key={i}><Icon name="chevron"/><div><b>{f.text}</b><Badge tone={CLASS_TONE[f.classification]}>{f.classification}</Badge><Cite ids={f.evidence_ids}/></div></div>)}</Card>
        {r.validation_errors.length > 0 && <Card className="blocked"><SectionTitle title="차단된 주장" action={<Badge tone="red">{r.validation_errors.length}건</Badge>}/>{r.validation_errors.map((e: string) =>
          <div className="blocked-box" key={e}><Icon name="shield"/><div><span>{e}</span></div></div>)}</Card>}
      </div>
    </div>}
    {r && <div className="action-bar"><div><Icon name="shield"/><span><b>사람 승인 필수</b> 사실 관측은 D2 NCR, 원인 후보와 모델 출력은 D4 원인 가설 초안으로 나뉩니다. 임시조치 계획은 템플릿으로 작성합니다.</span></div>
      <span className="row-gap"><button className="button primary" disabled={!author || r.status !== 'VALIDATED'} onClick={() => draft('ncr')}>D2 NCR 초안</button>
        <button className="button secondary" disabled={!author || r.status !== 'VALIDATED'} onClick={() => draft('rca')}>D4 원인 가설 초안</button></span></div>}
  </Page>
}

function HistoryScreen({ ctx }: { ctx: Ctx }) {
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

function Reports({ ctx }: { ctx: Ctx }) {
  const lists = KINDS.map(([k]) => useLoad<J[]>(ctx, `/cases/${ctx.cid}/${k}`, [])) // fixed order, safe for hooks
  const stages = useLoad<J[]>(ctx, `/cases/${ctx.cid}/stages`, [])
  const all = KINDS.flatMap(([k], i) => lists[i].map(d => ({ ...d, kind: k })))
  const [selKey, setSelKey] = useState(ctx.focus)
  const [comment, setComment] = useState('')
  const [note, setNote] = useState('')
  const [claimFor, setClaimFor] = useState('')
  const [replyTo, setReplyTo] = useState<number | null>(null)
  const d = all.find(x => `${x.kind}:${x.version}` === selKey) ?? all[all.length - 1]
  const author = ctx.me?.role === 'AUTHOR'
  const create = async (k: string) => { const r = await ctx.api(`/cases/${ctx.cid}/${k}`, 'POST', {}, true); setSelKey(`${k}:${r.version}`); ctx.refresh() }
  const latestOf = (x: J) => { const l = lists[KINDS.findIndex(k => k[0] === x.kind)]; return l[l.length - 1]?.version === x.version }
  const approver = d && KINDS.find(k => k[0] === d.kind)![3]
  const stage = d && stages.find(s => s.kind === d.kind)
  const act = async (path: string, body: J) => { await ctx.api(`/cases/${ctx.cid}/${d.kind}/${d.version}/${path}`, 'POST', body, true); setComment(''); ctx.refresh() }
  const say = async () => { await act('comments', { body: note, claim_id: claimFor || null, reply_to: replyTo }); setNote(''); setReplyTo(null) }
  const resolve = async (id: number) => { await act(`comments/${id}/resolve`, { body: note || '해결' }); setNote('') }
  const openOn = (cl: string) => (d?.comments ?? []).filter((x: J) => x.open && x.claim_id === cl).length
  return <Page title="문서 및 결재" desc="8D 순서: D2 NCR(검토자) → D3 임시조치 계획(QA/생산) → D4 원인 가설(공정 엔지니어). 초안은 미리 쓸 수 있지만 결재는 앞 단계 승인 후에만 열립니다."
    action={author && <span>{KINDS.map(([k, t]) => <button key={k} className="button secondary" onClick={() => create(k)}>{t} 초안 생성</button>)}</span>}>
    <Card className="mb"><Stages ctx={ctx}/></Card>
    <div className="report-layout">
      <Card><SectionTitle title="문서 목록" sub={`${all.length}개 버전`}/>{all.map(x => <div key={`${x.kind}:${x.version}`} className={`doc-row ${x === d ? 'selected' : ''}`} onClick={() => setSelKey(`${x.kind}:${x.version}`)}>
        <Icon name="document"/><div><b>{x.doc_type} <small>v{x.version}</small></b><span>근거 주장 {x.claims.length}개 · {x.author_id}</span></div><Badge tone={STATUS_TONE[x.status]}>{x.status}</Badge></div>)}
        {!all.length && <Empty>문서가 없습니다.</Empty>}</Card>
      {d ? <Card className="document-view"><div className="doc-title"><div><Badge tone="teal">{d.doc_type} · v{d.version}</Badge> <Badge tone={STATUS_TONE[d.status]}>{d.status}</Badge><h3>{d.doc_type} {d.case_id}</h3>
        <span>작성 {d.author_id} · {d.created_at.slice(0, 19)} · 템플릿 {d.template_version} · 기반 {d.based_on.join(', ') || '-'} · 생성기 {d.builder}</span></div>
        <a className="button secondary" href={`/cases/${d.case_id}/${d.kind}/${d.version}/html`} onClick={async e => { e.preventDefault(); const w = window.open(''); w?.document.write(await (await fetch(`/cases/${d.case_id}/${d.kind}/${d.version}/html`, { headers: { 'X-User': ctx.me.id } })).text()) }}>HTML 보기</a></div>
        {d.note && <Note>{d.note}</Note>}
        <div className="table-wrap"><table><thead><tr><th>ID</th><th>구분</th><th>주장</th><th>근거</th><th>코멘트</th></tr></thead><tbody>{d.claims.map((c: J) =>
          <tr key={c.claim_id}><td>{c.claim_id}</td><td><Badge tone={CLASS_TONE[c.classification]}>{c.classification}</Badge></td><td className="wrap">{c.text}</td><td className="wrap"><Cite ids={c.evidence_ids}/></td>
            <td><button className="citation" onClick={() => { setClaimFor(c.claim_id); setReplyTo(null) }}>{openOn(c.claim_id) ? `열림 ${openOn(c.claim_id)}` : '+'}</button></td></tr>)}</tbody></table></div>
        <p className="muted">SHA-256 {d.content_sha256}</p></Card> : <Card><Empty>문서를 선택하세요.</Empty></Card>}
      {d && <div className="stack"><Card><SectionTitle title="검토 및 결재"/>
        {d.reviews.map((r: J, i: number) => <div className="reviewer" key={i}><div className="avatar">{r.reviewer_id[0].toUpperCase()}</div><div><b>{r.reviewer_id}</b><span>검토 요청 · {r.state}</span></div></div>)}
        {d.decisions.map((x: J, i: number) => <div className="detail-row" key={i}><span>{x.action} · {x.actor_id}</span><b>{x.comment || '-'}</b></div>)}
        <div className="role-note"><Icon name="shield"/><span>{d.doc_type} 승인 권한: {APPROVER_ROLE[d.doc_type]}</span></div>
        {d.status === 'DRAFT' && latestOf(d) && stage && !stage.approval_open && <Note>결재 잠금: {stage.blocked_by}</Note>}
        {author && d.author_id === ctx.me.id && d.status === 'DRAFT' && latestOf(d) && <button className="button primary full" disabled={!stage?.approval_open} onClick={() => act('request-review', { reviewer_id: approver })}>{approver}에게 검토 요청</button>}
        {d.status === 'BASIS_CHANGED' && <Note>기반 문서가 정정으로 재검토 중입니다. 이 문서의 내용은 정정된 행을 인용하지 않아 그대로이지만, {APPROVER_ROLE[d.doc_type]}가 새 기반에서 범위가 유효한지 확인해야 다음 단계 결재가 열립니다.</Note>}
        {ctx.me?.role === APPROVER_ROLE[d.doc_type] && d.status === 'BASIS_CHANGED' && <>
          <input className="input" placeholder="확인 의견 (3자 이상)" value={comment} onChange={e => setComment(e.target.value)}/>
          <div className="dual"><button className="button success" onClick={() => act('basis-check', { decision: 'NO_SCOPE_IMPACT', comment, content_sha256: d.content_sha256 })}>범위 영향 없음</button>
            <button className="button danger" onClick={() => act('basis-check', { decision: 'REVISE', comment, content_sha256: d.content_sha256 })}>재작성 필요</button></div></>}
        {ctx.me?.role === APPROVER_ROLE[d.doc_type] && d.status === 'IN_REVIEW' && latestOf(d) && <>
          <input className="input" placeholder="검토 의견" value={comment} onChange={e => setComment(e.target.value)}/>
          <div className="dual"><button className="button success" onClick={() => act('decision', { decision: 'APPROVE', comment, content_sha256: d.content_sha256 })}>승인</button>
            <button className="button danger" onClick={() => act('decision', { decision: 'REJECT', comment, content_sha256: d.content_sha256 })}>반려</button></div>
          <button className="button secondary full" onClick={() => act('decision', { decision: 'REQUEST_INFO', comment, content_sha256: d.content_sha256 })}>추가 정보 요청</button></>}
      </Card>
      <Card><SectionTitle title="검토 코멘트" sub="주장 단위 · 감사 기록에 남음" action={<Badge tone={d.comments.some((x: J) => x.open) ? 'violet' : 'slate'}>열림 {d.comments.filter((x: J) => x.open).length}</Badge>}/>
        {d.comments.filter((x: J) => !x.reply_to).map((x: J) => <div key={x.comment_id} className="comment">
          <div className="detail-row"><span>{x.claim_id ?? '문서 전체'} · {x.actor_id} · {x.created_at.slice(11, 19)}</span><Badge tone={x.open ? 'violet' : 'green'}>{x.open ? '열림' : '해결'}</Badge></div>
          <p>{x.body}</p>
          {d.comments.filter((r: J) => r.reply_to === x.comment_id).map((r: J) => <p key={r.comment_id} className="muted">↳ {r.actor_id}{r.kind === 'RESOLVE' ? ' (해결)' : ''}: {r.body}</p>)}
          {x.open && <span className="row-gap"><button className="citation" onClick={() => { setReplyTo(x.comment_id); setClaimFor(x.claim_id ?? '') }}>답글</button>
            {(ctx.me?.id === d.author_id || ctx.me?.id === x.actor_id) && <button className="citation" onClick={() => resolve(x.comment_id)}>해결 처리</button>}</span>}</div>)}
        <div className="row-gap"><select value={claimFor} onChange={e => setClaimFor(e.target.value)}><option value="">문서 전체</option>{d.claims.map((c: J) => <option key={c.claim_id}>{c.claim_id}</option>)}</select>
          {replyTo && <Badge tone="violet">#{replyTo}에 답글</Badge>}</div>
        <input className="input" placeholder="코멘트 (해결 처리 시 메모로도 사용)" value={note} onChange={e => setNote(e.target.value)}/>
        <button className="button secondary full" disabled={!note.trim()} onClick={say}>코멘트 남기기</button></Card>
      <Card><SectionTitle title="책임 추적" sub="이 버전에 누가 어떤 역할로 무엇을 했는지 · 수정 불가 기록"/>
        <div className="tool-timeline">{d.trail.map((t: J, i: number) => <div className="tool-item" key={i}><i className={t.event === 'APPROVE' ? 'green' : 'amber'}>{t.event === 'APPROVE' && <Icon name="check" size={12}/>}</i>
          <time>{t.at.slice(11, 19)}</time><div><b>{t.event} · {t.actor_id} ({t.role})</b><span>{t.detail}</span></div></div>)}</div></Card>
      <Card><SectionTitle title="문서 주의사항"/><p className="muted">임시조치 계획 승인은 물리적 조치 완료를 의미하지 않습니다.</p><p className="muted">원인 가설 승인은 근본원인 확정을 의미하지 않습니다.</p></Card></div>}
    </div>
  </Page>
}

function Impact({ ctx }: { ctx: Ctx }) {
  const impacts = useLoad<J[]>(ctx, `/cases/${ctx.cid}/change-impact`, [])
  const sources = useLoad<J[]>(ctx, `/cases/${ctx.cid}/sources`, [])
  const events = useLoad<J[]>(ctx, `/cases/${ctx.cid}/events?entity_type=spi_measurements`, [])
  const rows = [...new Set(events.map(e => e.original_row_id))].sort()
  const [row, setRow] = useState('SPI-P02-B01-1')
  const imp = impacts[impacts.length - 1]
  const fix = async () => {
    const spi = sources.filter(s => s.source_system === 'SYNTHETIC_SPI_MEASUREMENTS')
    if (!spi.length) return
    const version = Math.max(...spi.map(s => s.source_version)) + 1
    const asset = await (await fetch(`/synthetic/7/spi-correction?row_id=${row}&version=${version}`)).json()
    await ctx.api(`/cases/${ctx.cid}/source-revisions`, 'POST', { asset, reason: `SPI 재측정 ${row}` }, true); ctx.refresh()
  }
  const col = (title: string, items: string[], tone: string) => <div className="graph-col"><small>{title}</small>{items.length ? items.map(i => <div className={`node-box ${tone}`} key={i}>{i}</div>) : <span className="muted">없음</span>}</div>
  return <Page title="증거 변경 영향 분석" desc="정정된 원천 행에서 의존성 그래프를 따라 영향받는 문서만 재검토로 돌립니다."
    action={ctx.me?.role === 'AUTHOR' && <span className="row-gap"><select value={row} onChange={e => setRow(e.target.value)}>{rows.map(r => <option key={r}>{r}</option>)}</select><button className="button primary" onClick={fix}>SPI 정정 가져오기 (데모)</button></span>}>
    {!imp ? <Card><Empty>가져온 원천 정정이 없습니다. 데모 정정은 seed 7 픽스처 기준으로 값만 바꾼 합성 행입니다.</Empty></Card> : <>
      <div className="revision-alert"><Icon name="warning"/><div><b>{imp.reason}</b><span>{imp.actor_id} · {imp.created_at.slice(0, 19)}</span></div><div><Badge tone="slate">{imp.supersedes_asset_id}</Badge><Icon name="arrow"/><Badge tone="amber">{imp.asset_id}</Badge></div></div>
      <div className="impact-layout">
        <Card><SectionTitle title="문서 상태 변화" sub="정정 전 → 후"/>{imp.documents.length ? imp.documents.map((d: J) =>
          <div key={d.document_version_id} className="compare-row amber"><span>{d.doc_type} v{d.version}</span><del>{d.status_before}</del><Icon name="arrow"/><b>{d.status_after}</b></div>) : <Empty>이 행에 의존하는 문서가 없어 재검토 대상이 없습니다.</Empty>}
          {(imp.basis_changed ?? []).map((d: J) => <div key={d.document_version_id} className="compare-row amber"><span>{d.doc_type} v{d.version} (기반 변경)</span><del>{d.status_before}</del><Icon name="arrow"/><b>{d.status_after}</b></div>)}
          <div className="immutable"><Icon name="shield"/><span><b>원본 보존</b> 기존 승인 기록은 DB 수준에서 수정·삭제가 차단됩니다.</span></div></Card>
        <Card className="graph-card"><SectionTitle title="증거 의존성 경로" sub="영향받은 노드만 표시"/><div className="graph-cols">
          {col('정정된 원천 Evidence', imp.changed_evidence, 'affected')}{col('파생 (예측 · XAI)', imp.derived, 'affected')}
          {col('주장', [...imp.claims].sort((a: string, b: string) => { const [, da, ca] = a.split(':'), [, db, cb] = b.split(':'); return +da - +db || +ca.slice(1) - +cb.slice(1) }).map((c: string) => { const [, id, cl] = c.split(':'); const d = imp.documents.find((x: J) => String(x.document_version_id) === id); return `${d ? `${d.doc_type} v${d.version}` : id} · ${cl}` }), 'critical')}
          {col('문서', imp.documents.map((d: J) => `${d.doc_type} v${d.version}`), 'affected')}</div></Card>
        <Card><SectionTitle title="정정 이력" action={<Badge tone="amber">{impacts.length}건</Badge>}/>{impacts.slice().reverse().map(i =>
          <div className="impact-item" key={i.impact_id}><Badge tone="slate">{i.asset_id}</Badge><b>{i.reason}</b><span>문서 {i.documents.length}개 · 주장 {i.claims.length}개 · 파생 {i.derived.length}개</span></div>)}</Card>
      </div></>}
  </Page>
}

function Audit({ ctx }: { ctx: Ctx }) {
  const tl = useLoad<J[]>(ctx, `/cases/${ctx.cid}/timeline`, [])
  const policies: [string, string, Tone][] = [
    ['미배정 사건 접근', '배정되지 않은 사용자는 403', 'red'], ['외부 전송 제한', 'SYNTHETIC + APPROVED_FOR_EXTERNAL만 Meta로 전송, 그 외 전송 전 차단', 'green'],
    ['감사 기록 불변', 'approval_events · workflow_events 수정/삭제를 DB 트리거로 차단', 'blue'], ['오래된 버전 결재', '최신이 아니거나 해시가 다르면 409', 'amber']]
  return <Page title="감사 및 보안" desc="사건 타임라인과 서버가 강제하는 정책입니다.">
    <div className="security-grid">{policies.map(x => <Card key={x[0]}><div className={`security-icon ${x[2]}`}><Icon name="shield"/></div><b>{x[0]}</b><span className="muted">{x[1]}</span><Badge tone={x[2]}>서버 정책</Badge></Card>)}</div>
    <Card><SectionTitle title="감사 이벤트" sub={`${tl.length}건 · 추가만 가능한 기록`}/><div className="table-wrap"><table><thead><tr><th>시각</th><th>행위자</th><th>이벤트</th><th>내용</th></tr></thead><tbody>
      {tl.map((t, i) => <tr key={i}><td>{t.at.slice(0, 19)}</td><td>{t.actor_id}</td><td><Badge tone={t.event.includes('REVALIDATION') ? 'red' : t.event.startsWith('BASIS') ? 'amber' : t.event === 'APPROVE' ? 'green' : 'slate'}>{t.event}</Badge></td><td className="wrap">{t.detail}</td></tr>)}
    </tbody></table></div></Card>
  </Page>
}

export default function App() {
  const [active, setActive] = useState('dashboard')
  const [user, setUser] = useState('alice')
  const [cases, setCases] = useState<J[]>([])
  const [cid, setCid] = useState('')
  const [me, setMe] = useState<J>(null)
  const [provider, setProvider] = useState<J>(null)
  const [msg, setMsg] = useState('')
  const [tick, setTick] = useState(0)
  const [focus, setFocus] = useState('')

  const api = useCallback(async (path: string, method = 'GET', body?: unknown, idem = false) => {
    const headers: Record<string, string> = { 'X-User': user }
    if (body !== undefined) headers['Content-Type'] = 'application/json'
    if (idem) headers['Idempotency-Key'] = uid()
    const r = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
    const text = await r.text(); let j: J; try { j = JSON.parse(text) } catch { j = text }
    if (!r.ok) { if (method !== 'GET') setMsg(`${r.status}: ${typeof j?.detail === 'string' ? j.detail : JSON.stringify(j?.detail ?? j)}`); throw new Error(String(r.status)) }
    if (method !== 'GET') setMsg('')
    return j
  }, [user])
  const refresh = useCallback(() => setTick(t => t + 1), [])

  useEffect(() => { fetch('/provider').then(r => r.json()).then(setProvider).catch(() => setProvider(null)) }, [])
  useEffect(() => {
    api('/me').then(setMe).catch(() => setMe(null))
    api('/cases').then((cs: J[]) => { setCases(cs); setCid(c => cs.some(x => x.case_id === c) ? c : cs[cs.length - 1]?.case_id ?? '') }).catch(() => setCases([]))
  }, [api, tick])

  const newCase = async () => {
    const id = `PCB-${Date.now().toString(36).toUpperCase()}`
    await api('/cases', 'POST', { case_id: id })
    await api(`/cases/${id}/sources`, 'POST', await (await fetch('/synthetic/7')).json())
    for (const u of ['bob', 'erin', 'frank']) await api(`/cases/${id}/assignments`, 'POST', { user_id: u })
    setCid(id); refresh()
  }

  const open = useCallback((c: string, sel: string) => { setCid(c); setFocus(sel); setActive('reports') }, [])
  const ctx: Ctx = { cid, me, api, refresh, tick, open, focus }
  const screens: Record<string, ReactNode> = {
    dashboard: <Dashboard ctx={ctx} cases={cases} onNew={newCase}/>, queue: <Queue ctx={ctx}/>, data: <DataWorkspace ctx={ctx}/>, prediction: <Prediction ctx={ctx}/>,
    investigation: <Investigation ctx={ctx} provider={provider}/>, history: <HistoryScreen ctx={ctx}/>, reports: <Reports ctx={ctx}/>, impact: <Impact ctx={ctx}/>, audit: <Audit ctx={ctx}/>,
  }
  return <div className="app">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><span/><span/><span/></div><div><b>QualityOps</b><small>AI</small></div></div>
      <label className="site-select"><span><small>현재 사건</small><select value={cid} onChange={e => setCid(e.target.value)}>{cases.map(c => <option key={c.case_id}>{c.case_id}</option>)}{!cases.length && <option value="">배정된 사건 없음</option>}</select></span></label>
      <nav>{nav.map(n => <button key={n[0]} className={active === n[0] ? 'active' : ''} onClick={() => { setFocus(''); setActive(n[0]) }}><Icon name={n[2]}/><span>{n[1]}</span>{n[0] === 'investigation' && <i>AI</i>}</button>)}</nav>
      <div className="sidebar-bottom"><div className="status-live"><i className={provider?.configured ? '' : 'off'}/><span><b>Meta · {provider?.model ?? '-'}</b><small>{provider?.configured ? 'LIVE 키 설정됨' : '키 없음 · 호출 불가'}</small></span></div></div>
    </aside>
    <div className="shell">
      <header><div className="breadcrumb"><span>QualityOps AI</span><Icon name="chevron" size={13}/><b>{nav.find(x => x[0] === active)?.[1]}</b></div>
        <div className="header-actions"><Badge tone="blue">SYNTHETIC 데이터</Badge>
          <label className="user"><div className="avatar">{user[0].toUpperCase()}</div><span><small>데모 사용자 (X-User, 비밀번호 없음)</small><select value={user} onChange={e => setUser(e.target.value)}>{USERS.map(u => <option key={u[0]} value={u[0]}>{u[1]}</option>)}</select></span></label></div></header>
      {msg && <div className="error-bar" onClick={() => setMsg('')}>{msg}</div>}
      {cid || active === 'dashboard' ? screens[active] : <main className="page"><Card><Empty>배정된 사건이 없습니다.</Empty></Card></main>}
    </div>
  </div>
}
