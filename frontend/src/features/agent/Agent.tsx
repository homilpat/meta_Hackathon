import { useEffect, useRef, useState } from 'react'
import { Badge, Card, Icon } from '../../components/ui'
import type { Ctx, J, Tone } from '../../types'
import { RunView } from './RunView'

// What the provider status actually says; never "LIVE" unless the server verified a LIVE run.
export function plannerLabel(provider: J): [string, Tone] {
  if (!provider?.configured) return ['AI 오프라인 · 서버 규칙 플래너', 'slate']
  if (provider.live_status === 'VERIFIED') return [`Meta ${provider.model} · LIVE 검증됨`, 'green']
  if (provider.live_status === 'TEST_DOUBLE') return ['TEST_DOUBLE 플래너 (LIVE 아님)', 'amber']
  return [`Meta ${provider.model} · 키 설정됨, LIVE 미검증`, 'amber']
}

const EXAMPLES = ['이번 SPC 경보, 8D로 가야 할지 판정해 줘', '이번 LOT 불량 원인을 조사해 줘', 'NCR 초안 써 줘', '내 할 일 알려줘', '8D 진행 상태와 차단 사유 알려줘']

export function Agent({ ctx, provider, go }: { ctx: Ctx; provider: J; go: (view: string) => void }) {
  const [runs, setRuns] = useState<J[] | null>(null)
  const [down, setDown] = useState('')
  const [goal, setGoal] = useState('')
  const [busy, setBusy] = useState(false)
  const inFlight = useRef(false) // state updates are async; a second click in the same tick must still be refused

  useEffect(() => { // restore this case's runs from the server on every entry, user or case change
    let live = true
    setRuns(null); setDown('')
    if (ctx.cid) ctx.api(`/agent/runs?case_id=${encodeURIComponent(ctx.cid)}`)
      .then(r => live && setRuns(r)).catch(e => live && setDown(String(e.message ?? e)))
    return () => { live = false }
  }, [ctx.cid, ctx.api, ctx.tick]) // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (call: () => Promise<J>) => {
    if (inFlight.current) return // one request at a time; the server also rejects a repeated decision
    inFlight.current = true; setBusy(true)
    try {
      const run = await call()
      setRuns(rs => [run, ...(rs ?? []).filter(r => r.run_id !== run.run_id)])
      ctx.refresh() // queue, context panel and other screens re-read the same server state
      return run
    } catch { return null } finally { inFlight.current = false; setBusy(false) } // the shell's error bar shows the server's reason
  }
  const send = async () => {
    const text = goal.trim()
    if (!text) return
    if (await act(() => ctx.api('/agent/runs', 'POST', { case_id: ctx.cid, goal: text }, true))) setGoal('')
  }
  const resume = (run: J) => (confirm: boolean, reviewer?: string, answer?: string) =>
    act(() => ctx.api(`/agent/runs/${run.run_id}/resume`, 'POST', { token: run.pending.token, confirm, reviewer_id: reviewer ?? null, answer: answer ?? null }))

  const [label, tone] = plannerLabel(provider)
  const ordered = [...(runs ?? [])].reverse() // oldest first, like a conversation
  return <main className="agent-page">
    <div className="agent-heading"><div><span className="eyebrow"><i/>QualityOps Agent</span><h1>품질 조사 워크스페이스</h1>
      <p>목표를 말하면 Agent가 허용된 도구로 근거 조회부터 문서 초안·검증·검토 요청 준비까지 계획하고, 사람의 결정이 필요한 곳에서 멈춥니다.</p></div>
      <Badge tone={tone}>{label}</Badge></div>
    {down ? <Card className="fallback"><div className="fallback-icon"><Icon name="warning" size={24}/></div><h2>Agent 서비스에 연결할 수 없습니다</h2>
      <p>서버 응답: {down}. Agent 없이도 할 일, 승인, 8D, 문서 편집·검증은 기존 화면에서 계속할 수 있습니다.</p>
      <div className="row-gap" style={{ justifyContent: 'center' }}><button className="button secondary" onClick={ctx.refresh}>다시 연결</button>
        <button className="button primary" onClick={() => go('my')}>내 할 일</button><button className="button secondary" onClick={() => go('approvals')}>승인 대기</button>
        <button className="button secondary" onClick={() => go('eightd')}>D0~D8 진행</button><button className="button secondary" onClick={() => go('reports')}>문서 · 결재</button></div></Card>
      : <div className="conversation">
        {runs === null && <p className="muted">서버에서 이 사건의 Agent 기록을 불러오는 중…</p>}
        {runs?.length === 0 && <Card><b>이 사건의 Agent 기록이 없습니다.</b><p className="muted">예시:</p><div className="row-gap">{EXAMPLES.map(x => <button key={x} className="button secondary" onClick={() => setGoal(x)}>{x}</button>)}</div></Card>}
        {ordered.map(r => <div key={r.run_id}>
          <div className="message user-message"><div className="avatar user">{r.user_id[0].toUpperCase()}</div><div><span>{r.user_id} · {r.created_at?.slice(0, 19)}</span><p className="wrap">{r.goal}</p></div></div>
          <RunView run={r} ctx={ctx} busy={busy} onResume={resume(r)}/></div>)}
      </div>}
    <div className="composer"><div className="composer-input">
      <textarea aria-label="Agent에게 보낼 목표" value={goal} disabled={!!down || !ctx.cid} onChange={e => setGoal(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send() } }}
        placeholder={ctx.cid ? 'Agent에게 품질 관리 목표를 설명하세요… (Enter 전송, Shift+Enter 줄바꿈)' : '배정된 사건이 없습니다'}/>
      <div><span>현재 사건과 연결됨 · {ctx.cid || '-'} · 사용자 {ctx.me?.id ?? '-'} ({ctx.me?.role ?? '-'})</span>
        <button className="send" aria-label="메시지 전송" disabled={busy || !goal.trim() || !!down || !ctx.cid} onClick={send}><Icon name="arrow"/></button></div></div>
      <p>{busy ? '서버가 실행 중입니다…' : 'Agent의 모든 도구 호출과 결과는 서버에 기록되며, 권한·승인 정책은 서버가 판단합니다.'}</p></div>
  </main>
}
