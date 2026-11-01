import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IntakeCard } from '../src/features/intake/Intake'
import { Requests } from '../src/features/requests/Requests'
import type { Ctx, J } from '../src/types'

const ctxWith = (api: Ctx['api'], over: Partial<Ctx> = {}): Ctx =>
  ({ cid: '', me: { id: 'alice', role: 'AUTHOR' }, api, refresh: vi.fn(), tick: 0, open: vi.fn(), focus: '', ...over })
afterEach(cleanup)

const FIELDS = (lot: J) => ({
  customer_ref: { status: 'FOUND', value: 'HM-CC-2026-0417', kind: 'CUSTOMER_REPORTED', candidates: [], rejected: [],
    sources: [{ element_id: 'pdf:p1:l3', page: 1, excerpt: 'HM-CC-2026-0417', file_id: 1 }] },
  lot, customer_cause_claim: { status: 'FOUND', value: 'likely solder paste', kind: 'HYPOTHESIS', candidates: [], rejected: [],
    sources: [{ element_id: 'pdf:p1:l6', page: 1, excerpt: 'likely', file_id: 1 }] },
})
const CONFLICT = { status: 'CONFLICT', value: null, kind: 'CUSTOMER_REPORTED', sources: [], rejected: [], candidates: [
  { value: 'L02', sources: [{ element_id: 'pdf:p1:l12', page: 1, excerpt: 'L02' }] },
  { value: 'L03', sources: [{ element_id: 'docx:t1:r3:c1', excerpt: 'L03' }] }] }
const VIEW = (lot: J, version = 1) => ({ intake_id: 3, files: [{ file_id: 1, name: 'c.pdf', data_origin: 'SYNTHETIC',
  coverage: { text: 'OK', tables: 'PARTIAL', images: 'OK', charts: 'IMAGE_ONLY', scan: 'NEEDS_VISION', render: 'OK' }, checks: {} }],
  draft: { version, kind: 'EXTRACTION', mode: 'TEST_DOUBLE', status: 'OK', model: 'scripted', prompt_version: 'abc', withheld: [], changes: [],
    fields: FIELDS(lot), documents: [], links: [], notes: ['검사 모수가 확인되지 않아 불량률을 계산하지 않습니다.'], questions: ['LOT가 다릅니다'], flags: [] } })

describe('intake card', () => {
  it('shows locators and conflicts, blocks confirmation until a person resolves them, then confirms that version', async () => {
    let view: J = VIEW(CONFLICT)
    const api = vi.fn(async (path: string, method = 'GET', body?: J) => {
      if (path === '/cases') return [{ case_id: 'L' }]
      if (path.endsWith('/draft/edits')) { view = VIEW({ ...CONFLICT, status: 'USER_SET', value: body.changes[0].value, candidates: [] }, 2); return view }
      if (path.endsWith('/confirm')) return { case_id: 'CC-3', origin: 'CUSTOMER_COMPLAINT', channel: 'CHAT_UPLOAD', owner_id: 'alice', d0: 'PENDING',
        assignees: ['alice'], internal_data: { linked: false, note: '내부 데이터가 연결되지 않았습니다' }, intakes: [{}] }
      return method === 'GET' ? view : null
    })
    render(<IntakeCard ctx={ctxWith(api)} intake={{ intake_id: 3, files: [] }}/>)
    expect(await screen.findByText('문서 간 충돌')).toBeTruthy()
    expect(screen.getByText('TEST_DOUBLE (Meta 아님)')).toBeTruthy()
    expect(screen.getByText('가설')).toBeTruthy()
    expect(screen.getByText('pdf:p1:l3 (p.1)')).toBeTruthy()
    const confirm = screen.getByRole('button', { name: /확인하고 사건 생성/ }) as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'L02 선택' }))
    fireEvent.change(screen.getByLabelText('LOT 수정 사유'), { target: { value: '고객 통화로 확인' } })
    fireEvent.click(screen.getByRole('button', { name: '수정 저장 (새 버전)' }))
    await waitFor(() => expect(api).toHaveBeenCalledWith('/intakes/3/draft/edits', 'POST', { base_version: 1, changes: [
      { field: 'lot', value: 'L02', reason: '고객 통화로 확인', element_id: 'pdf:p1:l12', excerpt: 'L02' }] }, true))
    await waitFor(() => expect((screen.getByRole('button', { name: /확인하고 사건 생성/ }) as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(screen.getByRole('button', { name: /확인하고 사건 생성/ }))
    await waitFor(() => expect(api).toHaveBeenCalledWith('/intakes/3/confirm', 'POST', { base_version: 2, action: 'NEW_CASE' }, true))
    expect(await screen.findByText('내부 데이터가 연결되지 않았습니다')).toBeTruthy()
  })
})

const REQ: J = { request_id: 5, case_id: 'SN-1', kind: 'SUPPLIER_CORRECTIVE_ACTION', title: '8D 회신', items: [{ item_id: 'I1', requirement: '봉쇄', required_evidence: '보류 기록', criterion: '기록 존재' }],
  owner_id: 'alice', pending_owner_id: null, reviewer_id: 'bob', external_party: { org: 'Daeil' }, due_at: '2026-11-10T18:00:00+09:00', due_tz: 'KST', overdue: false,
  status: 'IN_REVIEW', submission_version: 2, created_by: 'alice', note: '회신 수용은 요청 답변의 수용일 뿐입니다.',
  submissions: [{ version: 1, current: false, files: [{ name: 'v1.docx' }], submitted_by: { org: 'Daeil', identity: 'DOCUMENT_STATED' }, registered_by: 'alice', files_sha256: 'a'.repeat(64) },
    { version: 2, current: true, files: [{ name: 'v2.docx' }], submitted_by: { org: 'Daeil', identity: 'DOCUMENT_STATED' }, registered_by: 'alice', files_sha256: 'b'.repeat(64) }],
  reviews: [{ kind: 'AI', submission_version: 2, mode: 'TEST_DOUBLE', items: [{ item_id: 'I1', verdict: 'NEEDS_HUMAN', note: '근거 위치 확인 안 됨', sources: [] }] }], events: [] }

describe('requests screen', () => {
  it('shows the AI opinion as an opinion and decides on the current version and file hash', async () => {
    const api = vi.fn(async (path: string) => {
      if (path === '/cases/SN-1/requests') return [REQ]
      if (path === '/cases/SN-1/responsibilities') return { case_owner: { user_id: 'alice', pending_handover: null }, approvers: { D0: 'REVIEWER' }, executors: [], effect_verifiers: [], history: [], identity_note: 'X-User는 데모 신원' }
      if (path === '/cases/SN-1/profile') return { origin: 'SUPPLIER_NONCONFORMITY', channel: 'MANUAL', profile: [] }
      return {}
    })
    render(<Requests ctx={ctxWith(api, { cid: 'SN-1', me: { id: 'bob', role: 'REVIEWER' } })}/>)
    expect(await screen.findByText('NEEDS_HUMAN')).toBeTruthy()
    expect(screen.getByText(/AI 의견 \(결정 아님\)/)).toBeTruthy()
    expect(screen.getByText(/회신 v1:/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText('결정'), { target: { value: 'NEEDS_REVISION' } })
    fireEvent.change(screen.getByLabelText('결정 사유'), { target: { value: '보류 기록 번호 없음' } })
    fireEvent.click(screen.getByRole('button', { name: 'v2 결정' }))
    await waitFor(() => expect(api).toHaveBeenCalledWith('/requests/5/decisions', 'POST',
      { submission_version: 2, files_sha256: 'b'.repeat(64), decision: 'NEEDS_REVISION', reason: '보류 기록 번호 없음' }, true))
  })
})
