import { useState } from 'react'
import { Badge, Card, Field, Icon, Page, SectionTitle } from '../../components/ui'
import { useLoad } from '../../hooks/useLoad'
import type { Ctx, J, Tone } from '../../types'

export function Audit({ ctx }: { ctx: Ctx }) {
  const tl = useLoad<J[]>(ctx, ctx.cid ? `/cases/${ctx.cid}/timeline` : '', [])
  const chain = useLoad<J>(ctx, '/audit/verify', null)
  const policies: [string, string, Tone][] = [
    ['미배정 사건 접근', '배정되지 않은 사용자는 403', 'red'], ['외부 전송 제한', 'SYNTHETIC + APPROVED_FOR_EXTERNAL만 Meta로 전송, 그 외 전송 전 차단', 'green'],
    ['감사 기록 불변', 'approval_events · workflow_events 수정/삭제를 DB 트리거로 차단', 'blue'], ['오래된 버전 결재', '최신이 아니거나 해시가 다르면 409', 'amber'], ['AI 조사 쿼터', '사용자당 시간당 10회 초과 시 429', 'amber'], ['운영 한도 변경', 'AI 운영(AGENT_ADMIN)만 사유와 함께 변경, 이력은 추가만 가능', 'violet']]
  return <Page title="감사 및 보안" desc="사건 타임라인과 서버가 강제하는 정책입니다.">
    {chain && <div className={chain.ok ? 'immutable' : 'revision-alert'}><Icon name="shield"/><span><b>감사 해시 체인 {chain.ok ? '무결' : '불일치 발견'}</b> {chain.links}개 기록 검증 · 헤드 {chain.head_sha256.slice(0, 16)}…{!chain.ok && ` · ${chain.breaks.map((x: J) => `${x.table}#${x.row_id} ${x.problem}`).join(', ')}`}</span></div>}
    <div className="security-grid">{policies.map(x => <Card key={x[0]}><div className={`security-icon ${x[2]}`}><Icon name="shield"/></div><b>{x[0]}</b><span className="muted">{x[1]}</span><Badge tone={x[2]}>서버 정책</Badge></Card>)}</div>
    <Card><SectionTitle title="감사 이벤트" sub={`${tl.length}건 · 추가만 가능한 기록`}/><div className="table-wrap"><table><thead><tr><th>시각</th><th>행위자</th><th>이벤트</th><th>내용</th></tr></thead><tbody>
      {tl.map((t, i) => <tr key={i}><td>{t.at.slice(0, 19)}</td><td>{t.actor_id}</td><td><Badge tone={t.event.includes('REVALIDATION') ? 'red' : t.event.startsWith('BASIS') ? 'amber' : t.event === 'APPROVE' ? 'green' : 'slate'}>{t.event}</Badge></td><td className="wrap">{t.detail}</td></tr>)}
    </tbody></table></div></Card>
    <Limits ctx={ctx}/>
  </Page>
}

const BASIS: Record<string, [string, Tone]> = { STANDARD: ['외부 기준', 'blue'], MEASURED: ['측정', 'green'], DERIVED: ['계산', 'teal'], DECISION: ['결정', 'violet'], DEFAULT: ['임의 기본값', 'amber'] }

// Operating limits with where each value comes from; only the AI operations department changes them, with a reason.
function Limits({ ctx }: { ctx: Ctx }) {
  const data = useLoad<J>(ctx, '/limits', null)
  const [form, setForm] = useState({ name: '', value: '', reason: '' })
  const admin = ctx.me?.role === data?.admin_role
  const save = async () => { try { await ctx.api(`/limits/${form.name}`, 'POST', { value: form.value, reason: form.reason }); setForm({ name: '', value: '', reason: '' }); ctx.refresh() } catch { /* error bar */ } }
  if (!data) return null
  return <Card><SectionTitle title="운영 한도" sub={`근거와 함께 공개 · 변경은 ${data.admin_role}만`}/><div className="table-wrap"><table><thead><tr><th>항목</th><th>값</th><th>단위</th><th>근거</th><th>출처</th><th>적용</th></tr></thead><tbody>
    {data.limits.map((l: J) => <tr key={l.name}><td>{l.name}</td><td><b>{String(l.value)}</b></td><td className="wrap">{l.unit}</td><td><Badge tone={BASIS[l.basis]?.[1] ?? 'slate'}>{BASIS[l.basis]?.[0] ?? l.basis}</Badge></td><td className="wrap muted">{l.source}</td><td>{l.set_by}{l.restart_required ? ' · 재시작 필요' : ''}</td></tr>)}
  </tbody></table></div>
    {admin && <div className="row-gap"><select aria-label="변경할 항목" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}><option value="">항목 선택</option>{data.limits.map((l: J) => <option key={l.name}>{l.name}</option>)}</select>
      <input aria-label="새 값" placeholder="새 값" value={form.value} onChange={e => setForm(f => ({ ...f, value: e.target.value }))}/>
      <input aria-label="변경 사유" placeholder="사유 (필수)" value={form.reason} onChange={e => setForm(f => ({ ...f, reason: e.target.value }))}/>
      <button className="button primary" disabled={!form.name || !form.value || !form.reason.trim()} onClick={save}>변경</button></div>}
    {data.history.length > 0 && <Field label="변경 이력">{data.history.map((h: J, i: number) => <span key={i} className="muted">{h.at.slice(0, 19)} · {h.actor_id} · {h.name} = {h.value} · {h.reason}</span>)}</Field>}</Card>
}
