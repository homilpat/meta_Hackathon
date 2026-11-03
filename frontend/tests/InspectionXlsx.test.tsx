import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IntakeCard } from '../src/features/intake/Intake'
import type { Ctx, J } from '../src/types'

afterEach(cleanup)

const cell = (ref: string, raw: J) => ({ cell: ref, raw, type: 'n', format: 'General', formula: false })
const PREVIEW: J = {
  form: { name: 'ACME 수입검사', version: 2, builtin: false, candidates: ['inspection_results_v1', 'ACME 수입검사'] }, mapping_version: 'abc123', file_sha256: 'f'.repeat(64), sheet: '검사결과', header_row: 2,
  columns: { B: 'LOT', D: '검사 수량', E: '불량 수량' }, mapping: { lot: 'B', inspected_qty: 'D', defective_qty: 'E' }, issues: [],
  rows: [
    { row: 3, hidden: false, cells: { lot: cell('B3', 'L02'), inspected_qty: cell('D3', 480), defective_qty: cell('E3', 12) },
      values: { lot: 'L02', inspected_qty: 480, defective_qty: 12 }, issues: [] },
    { row: 4, hidden: false, cells: { lot: cell('B4', 'L02'), inspected_qty: cell('D4', 10), defective_qty: cell('E4', 12) },
      values: { lot: 'L02', inspected_qty: 10, defective_qty: 12 },
      issues: [{ level: 'BLOCK', code: 'DEFECTIVE_EXCEEDS_INSPECTED', cell: 'E4', message: '불량 수량이 검사 수량보다 많습니다' }] }],
}

describe('inspection xlsx card', () => {
  it('never includes a BLOCK row, needs a reason for every excluded row and sends what the person confirmed', async () => {
    const api = vi.fn(async (path: string, method = 'GET', body?: J) => {
      if (path === '/cases') return [{ case_id: 'L' }]
      if (path.startsWith('/intakes/3/files/9/inspection')) return PREVIEW
      if (path === '/intakes/3/draft') return {}
      if (path === '/cases/L/inspection-imports' && method === 'POST') return { import_id: 1, version: 1, denominator: { included: 1, excluded: 1 }, evidence_ids: ['EV-XL1-3'], body }
      if (path.includes('/reconciliation')) return { items: [{ field: 'lot', status: 'MATCH', customer: [{ value: 'L02', file: 'c.pdf', element_id: 'pdf:p1:l12' }], inspection: [{ sheet: '검사결과', row: 3 }] }] }
      return {}
    })
    const ctx: Ctx = { cid: '', me: { id: 'alice', role: 'AUTHOR' }, api, refresh: vi.fn(), tick: 0, open: vi.fn(), focus: '' }
    render(<IntakeCard ctx={ctx} intake={{ intake_id: 3, files: [{ file_id: 9, name: 'inspection.xlsx' }] }}/>)
    fireEvent.click(await screen.findByText(/검사 결과로 읽기/))
    const row4 = await screen.findByLabelText('4행 포함') as HTMLInputElement
    expect(row4.checked).toBe(false); expect(row4.disabled).toBe(true) // a BLOCK row cannot be included
    fireEvent.change(screen.getByLabelText('연결할 사건'), { target: { value: 'L' } })
    const go = screen.getByRole('button', { name: '확인한 열·행으로 사건에 연결' }) as HTMLButtonElement
    expect(go.disabled).toBe(true) // row 4 is excluded without a reason yet
    fireEvent.change(screen.getByLabelText('4행 제외 사유'), { target: { value: '불량>검사: 원본 확인 요청' } })
    fireEvent.click(go)
    await waitFor(() => expect(api).toHaveBeenCalledWith('/cases/L/inspection-imports', 'POST', {
      intake_id: 3, file_id: 9, file_sha256: 'f'.repeat(64), sheet: '검사결과', header_row: 2, mapping: PREVIEW.mapping,
      include_rows: [3], exclude: { 4: '불량>검사: 원본 확인 요청' }, form: 'ACME 수입검사' }, true))
    expect(await screen.findByText('MATCH')).toBeTruthy()
    expect((screen.getByLabelText('검사 양식') as HTMLSelectElement).value).toBe('ACME 수입검사') // the form the import was read with
  })
})
