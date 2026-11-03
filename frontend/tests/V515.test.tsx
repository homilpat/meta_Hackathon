import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CustomerForms } from '../src/features/documents/CustomerForms'
import { InputRequests } from '../src/features/requests/InputRequests'
import type { Ctx, J } from '../src/types'

afterEach(cleanup)
const ctxOf = (api: J): Ctx => ({ cid: 'C1', me: { id: 'alice', role: 'AUTHOR' }, api, refresh: vi.fn(), tick: 0, open: vi.fn(), focus: '' })

describe('§30 screens', () => {
  it('a held defect rate: the person answers 120, resumes, and sees 2.5 % with each source type', async () => {
    const req = { request_id: 4, status: 'ANSWERED', question: 'LOT 0007의 검사 수량(개)이 확인되지 않아 보류했습니다.', events: [], result: null }
    const api = vi.fn(async (path: string) => {
      if (path === '/cases/C1/input-requests') return [req]
      if (path.endsWith('/answers')) return { ...req, evidence_id: 'EV-IR4' }
      if (path.endsWith('/resume')) return { ...req, status: 'RESUMED' }
      return {}
    })
    render(<InputRequests ctx={ctxOf(api)}/>)
    expect(await screen.findByText(/LOT 0007의 검사 수량/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText('답변 값'), { target: { value: '120' } })
    fireEvent.click(screen.getByRole('button', { name: '답변' }))
    await waitFor(() => expect(api).toHaveBeenCalledWith('/input-requests/4/answers', 'POST', { kind: 'USER_ENTERED', value: 120, unit: 'EA' }, true))
    fireEvent.click(screen.getByRole('button', { name: '확인 후 계산 재개' }))
    await waitFor(() => expect(api).toHaveBeenCalledWith('/input-requests/4/resume', 'POST', {}, true))
  })

  it('a customer form: the final file stays disabled while a required value is missing', async () => {
    const tpl = { template_id: 1, customer: 'DEFAULT', name: '8D 회신서 A', version: 1, sha256: 'a'.repeat(64), data_origin: 'SYNTHETIC', route: 'CONFIRMED',
      slots: [{ id: 'T0.R5.C1', label: 'D4 Root Cause', kind: 'cell', context: '' }], fields: [{ id: 'd4.occurrence_cause', label: 'D4 발생 원인' }],
      mapping: { version: 1, mapping: { 'T0.R5.C1': 'd4.occurrence_cause' }, required: ['T0.R5.C1'] } }
    const api = vi.fn(async (path: string) => {
      if (path === '/customer-templates') return [tpl]
      if (path === '/customer-templates/1') return tpl
      if (path.endsWith('/preview')) return { case_data_version: 'v1', slots: [{ id: 'T0.R5.C1', status: 'MISSING', value: null, source: null }],
        final_blocked_by: [{ code: 'REQUIRED_MISSING', message: 'D4 Root Cause: 제출 필수 값이 없습니다' }] }
      return {}
    })
    render(<CustomerForms ctx={ctxOf(api)}/>)
    fireEvent.click(await screen.findByText(/8D 회신서 A v1/))
    expect(await screen.findByText(/완성본 차단: D4 Root Cause/)).toBeTruthy()
    expect((screen.getByRole('button', { name: '완성본 DOCX' }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByText('작성 필요')).toBeTruthy()
  })
})
