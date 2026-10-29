import { Badge, Card, Icon, Page, SectionTitle } from '../../components/ui'
import { useLoad } from '../../hooks/useLoad'
import type { Ctx, J, Tone } from '../../types'

export function Audit({ ctx }: { ctx: Ctx }) {
  const tl = useLoad<J[]>(ctx, `/cases/${ctx.cid}/timeline`, [])
  const chain = useLoad<J>(ctx, '/audit/verify', null)
  const policies: [string, string, Tone][] = [
    ['미배정 사건 접근', '배정되지 않은 사용자는 403', 'red'], ['외부 전송 제한', 'SYNTHETIC + APPROVED_FOR_EXTERNAL만 Meta로 전송, 그 외 전송 전 차단', 'green'],
    ['감사 기록 불변', 'approval_events · workflow_events 수정/삭제를 DB 트리거로 차단', 'blue'], ['오래된 버전 결재', '최신이 아니거나 해시가 다르면 409', 'amber'], ['AI 조사 쿼터', '사용자당 시간당 10회 초과 시 429', 'amber']]
  return <Page title="감사 및 보안" desc="사건 타임라인과 서버가 강제하는 정책입니다.">
    {chain && <div className={chain.ok ? 'immutable' : 'revision-alert'}><Icon name="shield"/><span><b>감사 해시 체인 {chain.ok ? '무결' : '불일치 발견'}</b> {chain.links}개 기록 검증 · 헤드 {chain.head_sha256.slice(0, 16)}…{!chain.ok && ` · ${chain.breaks.map((x: J) => `${x.table}#${x.row_id} ${x.problem}`).join(', ')}`}</span></div>}
    <div className="security-grid">{policies.map(x => <Card key={x[0]}><div className={`security-icon ${x[2]}`}><Icon name="shield"/></div><b>{x[0]}</b><span className="muted">{x[1]}</span><Badge tone={x[2]}>서버 정책</Badge></Card>)}</div>
    <Card><SectionTitle title="감사 이벤트" sub={`${tl.length}건 · 추가만 가능한 기록`}/><div className="table-wrap"><table><thead><tr><th>시각</th><th>행위자</th><th>이벤트</th><th>내용</th></tr></thead><tbody>
      {tl.map((t, i) => <tr key={i}><td>{t.at.slice(0, 19)}</td><td>{t.actor_id}</td><td><Badge tone={t.event.includes('REVALIDATION') ? 'red' : t.event.startsWith('BASIS') ? 'amber' : t.event === 'APPROVE' ? 'green' : 'slate'}>{t.event}</Badge></td><td className="wrap">{t.detail}</td></tr>)}
    </tbody></table></div></Card>
  </Page>
}
