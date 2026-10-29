import { useState } from 'react'
import { APPROVER_ROLE, CLASS_TONE, KINDS, STATUS_TONE } from '../../constants'
import { Stages } from '../../components/Stages'
import { Badge, Card, Cite, Empty, Icon, Note, Page, SectionTitle } from '../../components/ui'
import { useLoad } from '../../hooks/useLoad'
import { DocEditor } from './DocEditor'
import { ExportButtons } from '../../components/ExportButtons'
import type { Ctx, J } from '../../types'

export function Reports({ ctx }: { ctx: Ctx }) {
  const lists = KINDS.map(([k]) => useLoad<J[]>(ctx, `/cases/${ctx.cid}/${k}`, [])) // fixed order, safe for hooks
  const stages = useLoad<J[]>(ctx, `/cases/${ctx.cid}/stages`, [])
  const all = KINDS.flatMap(([k], i) => lists[i].map(d => ({ ...d, kind: k })))
  const [selKey, setSelKey] = useState(ctx.focus)
  const [comment, setComment] = useState('')
  const [note, setNote] = useState('')
  const [claimFor, setClaimFor] = useState('')
  const [replyTo, setReplyTo] = useState<number | null>(null)
  const d = all.find(x => `${x.kind}:${x.version}` === selKey) ?? all[all.length - 1]
  const author = ctx.me?.role === 'AUTHOR'
  const create = async (k: string) => { const r = await ctx.api(`/cases/${ctx.cid}/${k}`, 'POST', {}, true); setSelKey(`${k}:${r.version}`); ctx.refresh() }
  const latestOf = (x: J) => { const l = lists[KINDS.findIndex(k => k[0] === x.kind)]; return l[l.length - 1]?.version === x.version }
  const approver = d && KINDS.find(k => k[0] === d.kind)![3]
  const stage = d && stages.find(s => s.kind === d.kind)
  const act = async (path: string, body: J) => { await ctx.api(`/cases/${ctx.cid}/${d.kind}/${d.version}/${path}`, 'POST', body, true); setComment(''); ctx.refresh() }
  const say = async () => { await act('comments', { body: note, claim_id: claimFor || null, reply_to: replyTo }); setNote(''); setReplyTo(null) }
  const resolve = async (id: number) => { await act(`comments/${id}/resolve`, { body: note }); setNote('') }
  const openOn = (cl: string) => (d?.comments ?? []).filter((x: J) => x.open && x.claim_id === cl).length
  return <Page title="문서 및 결재" desc="8D 순서: D2 NCR(검토자) → D3 임시조치 계획(QA/생산) → D4 원인 가설(공정 엔지니어). 초안은 미리 쓸 수 있지만 결재는 앞 단계 승인 후에만 열립니다."
    action={author && <span>{KINDS.map(([k, t]) => <button key={k} className="button secondary" onClick={() => create(k)}>{t} 초안 생성</button>)}</span>}>
    <Card className="mb"><Stages ctx={ctx}/></Card>
    <div className="report-layout">
      <Card><SectionTitle title="문서 목록" sub={`${all.length}개 버전`}/>{all.map(x => <div key={`${x.kind}:${x.version}`} className={`doc-row ${x === d ? 'selected' : ''}`} onClick={() => setSelKey(`${x.kind}:${x.version}`)}>
        <Icon name="document"/><div><b>{x.doc_type} <small>v{x.version}</small></b><span>근거 주장 {x.claims.length}개 · {x.author_id}</span></div><Badge tone={STATUS_TONE[x.status]}>{x.status}</Badge></div>)}
        {!all.length && <Empty>문서가 없습니다.</Empty>}</Card>
      {d ? <Card className="document-view"><div className="doc-title"><div><Badge tone="teal">{d.doc_type} · v{d.version}</Badge> <Badge tone={STATUS_TONE[d.status]}>{d.status}</Badge><h3>{d.doc_type} {d.case_id}</h3>
        <span>작성 {d.author_id} · {d.created_at.slice(0, 19)} · 템플릿 {d.template_version} · 기반 {d.based_on.join(', ') || '-'} · 생성기 {d.builder}</span></div>
        <a className="button secondary" href={`/cases/${d.case_id}/${d.kind}/${d.version}/html`} onClick={async e => { e.preventDefault(); const w = window.open(''); w?.document.write(await (await fetch(`/cases/${d.case_id}/${d.kind}/${d.version}/html`, { headers: { 'X-User': ctx.me.id } })).text()) }}>HTML 보기</a></div>
        {d.status === 'APPROVED' && <ExportButtons key={`${d.kind}:${d.version}`} user={ctx.me.id} path={`/cases/${d.case_id}/documents/${d.kind}/export?version=${d.version}`} label="승인본"/>}
        {d.note && <Note>{d.note}</Note>}
        <div className="table-wrap"><table><thead><tr><th>ID</th><th>구분</th><th>주장</th><th>근거</th><th>코멘트</th></tr></thead><tbody>{d.claims.map((c: J) =>
          <tr key={c.claim_id}><td>{c.claim_id}</td><td><Badge tone={CLASS_TONE[c.classification]}>{c.classification}</Badge></td><td className="wrap">{c.text}</td><td className="wrap"><Cite ids={c.evidence_ids}/></td>
            <td><button className="citation" onClick={() => { setClaimFor(c.claim_id); setReplyTo(null) }}>{openOn(c.claim_id) ? `열림 ${openOn(c.claim_id)}` : '+'}</button></td></tr>)}</tbody></table></div>
        <p className="muted">SHA-256 {d.content_sha256}</p></Card> : <Card><Empty>문서를 선택하세요.</Empty></Card>}
      {d && <div className="stack"><Card><SectionTitle title="검토 및 결재"/>
        {d.reviews.map((r: J, i: number) => <div className="reviewer" key={i}><div className="avatar">{r.reviewer_id[0].toUpperCase()}</div><div><b>{r.reviewer_id}</b><span>검토 요청 · {r.state}</span></div></div>)}
        {d.decisions.map((x: J, i: number) => <div className="detail-row" key={i}><span>{x.action} · {x.actor_id}</span><b>{x.comment || '-'}</b></div>)}
        <div className="role-note"><Icon name="shield"/><span>{d.doc_type} 승인 권한: {APPROVER_ROLE[d.doc_type]}</span></div>
        {d.status === 'DRAFT' && latestOf(d) && stage && !stage.approval_open && <Note>결재 잠금: {stage.blocked_by}</Note>}
        {author && d.author_id === ctx.me.id && d.status === 'DRAFT' && latestOf(d) && <button className="button primary full" disabled={!stage?.approval_open} onClick={() => act('request-review', { reviewer_id: approver })}>{approver}에게 검토 요청</button>}
        {d.status === 'BASIS_CHANGED' && <Note>기반 문서가 정정으로 재검토 중입니다. 이 문서의 내용은 정정된 행을 인용하지 않아 그대로이지만, {APPROVER_ROLE[d.doc_type]}가 새 기반에서 범위가 유효한지 확인해야 다음 단계 결재가 열립니다.</Note>}
        {ctx.me?.role === APPROVER_ROLE[d.doc_type] && d.status === 'BASIS_CHANGED' && <>
          <input className="input" placeholder="확인 의견 (필수 · 자유 서술)" value={comment} onChange={e => setComment(e.target.value)}/>
          <div className="dual"><button className="button success" disabled={!comment.trim()} onClick={() => act('basis-check', { decision: 'NO_SCOPE_IMPACT', comment, content_sha256: d.content_sha256 })}>범위 영향 없음</button>
            <button className="button danger" disabled={!comment.trim()} onClick={() => act('basis-check', { decision: 'REVISE', comment, content_sha256: d.content_sha256 })}>재작성 필요</button></div></>}
        {ctx.me?.role === APPROVER_ROLE[d.doc_type] && d.status === 'IN_REVIEW' && latestOf(d) && <>
          <input className="input" placeholder="검토 의견 (반려·추가 정보 요청 시 필수)" value={comment} onChange={e => setComment(e.target.value)}/>
          <div className="dual"><button className="button success" onClick={() => act('decision', { decision: 'APPROVE', comment, content_sha256: d.content_sha256 })}>승인</button>
            <button className="button danger" disabled={!comment.trim()} onClick={() => act('decision', { decision: 'REJECT', comment, content_sha256: d.content_sha256 })}>반려</button></div>
          <button className="button secondary full" disabled={!comment.trim()} onClick={() => act('decision', { decision: 'REQUEST_INFO', comment, content_sha256: d.content_sha256 })}>추가 정보 요청</button></>}
      </Card>
      <DocEditor ctx={ctx} d={d} latest={latestOf(d)} onSaved={v => setSelKey(`${d.kind}:${v}`)}/>
      <Card><SectionTitle title="검토 코멘트" sub="주장 단위 · 감사 기록에 남음" action={<Badge tone={d.comments.some((x: J) => x.open) ? 'violet' : 'slate'}>열림 {d.comments.filter((x: J) => x.open).length}</Badge>}/>
        {d.comments.filter((x: J) => !x.reply_to).map((x: J) => <div key={x.comment_id} className="comment">
          <div className="detail-row"><span>{x.claim_id ?? '문서 전체'} · {x.actor_id} · {x.created_at.slice(11, 19)}</span><Badge tone={x.open ? 'violet' : 'green'}>{x.open ? '열림' : '해결'}</Badge></div>
          <p>{x.body}</p>
          {d.comments.filter((r: J) => r.reply_to === x.comment_id).map((r: J) => <p key={r.comment_id} className="muted">↳ {r.actor_id}{r.kind === 'RESOLVE' ? ' (해결)' : ''}: {r.body}</p>)}
          {x.open && <span className="row-gap"><button className="citation" onClick={() => { setReplyTo(x.comment_id); setClaimFor(x.claim_id ?? '') }}>답글</button>
            {(ctx.me?.id === d.author_id || ctx.me?.id === x.actor_id) && <button className="citation" disabled={!note.trim()} title="아래 코멘트 칸에 해결 내용을 적은 뒤 누르세요" onClick={() => resolve(x.comment_id)}>해결 처리</button>}</span>}</div>)}
        <div className="row-gap"><select value={claimFor} onChange={e => setClaimFor(e.target.value)}><option value="">문서 전체</option>{d.claims.map((c: J) => <option key={c.claim_id}>{c.claim_id}</option>)}</select>
          {replyTo && <Badge tone="violet">#{replyTo}에 답글</Badge>}</div>
        <input className="input" placeholder="코멘트 (해결 처리 시 메모로도 사용)" value={note} onChange={e => setNote(e.target.value)}/>
        <button className="button secondary full" disabled={!note.trim()} onClick={say}>코멘트 남기기</button></Card>
      <Card><SectionTitle title="책임 추적" sub="이 버전에 누가 어떤 역할로 무엇을 했는지 · 수정 불가 기록"/>
        <div className="tool-timeline">{d.trail.map((t: J, i: number) => <div className="tool-item" key={i}><i className={t.event === 'APPROVE' ? 'green' : 'amber'}>{t.event === 'APPROVE' && <Icon name="check" size={12}/>}</i>
          <time>{t.at.slice(11, 19)}</time><div><b>{t.event} · {t.actor_id} ({t.role})</b><span>{t.detail}</span></div></div>)}</div></Card>
      <Card><SectionTitle title="문서 주의사항"/><p className="muted">임시조치 계획 승인은 물리적 조치 완료를 의미하지 않습니다.</p><p className="muted">원인 가설 승인은 근본원인 확정을 의미하지 않습니다.</p></Card></div>}
    </div>
  </Page>
}
