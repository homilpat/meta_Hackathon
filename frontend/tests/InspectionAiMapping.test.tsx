import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IntakeCard } from '../src/features/intake/Intake'
import type { Ctx, J } from '../src/types'

afterEach(cleanup)

const cell = (ref: string, raw: J) => ({ cell: ref, raw, type: 'n', format: 'General', formula: false })
const ctxCols = [{ column: 'C', header: '수량 / 검사', cells: [{ cell: 'C4', raw: 480 }] }, { column: 'D', header: '수량 / 합격', cells: [{ cell: 'D4', raw: 470 }] },
  { column: 'E', header: '수량 / 불합격', cells: [{ cell: 'E4', raw: 10 }] }]
const view = (route: string, mapping: J, uncertain: J[] = []): J => ({
  form: { name: 'inspection_results_v1', version: 1, builtin: true }, file_sha256: 'f'.repeat(64), sheet: '검사성적', header_row: 3,
  columns: { A: 'LOT 번호', C: '수량 / 검사', D: '수량 / 합격', E: '수량 / 불합격' }, mapping, issues: [],
  rows: [{ row: 4, hidden: false, cells: { lot: cell('A4', '00412') }, values: { lot: '00412' }, issues: [] }],
  layout: { route, table: 'T1', reasons: route === 'NEEDS_AI' ? [{ code: 'REQUIRED_NOT_MAPPED', message: '필수 열을 모두 찾지 못했습니다' }] : [],
    tables: [{ id: 'T1', range: '검사성적!A2:F5', header_rows: [2, 3] }], uncertain } })

describe('inspection xlsx: AI mapping proposal', () => {
  it('asks only the uncertain field, shows its cells beside the other counts, and saves what the person confirmed', async () => {
    const wrong = { lot: 'A', inspected_qty: 'C', defective_qty: 'D' }
    const api = vi.fn(async (path: string, method = 'GET') => {
      if (path === '/cases') return [{ case_id: 'X' }]
      if (path === '/intakes/3/draft') return {}
      if (path.endsWith('/inspection/proposals') && method === 'POST') return { proposal_id: 7, status: 'OK', mode: 'LIVE', model: 'm', issues: [],
        proposal: { table: 'T1', mapping: wrong, reasons: { defective_qty: '불합격 아래' }, unresolved: [] },
        preview: view('NEEDS_AI', wrong, [{ field: 'defective_qty', column: 'D', header: '수량 / 합격', why: '합격(양품) 수량으로 보이는 열', cells: [], context: ctxCols }]) }
      if (path.endsWith('/inspection/mapping') && method === 'POST') return { name: '검사성적 확인 매핑 abc123' }
      if (path.includes('form=')) return view('REUSED', { ...wrong, defective_qty: 'E' })
      if (path.startsWith('/intakes/3/files/9/inspection')) return view('NEEDS_AI', { lot: 'A' })
      return {}
    })
    const ctx: Ctx = { cid: '', me: { id: 'alice', role: 'AUTHOR' }, api, refresh: vi.fn(), tick: 0, open: vi.fn(), focus: '' }
    render(<IntakeCard ctx={ctx} intake={{ intake_id: 3, files: [{ file_id: 9, name: 'inspection.xlsx' }] }}/>)
    fireEvent.click(await screen.findByText(/검사 결과로 읽기/))
    expect(await screen.findByText('AI 제안·검토 필요')).toBeTruthy()
    expect((screen.getByRole('button', { name: '확인한 열·행으로 사건에 연결' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'AI 열 연결 제안 받기' }))
    const box = await screen.findByLabelText('불량 수량 연결 확인')
    expect(screen.getByText('E4 = 10')).toBeTruthy() // the original cells, side by side with the other counts
    fireEvent.change(screen.getByLabelText('열 연결 확인 사유'), { target: { value: '원본 셀 대조' } })
    const keep = screen.getByRole('button', { name: /확인한 열 연결 저장/ }) as HTMLButtonElement
    expect(keep.disabled).toBe(true) // the uncertain field is not confirmed yet
    fireEvent.click(box)
    fireEvent.click(keep)
    await waitFor(() => expect(api).toHaveBeenCalledWith('/intakes/3/files/9/inspection/mapping', 'POST',
      { table: 'T1', mapping: wrong, confirmed: ['defective_qty'], proposal_id: 7, reason: '원본 셀 대조' }, true))
    expect(await screen.findByText('저장된 매핑 재사용')).toBeTruthy()
  })
})
