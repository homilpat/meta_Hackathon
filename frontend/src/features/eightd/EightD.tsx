import { useEffect, useState } from 'react'
import { USERS } from '../../constants'
import { Badge, Card, Cite, Empty, Field, Page, SectionTitle } from '../../components/ui'
import { ExperienceCard } from '../experience/ExperienceCard'
import { ExportButtons } from '../../components/ExportButtons'
import { say, show, words } from '../../labels'
import type { Ctx, J, Tone } from '../../types'

export const STAGE_LABEL: Record<string, string> = { D0: '위험 평가', D1: '팀', D2: '문제 정의', D3: '임시 봉쇄', D4: '근본 원인', D5: '조치 선정', D6: '실행·효과', D7: '재발 방지', D8: '종결' }
export const GATE_TONE: Record<string, Tone> = { PASS: 'green', WARN: 'amber', UNKNOWN: 'slate', BLOCK: 'red' }
export const stageTone = (s: string | null): Tone => !s ? 'slate' : ['APPROVED', 'DONE', 'CLOSED'].includes(s) ? 'green' : ['REJECTED', 'REVALIDATION_REQUIRED', 'NOT_EFFECTIVE', 'REOPENED'].includes(s) ? 'red' : 'amber'
export const list = (s: string) => s.split(',').map(x => x.trim()).filter(Boolean)
const opts = (xs: string[]) => xs.map(x => <option key={x} value={x}>{say(x)}</option>)
const D2_ROW: Record<string, string> = { what: '무엇이', where: '어디서', when: '언제', who_detected: '누가 발견', how_many: '얼마나', is: '해당 (IS)', is_not: '해당 아님 (IS NOT)' }

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
    cause_type: 'OCCURRENCE', category: 'MACHINE', htext: '', hev: '', causes: '', feasibility: '', risk: '', side: '', risk8: '', owner8: '', notify: '', mit8: '', why4: '', why6: '', why8: '', whyx: '' })
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
  return <Page title="D0~D8 진행" desc="사건을 D0 위험 평가부터 D8 종결까지 단계별로 진행합니다.">
    <Card className="mb"><SectionTitle title="단계 상태" sub={g ? `경로 ${g.route ? say(g.route) : 'D0 판정 전'}` : ''}/>
      <div className="row-gap" style={{ flexWrap: 'wrap' }}>{g && Object.entries(g.state).map(([s, v]) => <span key={s} className="row-gap"><b className="muted">{s} {STAGE_LABEL[s]}</b><Badge tone={stageTone(v as string)}>{v ? say(v as string) : '시작 전'}</Badge></span>)}</div>
      {g && g.urgent_containment.result !== 'PASS' && <p className="muted wrap mt">긴급 봉쇄: {g.urgent_containment.reasons.join(' · ')}</p>}
    </Card>
    <div className="dashboard-main">
      <Card><SectionTitle title="D0 위험 평가"/>
        {t ? <div className="wrap" style={{ fontSize: 11 }}><Badge tone="blue">{say(t.signal_kind)}</Badge> <Badge tone={t.observed_defect === 'DEFECT_CONFIRMED' ? 'red' : 'slate'}>{say(t.observed_defect)}</Badge> <Badge tone="violet">{say(t.route)}</Badge> <Badge>심각도 {say(t.severity)}</Badge>
          <p>{t.rationale}</p><p className="muted">범위 LOT {t.scope_lots.join(', ') || '-'} · 출하분 포함 {t.risk_flags.shipped_in_scope ? '예' : '아니요'} · 평가자 {t.assessor_id}</p><Cite ids={t.evidence_ids}/></div> : <Empty>아직 D0 평가가 없습니다.</Empty>}
        {role === 'REVIEWER' && <div className="mt">
          <div className="dual"><Field label="신호 종류"><select value={f.signal_kind} onChange={set('signal_kind')}>{opts(['SPC_SIGNAL', 'AOI_FAIL', 'CUSTOMER_COMPLAINT', 'OTHER'])}</select></Field>
            <Field label="불량 확인"><select value={f.observed_defect} onChange={set('observed_defect')}>{opts(['SIGNAL_ONLY', 'DEFECT_CONFIRMED', 'UNKNOWN'])}</select></Field>
            <Field label="경로"><select value={f.route} onChange={set('route')}>{opts(['NCR_ONLY', 'FULL_8D', 'EMERGENCY_FULL_8D'])}</select></Field>
            <Field label="심각도"><select value={f.severity} onChange={set('severity')}>{opts(['LOW', 'MEDIUM', 'HIGH'])}</select></Field></div>
          <input className="input" placeholder="범위 LOT (쉼표 구분, 예: L02)" value={f.scope_lots} onChange={set('scope_lots')}/>
          <input className="input" placeholder="판단 근거 (10자 이상)" value={f.rationale} onChange={set('rationale')}/>
          <input className="input" placeholder="근거 기록 ID (선택, 쉼표 구분)" value={f.evidence_ids} onChange={set('evidence_ids')}/>
          <button className="button primary full" onClick={() => run(api(`/cases/${cid}/triage`, 'POST', { signal_kind: f.signal_kind, observed_defect: f.observed_defect, route: f.route, severity: f.severity,
            scope_lots: list(f.scope_lots), rationale: f.rationale, evidence_ids: list(f.evidence_ids), risk_flags: {} }))}>D0 평가 기록</button></div>}
      </Card>
      <Card><SectionTitle title="공정 정보"/>
        {pc ? <div style={{ fontSize: 11 }}><Badge tone="teal">{pc.process_type}</Badge> <span className="muted">{pc.site} · 설비 {pc.equipment.join(', ')}</span>
          <p className="muted">대상 객체 {pc.objects.length}개 · 출하 {pc.objects.filter((o: J) => o.shipment_state === 'SHIPPED').length}개</p></div>
          : <>{role === 'AUTHOR' ? <button className="button secondary" onClick={() => run(api(`/cases/${cid}/process-context`, 'POST', { site: 'SITE-A' }))}>공정 컨텍스트 기록 (PCB_SMT)</button> : <Empty>작성자가 공정 컨텍스트를 기록해야 합니다.</Empty>}</>}
      </Card>
    </div>
    <div className="dashboard-main">
      <Card><SectionTitle title="D1 팀" sub={team ? (team.complete ? '필수 역할 모두 수락' : `미완료: ${team.missing.map(say).join(', ')}`) : ''}/>
        <div className="table-wrap"><table><thead><tr><th>책임</th><th>담당</th><th>상태</th><th>기한</th><th/></tr></thead><tbody>
          {team && Object.entries(team.members).map(([r, m]: [string, J]) => <tr key={r}><td>{say(r)}</td><td>{m.user_id ?? '-'}</td><td><Badge tone={m.status === 'ACCEPTED' ? 'green' : m.status === 'EXCEPTION' ? 'amber' : m.overdue ? 'red' : 'slate'}>{`${say(m.status)}${m.overdue ? ' · 기한 초과' : ''}`}</Badge></td><td>{m.due_at ?? '-'}</td>
            <td>{m.user_id === me?.id && m.status === 'ASSIGNED' && <button className="button success" onClick={() => run(api(`/cases/${cid}/team`, 'POST', { event: 'ACCEPT', responsibility: r }))}>수락</button>}</td></tr>)}
        </tbody></table></div>
        {role === 'AUTHOR' && <div className="row-gap mt"><select value={f.responsibility} onChange={set('responsibility')}>{opts(['LEAD', 'QUALITY', 'PRODUCTION', 'PROCESS', 'SUPPLIER', 'CUSTOMER'])}</select>
          <select value={f.user_id} onChange={set('user_id')}>{USERS.map(u => <option key={u[0]} value={u[0]}>{u[1]}</option>)}</select>
          <button className="button secondary" onClick={() => run(api(`/cases/${cid}/team`, 'POST', { event: 'ASSIGN', responsibility: f.responsibility, user_id: f.user_id }))}>배정</button></div>}
      </Card>
      <Card><SectionTitle title="봉쇄 조치 요청" sub="긴급 봉쇄는 QA/생산, D3 조치 제안은 작성자가 합니다"/>
        <div className="dual"><Field label="조치"><select value={f.action_type} onChange={set('action_type')}>{opts(['HOLD', 'SORT', 'STOP_SHIP', 'QUARANTINE', 'CUSTOMER_NOTIFY_REQUEST', 'OTHER'])}</select></Field>
          <Field label="대상 (쉼표 구분)"><input className="input" style={{ marginTop: 0 }} placeholder="L02-P09" value={f.targets} onChange={set('targets')}/></Field></div>
        <input className="input" placeholder="조치 설명 (10자 이상)" value={f.description} onChange={set('description')}/>
        <div className="dual"><button className="button primary" disabled={role !== 'QA_PRODUCTION'} onClick={() => run(api(`/cases/${cid}/urgent-actions`, 'POST', { action_type: f.action_type, targets: list(f.targets), description: f.description }))}>긴급 봉쇄 요청</button>
          <button className="button secondary" disabled={role !== 'AUTHOR'} onClick={() => run(api(`/cases/${cid}/actions`, 'POST', { action_type: f.action_type, targets: list(f.targets), description: f.description }))}>D3 조치 제안</button></div>
        <p className="muted wrap">대상 예: L02, L02-P09, L02-P09/B1. 이미 출하된 대상은 보류 대신 고객 통보를 요청합니다.</p>
      </Card>
    </div>
    {pd && <Card className="mb"><SectionTitle title="D2 문제 정의 (5W2H · IS / IS NOT)" sub="원본 기록에서 정리한 내용입니다"/>
      <div className="table-wrap"><table><thead><tr><th>항목</th><th>값</th><th>상태</th><th>근거</th></tr></thead><tbody>
        {['what', 'where', 'when', 'who_detected', 'how_many', 'is', 'is_not'].map(k => <tr key={k}><td>{D2_ROW[k]}</td><td className="wrap">{show(pd[k].value)}</td>
          <td><Badge tone={pd[k].status === 'KNOWN' ? 'green' : 'slate'}>{pd[k].status === 'KNOWN' ? '확인됨' : '미확인'}</Badge></td><td><Cite ids={pd[k].evidence_ids}/></td></tr>)}
      </tbody></table></div>
      {pd.unknown_scope.length > 0 && <p className="muted wrap mt">범위가 확인되지 않은 대상 {pd.unknown_scope.length}건</p>}</Card>}
    {xp && <ExperienceCard xp={xp} cid={cid} api={api} run={run} role={role} f={f} set={set}/>}
    {d4 && <Card className="mb"><SectionTitle title="D4 원인 가설 → 실험 → 판정" sub="원인 확정은 공정 엔지니어가 실험 결과를 근거로 합니다"/>
      <div className="table-wrap"><table><thead><tr><th>#</th><th>6M</th><th>유형</th><th>가설</th><th>출처</th><th>실험</th><th>상태</th><th>판정</th></tr></thead><tbody>
        {d4.hypotheses.map((h: J) => { const sup = h.experiments.filter((e: J) => e.result === 'SUPPORTS').map((e: J) => e.experiment_id)
          return <tr key={h.hypothesis_id}><td className="id">H{h.hypothesis_id}</td><td>{say(h.category)}</td><td>{say(h.cause_type)}</td><td className="wrap">{words(h.text)}</td><td>{say(h.origin)}</td>
            <td className="wrap">{h.experiments.map((e: J) => `${say(e.result)} · 표본 ${e.sample_size} (${e.performed_by})`).join(' / ') || '-'}</td>
            <td><Badge tone={h.status === 'CONFIRMED' ? 'green' : h.status === 'REJECTED' ? 'red' : 'amber'}>{h.status}</Badge></td>
            <td>{role === 'PROCESS_ENGINEER' && h.status === 'OPEN' && <div className="row-gap">
              <button className="button success" style={{ height: 26, padding: '0 6px' }} onClick={() => run(api(`/cases/${cid}/causal-decisions`, 'POST', { hypothesis_id: h.hypothesis_id, decision: 'CONFIRMED', basis_experiment_ids: sup, rationale: f.why4 }))} disabled={!f.why4.trim()}>원인 확정</button>
              <button className="button secondary" style={{ height: 26, padding: '0 6px' }} onClick={() => run(api(`/cases/${cid}/causal-decisions`, 'POST', { hypothesis_id: h.hypothesis_id, decision: 'INCONCLUSIVE', rationale: f.why4 }))} disabled={!f.why4.trim()}>판단 보류</button></div>}</td></tr> })}
        {!d4.hypotheses.length && <tr><td colSpan={8}><Empty>가설이 없습니다.</Empty></td></tr>}
      </tbody></table></div>
      {role === 'PROCESS_ENGINEER' && <input className="input" aria-label="D4 판정 사유" placeholder="D4 판정 사유 (필수)" value={f.why4} onChange={set('why4')}/>}
      <div className="row-gap mt" style={{ flexWrap: 'wrap' }}><select value={f.category} onChange={set('category')}>{opts(['MAN', 'MACHINE', 'MATERIAL', 'METHOD', 'MEASUREMENT', 'ENVIRONMENT'])}</select>
        <select value={f.cause_type} onChange={set('cause_type')}>{opts(['OCCURRENCE', 'NON_DETECTION', 'SYSTEMIC'])}</select>
        <input className="input" style={{ flex: 2, marginTop: 0 }} placeholder="가설 (10자 이상)" value={f.htext} onChange={set('htext')}/>
        <input className="input" style={{ flex: 1, marginTop: 0 }} placeholder="근거 기록 ID (선택)" value={f.hev} onChange={set('hev')}/>
        <button className="button secondary" onClick={() => run(api(`/cases/${cid}/hypotheses`, 'POST', { category: f.category, cause_type: f.cause_type, text: f.htext, evidence_ids: list(f.hev) }))}>가설 추가</button></div>
      <p className="muted wrap">확정 원인 {d4.confirmed.length}건 · 5-Why 연결 {d4.why_links.length}건</p></Card>}
    {d6 && <Card className="mb"><SectionTitle title="D5 조치 선정 · D6 효과 검증" sub={`D5 ${d6.D5 ? say(d6.D5) : '시작 전'} · D6 ${d6.D6 ? say(d6.D6) : '시작 전'} · 효과는 미리 정한 기준으로 판정합니다`}/>
      <div className="row-gap" style={{ flexWrap: 'wrap' }}><input className="input" style={{ flex: 1, marginTop: 0 }} placeholder="확정 원인 H# (쉼표, 숫자)" value={f.causes} onChange={set('causes')}/>
        <input className="input" style={{ flex: 1, marginTop: 0 }} placeholder="실현 가능성" value={f.feasibility} onChange={set('feasibility')}/>
        <input className="input" style={{ flex: 1, marginTop: 0 }} placeholder="위험 분석" value={f.risk} onChange={set('risk')}/>
        <input className="input" style={{ flex: 1, marginTop: 0 }} placeholder="부작용" value={f.side} onChange={set('side')}/>
        <button className="button secondary" disabled={!['AUTHOR', 'PROCESS_ENGINEER'].includes(role ?? '')} onClick={() => run(api(`/cases/${cid}/actions`, 'POST', { stage: 'D5', action_type: 'PROCESS_CHANGE', description: f.description,
          cause_ids: list(f.causes).map(Number), details: { feasibility: f.feasibility, risk_analysis: f.risk, side_effects: f.side } }))}>D5 조치안 추가</button></div>
      <p className="muted wrap">조치 설명은 위 봉쇄 조치의 설명 칸에 적습니다. 조치 선정은 아래 조치 기록에서 공정 엔지니어가 '계획 승인'으로 합니다.</p>
      <div className="table-wrap mt"><table><thead><tr><th>계획</th><th>조치</th><th>지표 · 기준</th><th>서버 계산</th><th>결과</th><th>판정</th></tr></thead><tbody>
        {d6.plans.map((p: J) => { const pv = d6.preview[p.plan_id]; const res = d6.results.filter((r: J) => r.plan_id === p.plan_id)
          return <tr key={p.plan_id}><td className="id">#{p.plan_id}</td><td>#{p.action_id}</td><td className="wrap">{say(p.metric)} {p.acceptance.op} {p.acceptance.value} · 비교 LOT {p.baseline_lots.join(',')} · 최소 표본 {p.min_sample}</td>
            <td className="wrap"><Badge tone={pv.computed === 'MEETS_CRITERIA' ? 'green' : pv.computed === 'FAILS_CRITERIA' ? 'red' : 'amber'}>{pv.computed}</Badge> {pv.observed.post ? `전 ${pv.observed.baseline.mean} (${pv.observed.baseline.n}개) → 후 ${pv.observed.post.mean} (${pv.observed.post.n}개)` : ''} {pv.reasons.map(words).join(' · ')}</td>
            <td>{res.map((r: J) => <Badge key={r.result_id} tone={r.decision === 'EFFECTIVE' ? 'green' : r.decision === 'NOT_EFFECTIVE' ? 'red' : 'amber'}>{`${say(r.decision)} (${r.reviewer_id})`}</Badge>)}</td>
            <td>{role === 'REVIEWER' && <div className="row-gap">{['EFFECTIVE', 'NOT_EFFECTIVE', 'INCONCLUSIVE'].map(d => <button key={d} className="button secondary" style={{ height: 26, padding: '0 6px' }}
              onClick={() => run(api(`/cases/${cid}/effectiveness`, 'POST', { plan_id: p.plan_id, decision: d, note: f.why6 }))} disabled={!f.why6.trim()}>{say(d)}</button>)}</div>}</td></tr> })}
        {!d6.plans.length && <tr><td colSpan={6}><Empty>효과 검증 계획이 없습니다.</Empty></td></tr>}
      </tbody></table></div>
      {role === 'REVIEWER' && <input className="input" aria-label="D6 판정 사유" placeholder="D6 효과 판정 사유 (필수)" value={f.why6} onChange={set('why6')}/>}</Card>}
    <div className="dashboard-main">
      {d7 && <Card><SectionTitle title="D7 재발 방지 (문서 개정·교육·수평 전개)" sub={`상태 ${d7.state ? say(d7.state) : '시작 전'} · 발효된 개정 문서만 인정합니다`}/>
        <div className="table-wrap"><table><thead><tr><th>문서</th><th>개정</th><th>범위</th><th>교육</th><th>수평 전개</th></tr></thead><tbody>
          {d7.deployments.map((x: J) => <tr key={x.id}><td>{x.doc_number}</td><td>rev {x.old_revision} → {x.new_revision}</td><td>{x.scopes.join(', ')}</td>
            <td>{x.training.length}/{x.operators_in_scope.length}</td><td className="wrap">{x.sister_lines.map((l: J) => `${l.line}:${l.applies ? '적용' : '제외'}`).join(' · ') || '-'}</td></tr>)}
          {!d7.deployments.length && <tr><td colSpan={5}><Empty>D7 기록이 없습니다.</Empty></td></tr>}
        </tbody></table></div>
        {d7.reasons.length > 0 && <p className="muted wrap mt">남은 일: {d7.reasons.map(words).join(' · ')}</p>}</Card>}
      {d8 && <Card><SectionTitle title="D8 종결" sub={`고객 통보 ${d8.needs_customer_notification ? '필요' : '불필요'} · 확인 서명 ${d8.acknowledged.join(', ') || '없음'}`}/>
        {d8.blocks.length ? <ul className="wrap muted" style={{ fontSize: 11 }}>{d8.blocks.map((b: string) => <li key={b}>{words(b)}</li>)}</ul> : <p className="muted">종결 조건을 모두 충족했습니다.</p>}
        <input className="input" aria-label="D8 사유" placeholder="확인 내용 · 종결 의견 · 재오픈 사유 (필수)" value={f.why8} onChange={set('why8')}/>
        {d8.team[me?.id ?? ''] && !d8.acknowledged.includes(me?.id) && <button className="button success" disabled={!f.why8.trim()} onClick={() => run(api(`/cases/${cid}/closure/acknowledgements`, 'POST', { contribution: f.why8 }))}>결과 확인 서명</button>}
        {role === 'REVIEWER' && <div className="mt"><div className="dual"><input className="input" placeholder="잔여 위험" value={f.risk8} onChange={set('risk8')}/><input className="input" placeholder="위험 담당" value={f.owner8} onChange={set('owner8')}/></div>
          <input className="input" placeholder="잔여 위험 완화 방안" value={f.mit8} onChange={set('mit8')}/>
          <input className="input" placeholder="고객 통보 참조번호 (출하·고객 영향 시 필수)" value={f.notify} onChange={set('notify')}/>
          <div className="dual"><button className="button primary" disabled={!f.why8.trim() || !f.risk8.trim() || !f.mit8.trim()} onClick={() => run(api(`/cases/${cid}/closure`, 'POST', { residual_risks: [{ risk: f.risk8, mitigation: f.mit8, owner: f.owner8 }], customer_notification_ref: f.notify || null, comment: f.why8 }))}>D8 종결</button>
            <button className="button secondary" disabled={d8.state.D8 !== 'CLOSED' || !f.why8.trim()} onClick={() => run(api(`/cases/${cid}/closure/reopen`, 'POST', { reason: f.why8 }))}>재오픈</button></div></div>}
        {d8.state.D8 === 'CLOSED' && <ExportButtons user={me.id} path={`/cases/${cid}/report/export`} label="8D 보고서"/>}
        {d8.history.length > 0 && <p className="muted wrap mt">이력: {d8.history.map((h: J) => `${say(h.decision)} (${h.actor_id})`).join(' → ')}</p>}</Card>}
    </div>
    <Card className="mb"><SectionTitle title="조치 실행 기록" sub="요청 → 계획 승인 → 실행 → 독립 확인 · 실행한 사람과 확인한 사람은 달라야 합니다"/>
      <div className="dual"><input className="input" placeholder="실행·확인 메모 (실행, 해제, 효과 없음은 필수)" value={f.note} onChange={set('note')}/><input className="input" placeholder="확인 근거 기록 ID (선택)" value={f.evidence} onChange={set('evidence')}/></div>
      <div className="table-wrap mt"><table><thead><tr><th>#</th><th>단계</th><th>조치</th><th>대상</th><th>상태</th><th>이력</th><th>기록</th></tr></thead><tbody>
        {acts.map(a => <tr key={a.action_id}><td className="id">{a.action_id}</td><td>{a.stage}</td><td>{say(a.action_type)}</td><td>{a.targets.join(', ')}</td><td><Badge tone={stageTone(a.status)}>{a.status}</Badge></td>
          <td className="wrap">{a.events.map((e: J) => `${say(e.event_type)} (${e.actor_id})`).join(' → ')}</td>
          <td><div className="row-gap">{['PLAN_APPROVED', 'EXECUTED', 'INDEPENDENTLY_VERIFIED', 'RELEASED', 'NOT_EFFECTIVE'].map(ev => <button key={ev} className="button secondary" style={{ height: 26, padding: '0 6px' }}
            onClick={() => run(api(`/cases/${cid}/actions/${a.action_id}/events`, 'POST', { event_type: ev, note: f.note, evidence: list(f.evidence) }))}>{say(ev)}</button>)}</div></td></tr>)}
        {!acts.length && <tr><td colSpan={7}><Empty>조치가 없습니다.</Empty></td></tr>}
      </tbody></table></div>
    </Card>
  </Page>
}
