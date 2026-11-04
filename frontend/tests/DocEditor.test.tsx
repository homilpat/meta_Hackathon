import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DocEditor } from '../src/features/documents/DocEditor'

const doc = { kind: 'ncr', version: 1, content_sha256: 'abc', claims: [{ claim_id: 'C1', classification: 'CALCULATED', text: 'AOI FAIL is 3.2%.', value: 3.2, unit: '%', evidence_ids: ['E1'] }] }

function setup(responses: Record<string, unknown>) {
  const api = vi.fn(async (path: string, method = 'GET') => {
    const hit = Object.entries(responses).find(([k]) => `${method} ${path}`.endsWith(k))
    if (!hit) throw new Error('404')
    return hit[1]
  })
  const ctx = { cid: 'L', me: { id: 'alice', role: 'AUTHOR' }, api, refresh: vi.fn(), tick: 0 } as never
  const onSaved = vi.fn()
  render(<DocEditor ctx={ctx} d={doc} latest onSaved={onSaved}/>)
  return { api, onSaved }
}

afterEach(cleanup)

describe('DocEditor', () => {
  it('saves a manual edit as a new version against the exact hash, sending only the changed field', async () => {
    const { api, onSaved } = setup({ 'POST /cases/L/ncr/1/edits': { version: 2 } })
    fireEvent.change(screen.getByLabelText('편집할 주장'), { target: { value: 'C1' } })
    fireEvent.change(screen.getByLabelText('주장 문장'), { target: { value: 'AOI FAIL is about 3.2%.' } })
    fireEvent.change(screen.getByLabelText('수정 사유'), { target: { value: 'clearer wording' } })
    fireEvent.click(screen.getByText('새 버전으로 저장'))
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(2))
    expect(api).toHaveBeenCalledWith('/cases/L/ncr/1/edits', 'POST', { expected_sha256: 'abc', reason: 'clearer wording',
      changes: [{ claim_id: 'C1', text: 'AOI FAIL is about 3.2%.' }], ai_proposal: false }, true)
  })

  it('shows an AI proposal without applying it until the person accepts', async () => {
    const proposal = { provider_mode: 'TEST_DOUBLE', changes: [{ claim_id: 'C1', text: 'Short.' }],
      diff: [{ claim_id: 'C1', change: 'CHANGED', fields: { text: ['AOI FAIL is 3.2%.', 'Short.'] } }] }
    const { api, onSaved } = setup({ 'POST /cases/L/ncr/1/edit-proposals': proposal, 'POST /cases/L/ncr/1/edits': { version: 2 } })
    fireEvent.change(screen.getByLabelText('AI 지시'), { target: { value: 'shorter' } })
    fireEvent.click(screen.getByText('AI 제안 받기 (적용 안 됨)'))
    await screen.findByText(/수락하면 새 버전으로 저장됩니다/)
    expect(api.mock.calls.some(c => c[0].endsWith('/edits'))).toBe(false)
    fireEvent.change(screen.getByLabelText('수정 사유'), { target: { value: 'accepted AI wording' } })
    fireEvent.click(screen.getByText('제안 수락하여 저장'))
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(2))
    expect(api).toHaveBeenCalledWith('/cases/L/ncr/1/edits', 'POST', expect.objectContaining({ changes: proposal.changes, ai_proposal: true }), true)
  })
})
