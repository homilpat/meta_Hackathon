import { STATUS_TONE } from '../../constants'
import { Badge, Card, Empty, Page, SectionTitle } from '../../components/ui'
import { useLoad } from '../../hooks/useLoad'
import { words } from '../../labels'
import type { Ctx, J, Tone } from '../../types'

export const TASK: Record<string, [string, Tone]> = {
  REVIEW: ['결재 검토', 'amber'], BASIS_CHECK: ['기반 변경 확인', 'amber'], SEND_FOR_REVIEW: ['검토 요청 가능', 'teal'],
  WAITING_UPSTREAM: ['앞 단계 승인 대기', 'slate'], REDRAFT: ['재작성 필요', 'red'], ANSWER_COMMENT: ['코멘트 답변', 'violet'],
  D0_TRIAGE: ['D0 판정', 'amber'], D0_UNASSIGNED: ['D0 판정자 미배정', 'red'], REQUEST_OPEN: ['요청 등록', 'teal'],
  REQUEST_REPLY: ['회신 업로드', 'blue'], REQUEST_REVIEW: ['회신 검토', 'amber'], HANDOVER_ACCEPT: ['담당 인수', 'violet'],
}
// where a task is done: D0 on the 8D screen, requests and handovers on the requests screen, documents on reports
const SCREEN: Record<string, string> = { triage: 'eightd', request: 'requests', case_owner: 'requests' }
export const APPROVAL_TASKS = ['REVIEW', 'BASIS_CHECK']

// One server queue (/queue), three views: what I own, what my role's department sees, and the human decisions among them.
export type QueueScope = 'mine' | 'department' | 'approvals'
const HEAD: Record<QueueScope, string> = { mine: '내 할 일', department: '부서 할 일', approvals: '승인 대기' }

export function Queue({ ctx, scope }: { ctx: Ctx; scope: QueueScope }) {
  const all = useLoad<J[]>(ctx, `/queue?scope=${scope === 'mine' ? 'mine' : 'department'}`, [])
  const items = scope === 'approvals' ? all.filter(i => APPROVAL_TASKS.includes(i.task)) : all
  const role = ctx.me?.role
  const desc = {
    mine: `${ctx.me?.id ?? '-'}님이 맡은 일입니다.`,
    department: '내 부서가 맡은 일입니다. 담당자가 없는 일은 부서 누구나 처리할 수 있습니다.',
    approvals: '내 결재를 기다리는 문서입니다.',
  }[scope]
  return <Page title={HEAD[scope]} desc={desc}>
    <Card><SectionTitle title="열린 작업" sub={`${items.length}건`} action={<button className="button secondary" onClick={ctx.refresh}>새로고침</button>}/><div className="table-wrap"><table><thead><tr><th>사건</th><th>문서</th><th>상태</th><th>할 일</th><th>담당</th><th>내용</th><th/></tr></thead><tbody>
      {items.map((i, n) => <tr key={n}><td><b className="id">{i.case_id}</b></td><td>{i.doc_type}{i.version ? ` v${i.version}` : ''}</td><td><Badge tone={STATUS_TONE[i.status]}>{i.status}</Badge></td>
        <td><Badge tone={TASK[i.task]?.[1] ?? 'slate'}>{TASK[i.task]?.[0] ?? i.task}</Badge></td><td>{i.owner ?? '부서'}</td><td className="wrap">{i.detail ? words(i.detail) : '-'}</td>
        <td><button className="citation" onClick={() => ctx.open(i.case_id, `${i.kind}:${i.version}`, SCREEN[i.kind] ?? 'reports')}>열기</button></td></tr>)}
    </tbody></table></div>{!items.length && <Empty>열린 작업이 없습니다.</Empty>}</Card>
  </Page>
}
