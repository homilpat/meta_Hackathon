import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ExportButtons } from '../src/components/ExportButtons'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('ExportButtons', () => {
  it('downloads the file under the server filename with the X-User header', async () => {
    const fetch = vi.fn(async () => new Response(new Blob(['%PDF']), { headers: {
      'Content-Disposition': 'attachment; filename="L_8D_report_abc.pdf"', 'X-Fields-Checked': '12', 'X-File-SHA256': 'f'.repeat(64) } }))
    vi.stubGlobal('fetch', fetch)
    URL.createObjectURL = vi.fn(() => 'blob:x'); URL.revokeObjectURL = vi.fn()
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    render(<ExportButtons user="bob" path="/cases/L/report/export" label="8D 보고서"/>)
    fireEvent.click(screen.getByText('8D 보고서 PDF'))
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('L_8D_report_abc.pdf'))
    expect(fetch).toHaveBeenCalledWith('/cases/L/report/export?format=pdf', { headers: { 'X-User': 'bob' } })
    expect(click).toHaveBeenCalled()
  })

  it('shows why the server refused the export', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'NCR v2 is DRAFT' }), { status: 409 })))
    render(<ExportButtons user="bob" path="/cases/L/documents/ncr/export?version=2" label="승인본"/>)
    fireEvent.click(screen.getByText('승인본 DOCX'))
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('409: NCR v2 is DRAFT'))
  })
})
