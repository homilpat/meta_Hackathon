import { useEffect, useState } from 'react'
import { USERS } from '../../constants'
import { Badge, Card, Cite, Empty, Field, Note, Page, SectionTitle } from '../../components/ui'
import { ExperienceCard } from '../experience/ExperienceCard'
import type { Ctx, J, Tone } from '../../types'

export const STAGE_LABEL: Record<string, string> = { D0: '위험 평가', D1: '팀', D2: '문제 정의', D3: '임시 봉쇄', D4: '근본 원인', D5: '조치 선정', D6: '실행·효과', D7: '재발 방지', D8: '종결' }
export const GATE_TONE: Record<string, Tone> = { PASS: 'green', WARN: 'amber', UNKNOWN: 'slate', BLOCK: 'red' }
export const stageTone = (s: string | null): Tone => !s ? 'slate' : ['APPROVED', 'DONE', 'CLOSED'].includes(s) ? 'green' : ['REJECTED', 'REVALIDATION_REQUIRED', 'NOT_EFFECTIVE', 'REOPENED'].includes(s) ? 'red' : 'amber'
export const list = (s: string) => s.split(',').map(x => x.trim()).filter(Boolean)

export function EightD({ ctx }: { ctx: Ctx }) {
  const { cid, api, tick, refresh, me } = ctx
  const [g, setG] = useState<J>(null)
  const [tri, setTri] = useState<J[]>([])
  const [team, setTeam] = useState<J>(null)
  const [acts, setActs] = useState<J[]>([])
  const [pc, setPc] = useState<J>(null)
  const [pd, setPd] = useState<J>(null)
  const [d4, setD4] = useState<J>(null)
  const [d6, setD6] = useState<J>(null)
  const [d7, setD7] = useState<J>(null)
  const [xp, setXp] = useState<J>(null)
  const [d8, setD8] = useState<J>(null)
  const [f, setF] = useState<Record<string, string>>({ signal_kind: 'SPC_SIGNAL', observed_defect: 'SIGNAL_ONLY', route: 'FULL_8D', severity: 'MEDIUM', scope_lots: '', rationale: '', evidence_ids: '',
    responsibility: 'QUALITY', user_id: 'bob', action_type: 'HOLD', targets: '', description: '', note: '', evidence: '',
    cause_type: 'OCCURRENCE', category: 'MACHINE', htext: '', hev: '', causes: '', feasibility: '', risk: '', side: '', risk8: '', owner8: '', notify: '' })
  const set = (k: string) => (e: { target: { value: string } }) => setF(x => ({ ...x, [k]: e.target.value }))
  useEffect(() => {
    if (!cid) return
    api(`/cases/${cid}/gates`).then(setG).catch(() => setG(null))
    api(`/cases/${cid}/triage`).then(setTri).catch(() => setTri([]))
    api(`/cases/${cid}/team`).then(setTeam).catch(() => setTeam(null))
    api(`/cases/${cid}/actions`).then(setActs).catch(() => setActs([]))
    api(`/cases/${cid}/process-context`).then(setPc).catch(() => setPc(null))
    api(`/cases/${cid}/problem-definition`).then(setPd).catch(() => setPd(null))
    api(`/cases/${cid}/hypotheses`).then(setD4).catch(() => setD4(null))
    api(`/cases/${cid}/effectiveness`).then(setD6).catch(() => setD6(null))
    api(`/cases/${cid}/prevention`).then(setD7).catch(() => setD7(null))
    api(`/cases/${cid}/experience`).then(setXp).catch(() => setXp(null))
    api(`/cases/${cid}/closure`).then(setD8).catch(() => setD8(null))
  }, [cid, api, tick])
  const run = (p: Promise<unknown>) => p.then(refresh).catch(() => undefined)
  const t = tri[tri.length - 1]
  const role = me?.role
  return <Page title="D0~D8 진행" desc="정책(WorkflowPolicy)이 각 단계의 작성·실행·승인·종결 가능 여부를 판단합니다. 모든 실행 기록은 SIMULATED(합성 데모)입니다.">
    <Note>계획 ≠ 실행 ≠ 독립 확인. 이 화면의 조치 실행은 실제 재고·출하 상태를 바꾸지 않는 가상 기록입니다.</Note>
    <Card className="mb"><SectionTitle title="단계 상태" sub={g ? `정책 ${g.policy.policy_id} v${g.policy.version} · 경로 ${g.route ?? '미정 (D0 필요)'}` : ''}/>
      <div className="row-gap" style={{ flexWrap: 'wrap' }}>{g && Object.entries(g.state).map(([s, v]) => <span key={s} className="row-gap"><b className="muted">{s} {STAGE_LABEL[s]}</b><Badge tone={stageTone(v as string)}>{(v as string) ?? '—'}</Badge></span>)}</div>
      {g && <p className="muted wrap mt">긴급 봉쇄 (내 역할 {role}): <Badge tone={GATE_TONE[g.urgent_containment.result]}>{g.urgent_containment.result}</Badge> {g.urgent_containment.reasons.join(' · ')}</p>}
    </Card>
    <div className="dashboard-main">
      <Card><SectionTitle title="D0 위험 평가" sub="신호와 확정 불량은 별도 상태로 저장됩니다"/>
        {t ? <div className="wrap" style={{ fontSize: 11 }}><Badge tone="blue">{t.signal_kind}</Badge> <Badge tone={t.observed_defect === 'DEFECT_CONFIRMED' ? 'red' : 'slate'}>{t.observed_defect}</Badge> <Badge tone="violet">{t.route}</Badge> <Badge>{t.severity}</Badge>
          <p>{t.rationale}</p><p className="muted">범위 LOT {t.scope_lots.join(', ') || '-'} · 출하분 포함 {String(t.risk_flags.shipped_in_scope)} · 평가자 {t.assessor_id}</p><Cite ids={t.evidence_ids}/></div> : <Empty>아직 D0 평가가 없습니다.</Empty>}
        {role === 'REVIEWER' && <div className="mt">
          <div className="dual"><Field label="신호 종류"><select value={f.signal_kind} onChange={set('signal_kind')}>{['SPC_SIGNAL', 'AOI_FAIL', 'CUSTOMER_COMPLAINT', 'OTHER'].map(x => <option key={x}>{x}</option>)}</select></Field>
            <Field label="불량 확인"><select value={f.observed_defect} onChange={set('observed_defect')}>{['SIGNAL_ONLY', 'DEFECT_CONFIRMED', 'UNKNOWN'].map(x => <option key={x}>{x}</option>)}</select></Field>
            <Field label="경로"><select value={f.route} onChange={set('route')}>{['NCR_ONLY', 'FULL_8D', 'EMERGENCY_FULL_8D'].map(x => <option key={x}>{x}</option>)}</select></Field>
            <Field label="심각도"><select value={f.severity} onChange={set('severity')}>{['LOW', 'MEDIUM', 'HIGH'].map(x => <option key={x}>{x}</option>)}</select></Field></div>
          <input className="input" placeholder="범위 LOT (쉼표 구분, 예: L02)" value={f.scope_lots} onChange={set('scope_lots')}/>
          <input className="input" placeholder="판단 근거 (10자 이상)" value={f.rationale} onChange={set('rationale')}/>
          <input className="input" placeholder="증거 ID (쉼표 구분, EV-...)" value={f.evidence_ids} onChange={set('evidence_ids')}/>
          <button className="button primary full" onClick={() => run(api(`/cases/${cid}/triage`, 'POST', { signal_kind: f.signal_kind, observed_defect: f.observed_defect, route: f.route, severity: f.severity,
            scope_lots: list(f.scope_lots), rationale: f.rationale, evidence_ids: list(f.evidence_ids), risk_flags: {} }))}>D0 평가 기록</button></div>}
      </Card>
      <Card><SectionTitle title="공정 컨텍스트" sub="공정 중립 어댑터가 LOT·패널·출하 상태를 매핑"/>
        {pc ? <div style={{ fontSize: 11 }}><Badge tone="teal">{pc.process_type}</Badge> <span className="muted">{pc.adapter_version} · {pc.site} · 설비 {pc.equipment.join(', ')}</span>
          <p className="muted">대상 객체 {pc.objects.length}개 · 출하 {pc.objects.filter((o: J) => o.shipment_state === 'SHIPPED').length}개</p></div>
          : <>{role === 'AUTHOR' ? <button className="button secondary" onClick={() => run(api(`/cases/${cid}/process-context`, 'POST', { site: 'SITE-A' }))}>공정 컨텍스트 기록 (PCB_SMT)</button> : <Empty>작성자가 공정 컨텍스트를 기록해야 합니다.</Empty>}</>}
      </Card>
    </div>
    <div className="dashboard-main">
      <Card><SectionTitle title="D1 팀" sub={team ? (team.complete ? '필수 역할 모두 수락' : `미완료: ${team.missing.join(', ')}`) : ''}/>
        <div className="table-wrap"><table><thead><tr><th>책임</th><th>담당</th><th>상태</th><th>기한</th><th/></tr></thead><tbody>
          {team && Object.entries(team.members).map(([r, m]: [string, J]) => <tr key={r}><td>{r}</td><td>{m.user_id ?? '-'}</td><td><Badge tone={m.status === 'ACCEPTED' ? 'green' : m.status === 'EXCEPTION' ? 'amber' : m.overdue ? 'red' : 'slate'}>{m.status}{m.overdue ? ' · 기한 초과' : ''}</Badge></td><td>{m.due_at ?? '-'}</td>
            <td>{m.user_id === me?.id && m.status === 'ASSIGNED' && <button className="button success" onClick={() => run(api(`/cases/${cid}/team`, 'POST', { event: 'ACCEPT', responsibility: r }))}>수락</button>}</td></tr>)}
        </tbody></table></div>
        {role === 'AUTHOR' && <div className="row-gap mt"><select value={f.responsibility} onChange={set('responsibility')}>{['LEAD', 'QUALITY', 'PRODUCTION', 'PROCESS', 'SUPPLIER', 'CUSTOMER'].map(x => <option key={x}>{x}</option>)}</select>
          <select value={f.user_id} onChange={set('user_id')}>{USERS.map(u => <option key={u[0]} value={u[0]}>{u[1]}</option>)}</select>
          <button className="button secondary" onClick={() => run(api(`/cases/${cid}/team`, 'POST', { event: 'ASSIGN', responsibility: f.responsibility, user_id: f.user_id }))}>배정</button></div>}
      </Card>
      <Card><SectionTitle title="봉쇄 조치 요청" sub="긴급: D0 이후 D1/D2 전에도 가능 (QA/생산) · D3: 격리 계획서 기반 (작성자)"/>
        <div className="dual"><Field label="조치"><select value={f.action_type} onChange={set('action_type')}>{['HOLD', 'SORT', 'STOP_SHIP', 'QUARANTINE', 'CUSTOMER_NOTIFY_REQUEST', 'OTHER'].map(x => <option key={x}>{x}</option>)}</select></Field>
          <Field label="대상 (쉼표 구분)"><input className="input" style={{ marginTop: 0 }} placeholder="L02-P09" value={f.targets} onChange={set('targets')}/></Field></div>
        <input className="input" placeholder="조치 설명 (10자 이상)" value={f.description} onChange={set('description')}/>
        <div className="dual"><button className="button primary" disabled={role !== 'QA_PRODUCTION'} onClick={() => run(api(`/cases/${cid}/urgent-actions`, 'POST', { action_type: f.action_type, targets: list(f.targets), description: f.description }))}>긴급 봉쇄 요청</button>
          <button className="button secondary" disabled={role !== 'AUTHOR'} onClick={() => run(api(`/cases/${cid}/actions`, 'POST', { action_type: f.action_type, targets: list(f.targets), description: f.description }))}>D3 조치 제안 (계획서 기반)</button></div>
        <p className="muted wrap">대상은 LOT·패널(L02-P09)·보드(L02-P09/B1)·출하 행(SHIP-L02-P01). 출하된 대상은 HOLD 불가 → CUSTOMER_NOTIFY_REQUEST.</p>
      </Card>
    </div>
    {pd && <Card className="mb"><SectionTitle title="D2 문제 정의 (5W2H · IS / IS NOT)" sub="현재 원본 행에서 서버가 계산 · NCR 문서에도 같은 내용이 클레임으로 들어가 승인 해시에 묶입니다"/>
      <div className="table-wrap"><table><thead><tr><th>항목</th><th>값</th><th>상태</th><th>근거</th></tr></thead><tbody>
        {['what', 'where', 'when', 'who_detected', 'how_many', 'is', 'is_not'].map(k => <tr key={k}><td>{k}</td><td className="wrap">{typeof pd[k].value === 'string' ? pd[k].value : JSON.stringify(pd[k].value)}</td>
          <td><Badge tone={pd[k].status === 'KNOWN' ? 'green' : 'slate'}>{pd[k].status}</Badge></td><td>{pd[k].evidence_ids.length}건</td></tr>)}
      </tbody></table></div>
      <p className="muted wrap mt">범위 미상 {pd.unknown_scope.length}건 · 원본 버전 {Object.entries(pd.effective_source_versions).map(([k, v]) => `${k} v${v}`).join(', ')} · {pd.note}</p></Card>}
    {xp && <ExperienceCard xp={xp} cid={cid} api={api} run={run} role={role} f={f}/>}
    {d4 && <Card className="mb"><SectionTitle title="D4 원인 가설 → 실험 → 판정" sub="원인 확정은 독립된 공정 엔지니어가 지지 실험(VALID 증거)으로만 기록 · SHAP·선례·AI 제안만으로는 확정 불가"/>
      <div className="table-wrap"><table><thead><tr><th>#</th><th>6M</th><th>유형</th><th>가설</th><th>출처</th><th>실험</th><th>상태</th><th>판정</th></tr></thead><tbody>
        {d4.hypotheses.map((h: J) => { const sup = h.experiments.filter((e: J) => e.result === 'SUPPORTS').map((e: J) => e.experiment_id)
          return <tr key={h.hypothesis_id}><td className="id">H{h.hypothesis_id}</td><td>{h.category}</td><td>{h.cause_type}</td><td className="wrap">{h.text}</td><td>{h.origin}</td>
            <td className="wrap">{h.experiments.map((e: J) => `E${e.experiment_id} ${e.result} n=${e.sample_size} (${e.performed_by}, ${e.execution_mode})`).join(' · ') || '-'}</td>
            <td><Badge tone={h.status === 'CONFIRMED' ? 'green' : h.status === 'REJECTED' ? 'red' : 'amber'}>{h.status}</Badge></td>
            <td>{role === 'PROCESS_ENGINEER' && h.status === 'OPEN' && <div className="row-gap">
              <button className="button success" style={{ height: 26, padding: '0 6px' }} onClick={() => run(api(`/cases/${cid}/causal-decisions`, 'POST', { hypothesis_id: h.hypothesis_id, decision: 'CONFIRMED', basis_experiment_ids: sup, rationale: f.note || 'supporting experiment reviewed' }))}>CONFIRMED</button>
              <button className="button secondary" style={{ height: 26, padding: '0 6px' }} onClick={() => run(api(`/cases/${cid}/causal-decisions`, 'POST', { hypothesis_id: h.hypothesis_id, decision: 'INCONCLUSIVE', rationale: f.note || 'evidence insufficient' }))}>INCONCLUSIVE</button></div>}</td></tr> })}
        {!d4.hypotheses.length && <tr><td colSpan={8}><Empty>가설이 없습니다.</Empty></td></tr>}
      </tbody></table></div>
      <div className="row-gap mt" style={{ flexWrap: 'wrap' }}><select value={f.category} onChange={set('category')}>{['MAN', 'MACHINE', 'MATERIAL', 'METHOD', 'MEASUREMENT', 'ENVIRONMENT'].map(x => <option key={x}>{x}</option>)}</select>
        <select value={f.cause_type} onChange={set('cause_type')}>{['OCCURRENCE', 'NON_DETECTION', 'SYSTEMIC'].map(x => <option key={x}>{x}</option>)}</select>
        <input className="input" style={{ flex: 2, marginTop: 0 }} placeholder="가설 (10자 이상)" value={f.htext} onChange={set('htext')}/>
        <input className="input" style={{ flex: 1, marginTop: 0 }} placeholder="근거 EV-... (쉼표)" value={f.hev} onChange={set('hev')}/>
        <button className="button secondary" onClick={() => run(api(`/cases/${cid}/hypotheses`, 'POST', { category: f.category, cause_type: f.cause_type, text: f.htext, evidence_ids: list(f.hev) }))}>가설 추가</button></div>
      <p className="muted wrap">확정 원인 {d4.confirmed.length}건 · 5-Why 연결 {d4.why_links.length}건 · 판정 메모는 위 "실행/확인 메모" 칸을 사용합니다.</p></Card>}
    {d6 && <Card className="mb"><SectionTitle title="D5 조치 선정 · D6 효과 검증" sub={`D5 ${d6.D5 ?? '—'} · D6 ${d6.D6 ?? '—'} · 선정 ≠ 실행 ≠ 효과 · 효과는 사전 등록 기준으로 서버가 계산 (SYNTHETIC)`}/>
      <div className="row-gap" style={{ flexWrap: 'wrap' }}><input className="input" style={{ flex: 1, marginTop: 0 }} placeholder="확정 원인 H# (쉼표, 숫자)" value={f.causes} onChange={set('causes')}/>
        <input className="input" style={{ flex: 1, marginTop: 0 }} placeholder="실현 가능성" value={f.feasibility} onChange={set('feasibility')}/>
        <input className="input" style={{ flex: 1, marginTop: 0 }} placeholder="위험 분석" value={f.risk} onChange={set('risk')}/>
        <input className="input" style={{ flex: 1, marginTop: 0 }} placeholder="부작용" value={f.side} onChange={set('side')}/>
        <button className="button secondary" disabled={!['AUTHOR', 'PROCESS_ENGINEER'].includes(role ?? '')} onClick={() => run(api(`/cases/${cid}/actions`, 'POST', { stage: 'D5', action_type: 'PROCESS_CHANGE', description: f.description,
          cause_ids: list(f.causes).map(Number), details: { feasibility: f.feasibility, risk_analysis: f.risk, side_effects: f.side } }))}>D5 조치안 추가</button></div>
      <p className="muted wrap">조치 설명은 위 "조치 설명" 칸을 사용합니다. 선정은 아래 조치 실행 기록에서 PLAN_APPROVED (공정 엔지니어, 원인 CONFIRMED 필요).</p>
      <div className="table-wrap mt"><table><thead><tr><th>계획</th><th>조치</th><th>지표 · 기준</th><th>서버 계산</th><th>결과</th><th>판정</th></tr></thead><tbody>
        {d6.plans.map((p: J) => { const pv = d6.preview[p.plan_id]; const res = d6.results.filter((r: J) => r.plan_id === p.plan_id)
          return <tr key={p.plan_id}><td className="id">#{p.plan_id}</td><td>#{p.action_id}</td><td className="wrap">{p.metric} {p.acceptance.op} {p.acceptance.value} · 기준 LOT {p.baseline_lots.join(',')} · 최소 n {p.min_sample}</td>
            <td className="wrap"><Badge tone={pv.computed === 'MEETS_CRITERIA' ? 'green' : pv.computed === 'FAILS_CRITERIA' ? 'red' : 'amber'}>{pv.computed}</Badge> {pv.observed.post ? `전 ${pv.observed.baseline.mean} (n=${pv.observed.baseline.n}) → 후 ${pv.observed.post.mean} (n=${pv.observed.post.n})` : ''} {pv.reasons.join(' · ')}</td>
            <td>{res.map((r: J) => <Badge key={r.result_id} tone={r.decision === 'EFFECTIVE' ? 'green' : r.decision === 'NOT_EFFECTIVE' ? 'red' : 'amber'}>{r.decision} ({r.reviewer_id})</Badge>)}</td>
            <td>{role === 'REVIEWER' && <div className="row-gap">{['EFFECTIVE', 'NOT_EFFECTIVE', 'INCONCLUSIVE'].map(d => <button key={d} className="button secondary" style={{ height: 26, padding: '0 6px' }}
              onClick={() => run(api(`/cases/${cid}/effectiveness`, 'POST', { plan_id: p.plan_id, decision: d, note: f.note || 'reviewed the server comparison' }))}>{d}</button>)}</div>}</td></tr> })}
        {!d6.plans.length && <tr><td colSpan={6}><Empty>효과 검증 계획이 없습니다. (API: POST /effectiveness-plans, 실행 전 등록)</Empty></td></tr>}
      </tbody></table></div></Card>}
    <div className="dashboard-main">
      {d7 && <Card><SectionTitle title="D7 재발 방지 (문서 개정·교육·수평 전개)" sub={`상태 ${d7.state ?? '—'} · 등록부의 발효된 개정본만 인정 · '개정했다'는 문장은 증거가 아님`}/>
        <div className="table-wrap"><table><thead><tr><th>문서</th><th>개정</th><th>범위</th><th>교육</th><th>수평 전개</th></tr></thead><tbody>
          {d7.deployments.map((x: J) => <tr key={x.id}><td>{x.doc_number} <span className="muted">{x.kind}</span></td><td>rev {x.old_revision} → {x.new_revision}</td><td>{x.scopes.join(', ')}</td>
            <td>{x.training.length}/{x.operators_in_scope.length}</td><td className="wrap">{x.sister_lines.map((l: J) => `${l.line}:${l.applies ? '적용' : '제외'}`).join(' · ') || '-'}</td></tr>)}
          {!d7.deployments.length && <tr><td colSpan={5}><Empty>D7 기록이 없습니다. (API: /controlled-documents/revisions → release → /prevention)</Empty></td></tr>}
        </tbody></table></div>
        {d7.reasons.length > 0 && <p className="muted wrap mt">미완료: {d7.reasons.join(' · ')}</p>}</Card>}
      {d8 && <Card><SectionTitle title="D8 종결" sub={`정책 ${d8.policy.policy_id} v${d8.policy.version} · 고객 통보 필요 ${String(d8.needs_customer_notification)} · 서명 ${d8.acknowledged.join(', ') || '-'}`}/>
        {d8.blocks.length ? <ul className="wrap muted" style={{ fontSize: 11 }}>{d8.blocks.map((b: string) => <li key={b}>{b}</li>)}</ul> : <Note>모든 종결 조건 충족 (합성 데이터 기준)</Note>}
        {d8.team[me?.id ?? ''] && !d8.acknowledged.includes(me?.id) && <button className="button success" onClick={() => run(api(`/cases/${cid}/closure/acknowledgements`, 'POST', { contribution: f.note || 'reviewed the final result' }))}>결과 확인 서명</button>}
        {role === 'REVIEWER' && <div className="mt"><div className="dual"><input className="input" placeholder="잔여 위험" value={f.risk8} onChange={set('risk8')}/><input className="input" placeholder="위험 담당" value={f.owner8} onChange={set('owner8')}/></div>
          <input className="input" placeholder="고객 통보 참조번호 (출하·고객 영향 시 필수)" value={f.notify} onChange={set('notify')}/>
          <div className="dual"><button className="button primary" onClick={() => run(api(`/cases/${cid}/closure`, 'POST', { residual_risks: [{ risk: f.risk8, mitigation: f.note || 'monitored', owner: f.owner8 }], customer_notification_ref: f.notify || null, comment: f.note || 'closure reviewed' }))}>D8 종결</button>
            <button className="button secondary" disabled={d8.state.D8 !== 'CLOSED'} onClick={() => run(api(`/cases/${cid}/closure/reopen`, 'POST', { reason: f.note || 'reopened for re-investigation' }))}>재오픈</button></div></div>}
        <p className="muted wrap mt">이력: {d8.history.map((h: J) => `${h.decision}(${h.actor_id}, ${h.snapshot_sha256.slice(0, 10)})`).join(' → ') || '-'}</p></Card>}
    </div>
    <Card className="mb"><SectionTitle title="조치 실행 기록" sub="REQUESTED → (PLAN_APPROVED) → EXECUTED → INDEPENDENTLY_VERIFIED · 실행자와 확인자는 달라야 함"/>
      <div className="dual"><input className="input" placeholder="실행/확인 메모 (실행은 10자 이상)" value={f.note} onChange={set('note')}/><input className="input" placeholder="확인 근거 (쉼표 구분, EV-... 또는 REF:...)" value={f.evidence} onChange={set('evidence')}/></div>
      <div className="table-wrap mt"><table><thead><tr><th>#</th><th>단계</th><th>조치</th><th>대상</th><th>상태</th><th>이력</th><th>기록</th></tr></thead><tbody>
        {acts.map(a => <tr key={a.action_id}><td className="id">{a.action_id}</td><td>{a.stage}</td><td>{a.action_type}</td><td>{a.targets.join(', ')}</td><td><Badge tone={stageTone(a.status)}>{a.status}</Badge> <Badge tone="amber">{a.execution_mode}</Badge></td>
          <td className="wrap">{a.events.map((e: J) => `${e.event_type}(${e.actor_id})`).join(' → ')}</td>
          <td><div className="row-gap">{['PLAN_APPROVED', 'EXECUTED', 'INDEPENDENTLY_VERIFIED', 'RELEASED', 'NOT_EFFECTIVE'].map(ev => <button key={ev} className="button secondary" style={{ height: 26, padding: '0 6px' }}
            onClick={() => run(api(`/cases/${cid}/actions/${a.action_id}/events`, 'POST', { event_type: ev, note: f.note, evidence: list(f.evidence) }))}>{ev}</button>)}</div></td></tr>)}
        {!acts.length && <tr><td colSpan={7}><Empty>조치가 없습니다.</Empty></td></tr>}
      </tbody></table></div>
    </Card>
  </Page>
}
