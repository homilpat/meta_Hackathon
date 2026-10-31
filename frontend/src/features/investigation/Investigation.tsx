import { useState } from 'react'
import { CLASS_TONE, STATUS_TONE } from '../../constants'
import { Badge, Card, Cite, Empty, Icon, Page, SectionTitle } from '../../components/ui'
import { useLoad } from '../../hooks/useLoad'
import type { Ctx, J } from '../../types'

export function Investigation({ ctx, provider }: { ctx: Ctx; provider: J }) {
  const runs = useLoad<J[]>(ctx, `/cases/${ctx.cid}/investigations`, [])
  const [history, setHistory] = useState(true)
  const r = runs[runs.length - 1]
  const author = ctx.me?.role === 'AUTHOR'
  const run = async () => { await ctx.api(`/cases/${ctx.cid}/investigations`, 'POST', { use_history: history }, true); ctx.refresh() }
  const draft = async (k: string) => { await ctx.api(`/cases/${ctx.cid}/${k}`, 'POST', { investigation_run_id: r.run_id }, true); ctx.refresh() }
  return <Page title="AI 품질 조사" desc="Meta 모델이 읽기 전용 도구로 근거를 조회하고, 서버가 보고서를 검증합니다.">
    <div className="hero-banner"><div className="hero-icon"><Icon name="spark" size={22}/></div><div><b>{provider?.live_status === 'VERIFIED' ? `LIVE 검증됨 · ${provider.model}` : provider?.configured ? `${provider.model} · 키 설정됨 (LIVE 미검증)` : `${provider?.model ?? 'Meta'} · 키 미설정`}</b>
      <span>{provider?.configured ? 'SYNTHETIC·외부 승인 데이터만 전송됩니다. 결론 승인과 원인 확정은 사람이 합니다.' : 'MODEL_API_KEY가 없어 조사를 실행할 수 없습니다. 대체(목) 응답은 없습니다.'}</span></div>
      <label className="muted"><input type="checkbox" checked={history} onChange={e => setHistory(e.target.checked)}/> 과거 사례 사용 (History ON)</label>
      <button className="button primary" disabled={!author || !provider?.configured} onClick={run}>조사 실행</button></div>
    {!r ? <Card><Empty>이 사건의 조사 실행 기록이 없습니다.</Empty></Card> : <div className="workbench">
      <div className="stack"><Card><SectionTitle title="실행 정보"/>{[['실행', `Run ${r.run_id}`], ['모드', r.mode === 'LIVE' ? 'LIVE Meta 호출' : 'TEST DOUBLE (Meta 아님)'], ['모델', r.model], ['History', r.history], ['라운드', r.rounds], ['토큰', `${r.prompt_tokens}/${r.completion_tokens}`]].map(x =>
        <div className="detail-row" key={x[0]}><span>{x[0]}</span><b>{x[1]}</b></div>)}<div className="divider"/><Badge tone={STATUS_TONE[r.status] ?? 'slate'}>{r.status}</Badge>{r.error && <p className="muted">{r.error}</p>}</Card></div>
      <div className="stack center-col">
        <Card className="ai-summary"><div className="ai-head"><div className="hero-icon"><Icon name="spark"/></div><div><b>조사 요약</b><span>{r.started_at.slice(0, 19)} · 도구 호출 {r.tool_calls.length}회</span></div></div>{!r.report ? <p>보고서 없음</p> : r.status === 'VALIDATED' ? <p>{r.report.summary}</p>
          : <><Badge tone="red">검증 실패 · 사용 불가</Badge><p className="muted">{r.report.summary}</p></>}</Card>
        <Card><SectionTitle title="도구 실행 타임라인" sub="결과 본문 대신 해시만 기록"/><div className="tool-timeline">{r.tool_calls.map((c: J, i: number) =>
          <div className="tool-item" key={i}><i className={c.ok ? 'green' : 'amber'}>{c.ok && <Icon name="check" size={12}/>}</i><time>R{c.round}</time><div><b>{c.tool_name}</b><span>{c.ok ? `sha256 ${c.result_sha256?.slice(0, 12)}…` : c.error}</span></div></div>)}</div></Card>
        {r.report?.next_evidence_requests?.length > 0 && <Card className="recommend"><SectionTitle title="다음 증거 요청" sub="조치 권고가 아닌 확인 요청"/>{r.report.next_evidence_requests.map((n: J, i: number) =>
          <div className="rec-row" key={i}><b className="rank">{i + 1}</b><div><strong>{n.check}</strong><span>{n.reason}</span><small>{[...(n.evidence_ids ?? []), ...(n.precedent_ids ?? [])].join(' · ')}</small></div></div>)}</Card>}
      </div>
      <div className="stack">
        <Card><SectionTitle title="주장별 근거 수준"/>{(r.report?.findings ?? []).map((f: J, i: number) =>
          <div className="claim" key={i}><Icon name="chevron"/><div><b>{f.text}</b><Badge tone={CLASS_TONE[f.classification]}>{f.classification}</Badge><Cite ids={f.evidence_ids}/></div></div>)}</Card>
        {r.validation_errors.length > 0 && <Card className="blocked"><SectionTitle title="차단된 주장" action={<Badge tone="red">{r.validation_errors.length}건</Badge>}/>{r.validation_errors.map((e: string) =>
          <div className="blocked-box" key={e}><Icon name="shield"/><div><span>{e}</span></div></div>)}</Card>}
      </div>
    </div>}
    {r && <div className="action-bar"><div><Icon name="shield"/><span><b>사람 승인 필수</b> 사실 관측은 D2 NCR, 원인 후보와 모델 출력은 D4 원인 가설 초안으로 나뉩니다. 임시조치 계획은 템플릿으로 작성합니다.</span></div>
      <span className="row-gap"><button className="button primary" disabled={!author || r.status !== 'VALIDATED'} onClick={() => draft('ncr')}>D2 NCR 초안</button>
        <button className="button secondary" disabled={!author || r.status !== 'VALIDATED'} onClick={() => draft('rca')}>D4 원인 가설 초안</button></span></div>}
  </Page>
}
