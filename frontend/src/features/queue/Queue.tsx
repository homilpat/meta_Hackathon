import { STATUS_TONE } from '../../constants'
import { Badge, Card, Empty, Page, SectionTitle } from '../../components/ui'
import { useLoad } from '../../hooks/useLoad'
import type { Ctx, J, Tone } from '../../types'

export const TASK: Record<string, [string, Tone]> = {
  REVIEW: ['결재 검토', 'amber'], BASIS_CHECK: ['기반 변경 확인', 'amber'], SEND_FOR_REVIEW: ['검토 요청 가능', 'teal'],
  WAITING_UPSTREAM: ['앞 단계 승인 대기', 'slate'], REDRAFT: ['재작성 필요', 'red'], ANSWER_COMMENT: ['코멘트 답변', 'violet'],
}
export const APPROVAL_TASKS = ['REVIEW', 'BASIS_CHECK']

// One server queue (/queue), three views: what I own, what my role's department sees, and the human decisions among them.
export type QueueScope = 'mine' | 'department' | 'approvals'
const HEAD: Record<QueueScope, string> = { mine: '내 할 일', department: '부서 할 일', approvals: '승인 대기' }

export function Queue({ ctx, scope }: { ctx: Ctx; scope: QueueScope }) {
  const all = useLoad<J[]>(ctx, `/queue?scope=${scope === 'mine' ? 'mine' : 'department'}`, [])
  const items = scope === 'approvals' ? all.filter(i => APPROVAL_TASKS.includes(i.task)) : all
  const role = ctx.me?.role
  const desc = {
    mine: `${ctx.me?.id ?? '-'}님이 담당자인 일: 지정된 검토, 내가 승인한 문서의 기반 확인, 내 문서의 재작성·코멘트 답변.`,
    department: `${role ?? '-'} 역할 전체가 볼 일입니다. 배정된 사건 기준이며, 담당자가 비어 있으면 부서 누구나 처리할 수 있습니다.`,
    approvals: `${role ?? '-'} 역할에 요청된 결재 검토와 기반 변경 확인입니다. 결정은 문서 화면에서 사람이 내리며 Agent는 승인하지 않습니다.`,
  }[scope]
  return <Page title={HEAD[scope]} desc={desc}>
    <Card><SectionTitle title="열린 작업" sub={`${items.length}건 · 서버 /queue 기준`} action={<button className="button secondary" onClick={ctx.refresh}>새로고침</button>}/><div className="table-wrap"><table><thead><tr><th>사건</th><th>문서</th><th>상태</th><th>할 일</th><th>담당</th><th>내용</th><th/></tr></thead><tbody>
      {items.map((i, n) => <tr key={n}><td><b className="id">{i.case_id}</b></td><td>{i.doc_type} v{i.version}</td><td><Badge tone={STATUS_TONE[i.status]}>{i.status}</Badge></td>
        <td><Badge tone={TASK[i.task]?.[1] ?? 'slate'}>{TASK[i.task]?.[0] ?? i.task}</Badge></td><td>{i.owner ?? '부서'}</td><td className="wrap">{i.detail || '-'}</td>
        <td><button className="citation" onClick={() => ctx.open(i.case_id, `${i.kind}:${i.version}`)}>열기</button></td></tr>)}
    </tbody></table></div>{!items.length && <Empty>열린 작업이 없습니다.</Empty>}</Card>
  </Page>
}
