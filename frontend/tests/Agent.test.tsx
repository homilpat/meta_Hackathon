import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Agent, plannerLabel } from '../src/features/agent/Agent'
import type { Ctx, J } from '../src/types'

// A persisted run as the server returns it (contract for /agent/runs). The UI only renders it.
const RUN: J = {
  run_id: 7, case_id: 'C1', user_id: 'alice', goal: '이번 LOT 불량을 조사하고 8D 보고서 초안을 준비해 줘.', planner: 'SERVER_RULES',
  status: 'NEEDS_HUMAN', created_at: '2026-10-30T01:00:00', updated_at: '2026-10-30T01:00:05',
  plan: [{ tool: 'case_summary', title: '사건 범위와 증거 버전 확인', status: 'DONE', note: 'AOI FAIL 1건' },
    { tool: 'prepare_document', title: '다음 8D 문서 초안 · 검증', status: 'NEEDS_HUMAN', note: 'NCR v1 초안 저장됨 (DRAFT, 승인 아님)' },
    { tool: 'request_review', title: '검토 요청 (사람 확인 필요)', status: 'NEEDS_HUMAN', note: '' }],
  reply: [{ text: 'AOI FAIL 1건 · AOI 기록 없는 보드 0건 · LOT L01', steps: [1] }],
  pending: { action: 'request_review', token: '7:4', kind: 'ncr', version: 1, content_sha256: 'ab', validation: 'PASS', approver_role: 'REVIEWER',
    candidates: [{ user_id: 'bob', name: 'Bob (reviewer)', role: 'REVIEWER' }, { user_id: 'carol', name: 'Carol (reviewer)', role: 'REVIEWER' }] },
  steps: [
    { seq: 1, tool: 'case_summary', kind: 'READ', status: 'OK', http_status: 200, duration_ms: 12, audit_event_ids: [], args: {},
      result: { lots: [{ lot: 'L01', stencil: 'STN-1', lot_ev: 'EV-9', aoi: 4, fail: 1, not_cleared: 0 }], aoi_fail: [{ board: 'P1/B1', aoi: ['FAIL', 'EV-3'], human: ['DEFECT_CONFIRMED', 'EV-4'] }], no_aoi_record: [] } },
    { seq: 2, tool: 'create_draft', kind: 'WRITE', status: 'OK', http_status: 201, duration_ms: 30, audit_event_ids: [41], args: { kind: 'ncr' },
      result: { doc_type: 'NCR', version: 1, status: 'DRAFT', claims: [{}, {}], reviews: [] } },
    { seq: 3, tool: 'validate_document', kind: 'WRITE', status: 'OK', http_status: 201, duration_ms: 9, audit_event_ids: [42], args: { kind: 'ncr', version: 1 },
      result: { result: 'PASS', issues: [], stale: false } },
    { seq: 4, tool: 'approve_document', kind: 'CHECK', status: 'DENIED', http_status: null, duration_ms: 0, audit_event_ids: [], args: {},
      result: null, error: 'not on the agent allowlist' },
  ],
}

function ctxWith(api: Ctx['api'], over: Partial<Ctx> = {}): Ctx {
  return { cid: 'C1', me: { id: 'alice', role: 'AUTHOR' }, api, refresh: vi.fn(), tick: 0, open: vi.fn(), focus: '', ...over }
}
afterEach(cleanup)

describe('Agent workspace', () => {
  it('restores the persisted run: plan, recorded steps, draft is not approval, denied tool shown as denied', async () => {
    const api = vi.fn(async () => [RUN])
    render(<Agent ctx={ctxWith(api)} provider={{ configured: false }} go={vi.fn()}/>)
    expect(await screen.findByText(RUN.goal)).toBeTruthy()
    expect(api).toHaveBeenCalledWith('/agent/runs?case_id=C1')
    expect(screen.getAllByText('사람 확인 필요').length).toBeGreaterThan(0)
    expect(screen.getByText('초안')).toBeTruthy()  // a draft reads as a draft, never as approved
    expect(screen.getByText('검증 통과')).toBeTruthy()
    expect(screen.getByText('not on the agent allowlist')).toBeTruthy()
    expect(screen.getByText('거부됨')).toBeTruthy()
    expect(screen.queryByText(/#41/)).toBeNull()  // audit row ids stay in the audit screen
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('1')
  })

  it('a review request needs a chosen reviewer and sends the pending token once, even on a double click', async () => {
    let resolve: (v: J) => void = () => {}
    const api = vi.fn(async (path: string, _method?: string, _body?: unknown) => path.startsWith('/agent/runs?') ? [RUN] : new Promise(r => { resolve = r }))
    const ctx = ctxWith(api as Ctx['api'])
    render(<Agent ctx={ctx} provider={null} go={vi.fn()}/>)
    const send = await screen.findByRole('button', { name: '검토 요청 보내기' })
    expect((send as HTMLButtonElement).disabled).toBe(true) // two candidates: nobody is preselected
    fireEvent.click(screen.getByLabelText(/Bob \(reviewer\)/))
    await act(async () => { fireEvent.click(send); fireEvent.click(send) })
    const posts = api.mock.calls.filter(c => c[1] === 'POST')
    expect(posts).toEqual([['/agent/runs/7/resume', 'POST', { token: '7:4', confirm: true, reviewer_id: 'bob', answer: null }]])
    await act(async () => { resolve({ ...RUN, status: 'COMPLETED', pending: null, reply: [{ text: '서버 확인: NCR v1 IN_REVIEW → bob', steps: [5] }] }) })
    expect(await screen.findByText('서버 확인: NCR v1 IN_REVIEW → bob')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '검토 요청 보내기' })).toBeNull()
    expect(ctx.refresh).toHaveBeenCalled()
  })

  it('sends a goal for the current case with an idempotency key', async () => {
    const api = vi.fn(async (path: string, method?: string) => method === 'POST' ? { ...RUN, run_id: 8, goal: '내 할 일 알려줘', status: 'COMPLETED', pending: null } : [])
    render(<Agent ctx={ctxWith(api as Ctx['api'])} provider={null} go={vi.fn()}/>)
    expect(await screen.findByText('무엇을 도와드릴까요?')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Agent에게 보낼 목표'), { target: { value: '내 할 일 알려줘' } })
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: '메시지 전송' })) })
    expect(api).toHaveBeenCalledWith('/agent/runs', 'POST', { case_id: 'C1', goal: '내 할 일 알려줘' }, true)
    await waitFor(() => expect(screen.getAllByText('내 할 일 알려줘').length).toBeGreaterThan(0))
  })

  it('when the agent service is down it says so and offers the manual paths', async () => {
    const go = vi.fn()
    render(<Agent ctx={ctxWith(vi.fn(async () => { throw new Error('503') }))} provider={null} go={go}/>)
    expect(await screen.findByText('Agent 서비스에 연결할 수 없습니다')).toBeTruthy()
    expect((screen.getByLabelText('Agent에게 보낼 목표') as HTMLTextAreaElement).disabled).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: '승인 대기' }))
    expect(go).toHaveBeenCalledWith('approvals')
  })

  it('offers only the approved versions for export and never downloads by itself', async () => {
    const exportsRun = { ...RUN, status: 'COMPLETED', pending: null, plan: [], reply: [], steps: [
      { seq: 1, tool: 'exports', kind: 'READ', status: 'OK', http_status: 200, duration_ms: 3, audit_event_ids: [], args: {},
        result: { documents: [{ kind: 'ncr', doc_type: 'NCR', version: 2, path: '/cases/C1/documents/ncr/export?version=2' }], report: null } },
      { seq: 2, tool: 'exports', kind: 'READ', status: 'OK', http_status: 200, duration_ms: 3, audit_event_ids: [], args: {},
        result: { documents: [], report: null } }] }
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    render(<Agent ctx={ctxWith(vi.fn(async () => [exportsRun]))} provider={null} go={vi.fn()}/>)
    expect(await screen.findByRole('button', { name: 'NCR 승인본 PDF' })).toBeTruthy()
    expect(screen.getByText('NCR v2 승인됨')).toBeTruthy()
    expect(fetchSpy).not.toHaveBeenCalled() // a file is made only when the user clicks
    vi.unstubAllGlobals()
  })

  it('asks back for a vague goal and sends the typed answer with the pending token', async () => {
    const asked = { ...RUN, status: 'NEEDS_HUMAN', steps: [], plan: [], reply: [{ text: '무엇을 도와드릴까요?', steps: [] }],
      pending: { action: 'clarify', token: '7:1', question: '무엇을 도와드릴까요?' } }
    const api = vi.fn(async (path: string, _m?: string, _b?: unknown) => path.startsWith('/agent/runs?') ? [asked] : { ...asked, status: 'COMPLETED', pending: null })
    render(<Agent ctx={ctxWith(api as Ctx['api'])} provider={null} go={vi.fn()}/>)
    const send = await screen.findByRole('button', { name: '답변 보내기' })
    expect((send as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('Agent 질문에 대한 답변'), { target: { value: '불량 원인 조사' } })
    await act(async () => { fireEvent.click(send) })
    expect(api).toHaveBeenCalledWith('/agent/runs/7/resume', 'POST', { token: '7:1', confirm: true, reviewer_id: null, answer: '불량 원인 조사' })
  })

  it('offers to fill D0 first; the filled form is submitted only by the D0 role and by a click', async () => {
    const offer = { ...RUN, status: 'NEEDS_HUMAN', steps: [], plan: [], reply: [],
      pending: { action: 'offer_fill', token: '7:2', form: 'triage', question: 'D0 판정 양식을 채워 드릴까요?' } }
    const filled = { ...RUN, status: 'COMPLETED', pending: null, plan: [], reply: [], steps: [
      { seq: 3, tool: 'fill_triage', kind: 'PROPOSE', status: 'OK', http_status: 200, duration_ms: 5, audit_event_ids: [], args: {},
        result: { form: 'triage', basis: ['SPC 첫 경보: L02'], notes: [],
          fields: { signal_kind: 'SPC_SIGNAL', observed_defect: 'DEFECT_CONFIRMED', scope_lots: ['L02'], route: 'EMERGENCY_FULL_8D',
            severity: 'HIGH', risk_flags: { customer_impact: true }, rationale: '불량 확정, 출하 포함', evidence_ids: ['EV-1'] },
          submit: { path: '/cases/C1/triage', role: 'REVIEWER', can_submit: false } } }] }
    const api = vi.fn(async (path: string, method?: string, _b?: unknown) => path.startsWith('/agent/runs?') ? [offer] : method === 'POST' ? filled : [])
    render(<Agent ctx={ctxWith(api as Ctx['api'])} provider={null} go={vi.fn()}/>)
    const yes = await screen.findByRole('button', { name: '예, 채워 주세요' }) // find outside act: act holds renders
    await act(async () => { fireEvent.click(yes) })
    expect(api).toHaveBeenCalledWith('/agent/runs/7/resume', 'POST', { token: '7:2', confirm: true, reviewer_id: null, answer: null })
    const submit = await screen.findByRole('button', { name: '검토자만 제출할 수 있습니다' })
    expect((submit as HTMLButtonElement).disabled).toBe(true) // alice cannot record D0; nothing was stored
    expect(screen.getByDisplayValue('긴급 8D')).toBeTruthy()
    expect(api.mock.calls.some(c => c[0] === '/cases/C1/triage')).toBe(false)
  })

  it('labels the planner from the provider status and never claims LIVE without verification', () => {
    expect(plannerLabel(null)[0]).toBe('AI 오프라인 · 서버 규칙 플래너')
    expect(plannerLabel({ configured: true, live_status: 'TEST_DOUBLE' })[0]).toMatch(/LIVE 아님/)
    expect(plannerLabel({ configured: true, model: 'm', live_status: 'CONFIGURED_NOT_VERIFIED' })[0]).toBe('') // a set key shows no badge
    expect(plannerLabel({ configured: true, model: 'm', live_status: 'VERIFIED' })[0]).toMatch(/LIVE 검증됨/)
  })
})
