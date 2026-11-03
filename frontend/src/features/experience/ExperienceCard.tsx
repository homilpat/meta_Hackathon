import { Badge, Card, Note, SectionTitle } from '../../components/ui'
import { say } from '../../labels'
import type { Ctx, J } from '../../types'

// Experience Memory on the D0~D8 screen: retrieval, mode, matches and the three human choices (never a D5 approval).
export function ExperienceCard({ xp, cid, api, run, role, f, set }: { xp: J; cid: string; api: Ctx['api']; run: (p: Promise<unknown>) => Promise<unknown>
  role: string | undefined; f: Record<string, string>; set: (k: string) => (e: { target: { value: string } }) => void }) {
  return (
    <Card className="mb"><SectionTitle title="과거 비슷한 사건" sub={xp.latest ? `결과: ${say(xp.latest.mode)} · 비슷하다고 원인이 확정되지는 않습니다 · 고른다고 조치가 승인되지는 않습니다` : '아직 찾아보지 않았습니다'}/>
      <span className="row-gap"><button className="button secondary" onClick={() => run(api(`/cases/${cid}/experience/retrievals`, 'POST', { q: f.htext }))}>과거 사례 찾기</button>
        <button className="button secondary" onClick={() => run(api(`/cases/${cid}/experience/retrievals`, 'POST', { q: f.htext, ai: true }))}>AI로 넓혀 찾기 · 비교</button></span>
      {xp.latest?.ai && <p className="muted wrap">AI {xp.latest.ai.status} · {xp.latest.ai.mode} · 조건은 맞지만 단어가 달라 빠진 사례 {xp.latest.ai.read.length}건을 읽고 {xp.latest.ai.picked.length}건을 같은 문제로 골랐습니다 · 모드는 서버가 기록(효과·재발·적용 조건)으로 정합니다</p>}
      {xp.latest?.mode === 'NO_RELEVANT_HISTORY' && <Note>{xp.latest.note}</Note>}
      {xp.latest && <div className="table-wrap mt"><table><thead><tr><th>사례</th><th>판단</th><th>그때 한 조치</th><th>결과</th><th>같은 조건</th><th>다른 점 · 주의</th><th>선택</th></tr></thead><tbody>
        {xp.latest.matches.map((m: J) => <tr key={m.entry_key}><td className="id" title={m.entry_key}>{m.source_ref ?? m.entry_key}</td>
          <td><Badge tone={m.mode === 'KNOWN' ? 'green' : 'amber'}>{say(m.mode)}</Badge> <Badge tone={m.role === 'PRIOR_RESPONSE' ? 'blue' : 'red'}>{say(m.role)}</Badge>{m.found_by === 'AI_MATCH' && <> <Badge tone="violet">AI가 같은 문제로 고름</Badge><div className="muted">{m.ai_reason}</div></>}</td>
          <td className="wrap">{m.action}</td><td>{say(m.outcome)} · {say(m.recurrence)}</td><td className="wrap">{m.matched_factors.join(', ')}</td>
          <td className="wrap">{[...m.differing_factors, ...m.warnings].join(' · ') || '-'}{m.ai_review && <div className="muted">AI 비교: {m.ai_review.note}{m.ai_review.disagreements.length > 0 && <> · <Badge tone="red">기록과 다름</Badge> {m.ai_review.disagreements.join(' · ')}</>}</div>}</td>
          <td><div className="row-gap">{xp.latest.choices.filter((ch: string) => ch !== 'REVIEW_PRIOR_RESPONSE' || m.role === 'PRIOR_RESPONSE').map((ch: string) => <button key={ch} className="button secondary" style={{ height: 26, padding: '0 6px' }}
            disabled={!['AUTHOR', 'PROCESS_ENGINEER'].includes(role ?? '') || !f.whyx.trim()} onClick={() => run(api(`/cases/${cid}/experience/decisions`, 'POST', { retrieval_id: xp.latest.retrieval_id, entry_key: m.entry_key, decision: ch, reason: f.whyx }))}>{say(ch)}</button>)}</div></td></tr>)}
      </tbody></table></div>}
      {xp.latest && ['AUTHOR', 'PROCESS_ENGINEER'].includes(role ?? '') && <input className="input" aria-label="선택 사유" placeholder="선택 사유 (필수 · 자유 서술 · 감사 기록에 그대로 남음)" value={f.whyx} onChange={set('whyx')}/>}
      {xp.decisions.length > 0 && <p className="muted wrap mt">선택 기록: {xp.decisions.map((d: J) => `${say(d.decision)} ${d.entry_key} (${d.actor_id})${d.stale ? ' · STALE' : ''}`).join(' · ')}</p>}</Card>
  )
}
