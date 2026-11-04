import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Requests } from '../src/features/requests/Requests'
import type { Ctx, J } from '../src/types'

afterEach(cleanup)

// RW-UI-01..04 on screen: per-action executor and verifier, handover with both people, a role with nobody named,
// plan approval apart from execution, and a decision whose content changed afterwards.
const RESP: J = {
  case_owner: { user_id: 'alice', pending_handover: null }, approvers: { D2: 'REVIEWER' }, history: [], identity_note: 'X-User는 데모 신원',
  summary: { case_owner: 'alice', current_stage: 'D3', stage_state: 'IN_REVIEW', next_action: '요청 #7 협력사 대책', next_owner: 'dave',
    due_at: '2026-11-01T18:00:00+09:00', overdue: true, blocked_by: ['요청 #7 협력사 대책: HANDOVER_PENDING, OVERDUE'] },
  requests: [{ request_id: 7, title: '협력사 대책', owner_id: 'alice', pending_owner_id: 'dave', reviewer_id: 'bob', due_at: '2026-11-01T18:00:00+09:00',
    states: ['HANDOVER_PENDING', 'OVERDUE', 'AWAITING_REPLY'], submissions: [], reviews: [{ kind: 'AI', submission_version: 1 }] }],
  actions: [
    { action_id: 1, stage: 'URGENT', description: 'hold L02-P09', requested_by: 'erin', plan_approved_by: null, executed_by: 'erin', verified_by: 'bob',
      effect_reviews: [], states: ['EXECUTED', 'VERIFIED'], audit_event_ids: [11, 12], execution_mode: 'SIMULATED' },
    { action_id: 2, stage: 'D5', description: 'replace stencil', requested_by: 'alice', plan_approved_by: 'frank', executed_by: null, verified_by: null,
      effect_reviews: [], states: ['PLAN_APPROVED', 'NOT_EXECUTED'], audit_event_ids: [13], execution_mode: 'SIMULATED' }],
  decisions: [
    { doc_type: 'NCR', version: 1, status: 'DRAFT', content_sha256: 'a'.repeat(64), author_id: 'alice', based_on: [], approver_role: 'REVIEWER',
      assigned_reviewers: [], reviewer: 'ROLE_ONLY_UNASSIGNED', decisions: [], states: ['DRAFT'], audit_event_ids: [1] },
    { doc_type: 'CONTAINMENT', version: 1, status: 'BASIS_CHANGED', content_sha256: 'c'.repeat(64), author_id: 'alice', based_on: ['NCR v1'], approver_role: 'QA_PRODUCTION',
      assigned_reviewers: [{ reviewer_id: 'erin', state: 'DONE' }], reviewer: 'ASSIGNED', states: ['RE_REVIEW_NEEDED'], audit_event_ids: [2, 3],
      decisions: [{ event_id: 9, by: 'erin', role: 'QA_PRODUCTION', action: 'APPROVE', at: '2026-11-02T10:00:00', reason: 'plan ok', content_sha256: 'b'.repeat(64), on_current_content: false }] }],
}

describe('responsibility view', () => {
  it('keeps each action and document apart and shows missing people as missing', async () => {
    const api = vi.fn(async (path: string) => {
      if (path === '/cases/L/responsibilities') return RESP
      if (path === '/cases/L/requests') return []
      if (path === '/cases/L/profile') return { origin: 'INTERNAL', channel: 'MANUAL', profile: [] }
      return {}
    })
    const open = vi.fn()
    render(<Requests ctx={{ cid: 'L', me: { id: 'alice', role: 'AUTHOR' }, api, refresh: vi.fn(), tick: 0, open, focus: '' }}/>)
    expect(await screen.findByText('지금 누가 무엇을')).toBeTruthy()
    expect(screen.getAllByText('기한 초과').length).toBeGreaterThan(0)
    expect(screen.getByText('인수 대기')).toBeTruthy()
    expect(screen.getByText(/인수 예정/).textContent).toContain('수락 전에는 alice 책임')
    expect(screen.getByText('담당 미배정')).toBeTruthy()
    expect(screen.getAllByText('미실행').length).toBeGreaterThan(0) // action 2: plan approved, nothing executed
    expect(screen.getByText('계획 승인')).toBeTruthy()
    expect(screen.getByText('근거 변경 · 재검토 필요')).toBeTruthy()
    expect(screen.getByText('결정 이후 내용 변경')).toBeTruthy()
    expect(screen.getByText('AI 검토 · 참고')).toBeTruthy() // an AI review is never shown as a person's decision
    const first = screen.getByText(/조치 #1/).closest('.tool-item')!
    expect(first.textContent).toContain('독립 확인 bob') // action 1's verifier stays on action 1
    expect(screen.getByText(/조치 #2/).closest('.tool-item')!.textContent).toContain('독립 확인 미확인')
  })
})
