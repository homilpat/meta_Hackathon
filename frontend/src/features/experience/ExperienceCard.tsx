import { Badge, Card, Note, SectionTitle } from '../../components/ui'
import type { Ctx, J } from '../../types'

// Experience Memory on the D0~D8 screen: retrieval, mode, matches and the three human choices (never a D5 approval).
export function ExperienceCard({ xp, cid, api, run, role, f }: { xp: J; cid: string; api: Ctx['api']; run: (p: Promise<unknown>) => Promise<unknown>
  role: string | undefined; f: Record<string, string> }) {
  return (
    <Card className="mb"><SectionTitle title="과거 동일·유사 사건 (Experience Memory)" sub={xp.latest ? `모드 ${xp.latest.mode} · 검색 #${xp.latest.retrieval_id} · 유사도 ≠ 원인 확정 · 선택 ≠ D5 승인` : '아직 검색하지 않았습니다'}/>
      <button className="button secondary" onClick={() => run(api(`/cases/${cid}/experience/retrievals`, 'POST', { q: f.htext }))}>과거 사례 검색 (서버 결정론)</button>
      {xp.latest?.prompt && <Note>{xp.latest.prompt}</Note>}
      {xp.latest?.mode === 'NO_RELEVANT_HISTORY' && <Note>{xp.latest.note}</Note>}
      {xp.latest && <div className="table-wrap mt"><table><thead><tr><th>사례</th><th>모드·역할</th><th>조치</th><th>결과·재발</th><th>일치</th><th>차이</th><th>선택</th></tr></thead><tbody>
        {xp.latest.matches.map((m: J) => <tr key={m.entry_key}><td className="id">{m.entry_key}</td>
          <td><Badge tone={m.mode === 'KNOWN' ? 'green' : 'amber'}>{m.mode}</Badge> <Badge tone={m.role === 'PRIOR_RESPONSE' ? 'blue' : 'red'}>{m.role}</Badge></td>
          <td className="wrap">{m.action}</td><td>{m.outcome} · {m.recurrence}</td><td className="wrap">{m.matched_factors.join(', ')}</td>
          <td className="wrap">{[...m.differing_factors, ...m.warnings].join(' · ') || '-'}</td>
          <td><div className="row-gap">{xp.latest.choices.filter((ch: string) => ch !== 'REVIEW_PRIOR_RESPONSE' || m.role === 'PRIOR_RESPONSE').map((ch: string) => <button key={ch} className="button secondary" style={{ height: 26, padding: '0 6px' }}
            disabled={!['AUTHOR', 'PROCESS_ENGINEER'].includes(role ?? '')} onClick={() => run(api(`/cases/${cid}/experience/decisions`, 'POST', { retrieval_id: xp.latest.retrieval_id, entry_key: m.entry_key, decision: ch, reason: f.note || 'reviewed against current line conditions' }))}>{ch}</button>)}</div></td></tr>)}
      </tbody></table></div>}
      {xp.decisions.length > 0 && <p className="muted wrap mt">선택 기록: {xp.decisions.map((d: J) => `${d.decision} ${d.entry_key} (${d.actor_id})${d.stale ? ' · STALE' : ''}`).join(' · ')}</p>}</Card>
  )
}
