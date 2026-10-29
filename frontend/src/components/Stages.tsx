import { KINDS } from '../constants'
import type { Ctx, J } from '../types'
import { useLoad } from '../hooks/useLoad'
import { Icon } from './ui'

// 8D order from the API: drafts can be written ahead, review/approval opens only after the step before is APPROVED.
export function Stages({ ctx }: { ctx: Ctx }) {
  const st = useLoad<J[]>(ctx, `/cases/${ctx.cid}/stages`, [])
  return <div className="report-steps">{st.map(s => {
    const done = s.status === 'APPROVED'
    return <div key={s.kind} title={s.blocked_by ?? ''} className={done ? 'done' : s.approval_open ? 'active' : 'future'}><i>{done ? <Icon name="check" size={13}/> : s.step}</i>
      <span>{KINDS.find(k => k[0] === s.kind)![2]}</span><small>{s.version ? `v${s.version} · ${s.status}` : '미작성'}{!s.approval_open && ' · 결재 잠금 (앞 단계 미승인)'}</small></div>
  })}</div>
}
