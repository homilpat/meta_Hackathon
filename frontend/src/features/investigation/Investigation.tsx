import { useState } from 'react'
import { CLASS_TONE, STATUS_TONE } from '../../constants'
import { Badge, Card, Cite, Empty, Icon, Note, Page, SectionTitle } from '../../components/ui'
import { useLoad } from '../../hooks/useLoad'
import { say, words } from '../../labels'
import type { Ctx, J } from '../../types'

export function Investigation({ ctx, provider }: { ctx: Ctx; provider: J }) {
  const runs = useLoad<J[]>(ctx, `/cases/${ctx.cid}/investigations`, [])
  const [history, setHistory] = useState(true)
  const r = runs[runs.length - 1]
  const author = ctx.me?.role === 'AUTHOR'
  const [busy, setBusy] = useState(false)
  const run = async () => { setBusy(true); try { await ctx.api(`/cases/${ctx.cid}/investigations`, 'POST', { use_history: history }, true); ctx.refresh() } catch { /* error bar */ } finally { setBusy(false) } }
  const draft = async (k: string) => { await ctx.api(`/cases/${ctx.cid}/${k}`, 'POST', { investigation_run_id: r.run_id }, true); ctx.refresh() }
  return <Page title="AI 품질 조사" desc="AI가 사건 기록을 읽고 고객 주장과 내부 기록을 비교해 보고서를 씁니다.">
    <div className="hero-banner"><div className="hero-icon"><Icon name="spark" size={22}/></div><div><b>{provider?.configured ? `Meta ${provider.model}` : 'AI 연결 안 됨'}</b>
      <span>{provider?.configured ? '조사는 1분쯤 걸립니다.' : 'AI가 연결되지 않아 조사를 실행할 수 없습니다.'}</span></div>
      <label className="muted"><input type="checkbox" checked={history} onChange={e => setHistory(e.target.checked)}/> 과거 사례도 참고</label>
      <button className="button primary" disabled={busy || !author || !provider?.configured} onClick={run}>{busy ? <><span className="spinner"/> 조사 중…</> : '조사 실행'}</button></div>
    {!r ? <Card><Empty>이 사건의 조사 실행 기록이 없습니다.</Empty></Card> : <div className="workbench">
      <div className="stack"><Card><SectionTitle title="실행 정보"/>{[['실행 시각', r.started_at.slice(0, 16).replace('T', ' ')], ['요청한 사람', r.requested_by ?? '-'], ['과거 사례 참고', r.history === 'ON' ? '예' : '아니요']].map(x =>
        <div className="detail-row" key={x[0]}><span>{x[0]}</span><b>{x[1]}</b></div>)}<div className="divider"/><Badge tone={STATUS_TONE[r.status] ?? 'slate'}>{r.status}</Badge>{r.mode !== 'LIVE' && <> <Badge tone="amber">시험용 응답</Badge></>}</Card></div>
      <div className="stack center-col">
        <Card className="ai-summary"><div className="ai-head"><div className="hero-icon"><Icon name="spark"/></div><div><b>조사 요약</b><span>기록 조회 {r.tool_calls.length}회</span></div></div>{!r.report ? <p>보고서 없음</p> : r.status === 'VALIDATED' ? <p>{words(r.report.summary)}</p>
          : r.status === 'INCOMPLETE' ? <><Badge tone="amber">필수 항목 미완료 · 초안 불가</Badge><p className="muted">{r.report.summary}</p><ul className="muted">{r.validation_errors.map((e: string, i: number) => <li key={i}>{words(e)}</li>)}</ul></>
          : <><Badge tone="red">기록과 맞지 않아 사용할 수 없음</Badge><p className="muted">{r.report.summary}</p></>}{r.report?.data_warnings?.length > 0 && <div className="mt">{r.report.data_warnings.map((w: J, i: number) => <Note key={i}><Badge tone={w.source === 'SERVER' ? 'red' : 'amber'}>{w.source === 'SERVER' ? '서버 감지 · 지시문' : 'AI 보고 · 지시문'}</Badge> {w.text} <span className="muted">(데이터 속 문장이며 따르지 않았습니다)</span></Note>)}</div>}{r.attempts?.length > 1 && <p className="muted">서버 검사에서 고칠 점이 나와 AI가 {r.attempts.length - 1}번 고쳐 썼습니다</p>}</Card>
        {r.report?.next_evidence_requests?.length > 0 && <Card className="recommend"><SectionTitle title="다음에 확인할 것"/>{r.report.next_evidence_requests.map((n: J, i: number) =>
          <div className="rec-row" key={i}><b className="rank">{i + 1}</b><div><strong>{words(n.check)}</strong><span>{words(n.reason)}</span><Cite ids={[...(n.evidence_ids ?? []), ...(n.precedent_ids ?? [])]}/></div></div>)}</Card>}
      </div>
      <div className="stack">
        <Card><SectionTitle title="발견 사항"/>{(r.report?.findings ?? []).map((f: J, i: number) =>
          <div className="claim" key={i}><Icon name="chevron"/><div><b>{words(f.text)}{f.value != null && ` (${f.value}${f.unit ? ` ${f.unit}` : ''})`}</b><Badge tone={CLASS_TONE[f.classification]}>{say(f.classification)}</Badge><Cite ids={f.evidence_ids}/></div></div>)}</Card>
        {r.validation_errors.length > 0 && <Card className="blocked"><SectionTitle title="기록과 맞지 않은 부분" action={<Badge tone="red">{r.validation_errors.length}건</Badge>}/>{r.validation_errors.map((e: string) =>
          <div className="blocked-box" key={e}><Icon name="shield"/><div><span>{words(e)}</span></div></div>)}</Card>}
      </div>
    </div>}
    {r && <div className="action-bar"><div><Icon name="shield"/><span><b>문서로 만들기</b> 기록에서 확인한 내용은 D2 NCR로, 원인 후보는 D4 원인 가설로 옮깁니다.</span></div>
      <span className="row-gap"><button className="button primary" disabled={!author || r.status !== 'VALIDATED'} onClick={() => draft('ncr')}>D2 NCR 초안</button>
        <button className="button secondary" disabled={!author || r.status !== 'VALIDATED'} onClick={() => draft('rca')}>D4 원인 가설 초안</button></span></div>}
  </Page>
}
