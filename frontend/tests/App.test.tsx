import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App'

// A small fake of the QualityOps API: enough routes for the shell, dashboard, queue and audit screens.
// Anything else answers 404, which screens must survive (they fall back to their empty state).
const ROLES: Record<string, string> = { alice: 'AUTHOR', bob: 'REVIEWER', erin: 'QA_PRODUCTION', frank: 'PROCESS_ENGINEER' }
type Call = { path: string; method: string; user: string; body?: string }
let calls: Call[]
let failPost: { status: number; detail: string } | null

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status })

function fakeApi(path: string, init: RequestInit = {}): Response {
  const method = init.method ?? 'GET'
  const user = (init.headers as Record<string, string> | undefined)?.['X-User'] ?? ''
  calls.push({ path, method, user, body: init.body as string | undefined })
  if (method !== 'GET') return failPost ? json(failPost.status, { detail: failPost.detail }) : json(201, {})
  if (path === '/provider') return json(200, { model: 'muse-spark-1.3', configured: false, live_status: 'BLOCKED_NO_CREDENTIALS' })
  if (path === '/me') return json(200, { id: user, role: ROLES[user] })
  if (path === '/cases') return json(200, [{ case_id: 'C1', domain: 'PCB_SMT', data_origin: 'SYNTHETIC' }])
  if (path === '/audit/verify') return json(200, { ok: true, links: 12, head_sha256: 'ab'.repeat(32), breaks: [] })
  if (path.startsWith('/queue')) return json(200, [{ case_id: 'C1', kind: 'ncr', doc_type: 'NCR', version: 2, status: 'IN_REVIEW', task: 'REVIEW', owner: 'bob', detail: 'review NCR v2' }])
  if (/^\/cases\/C1\/(evidence|data-issues|predictions|investigations|ncr|containment|rca|stages|timeline)$/.test(path)) return json(200, [])
  return json(404, { detail: 'not in fake' })
}

beforeEach(() => {
  calls = []; failPost = null
  vi.stubGlobal('fetch', vi.fn(async (path: string, init?: RequestInit) => fakeApi(path, init)))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const nav = (label: string) => fireEvent.click(screen.getByRole('button', { name: new RegExp(label) }))

describe('App shell', () => {
  it('renders the dashboard for the assigned case with honest offline Meta status', async () => {
    render(<App/>)
    expect(await screen.findByRole('heading', { name: '품질 운영 현황' })).toBeTruthy()
    await waitFor(() => expect(screen.getAllByText('C1').length).toBeGreaterThan(0))
    expect(screen.getByText('키 없음 · 호출 불가')).toBeTruthy()
    expect(screen.getByText(/SYNTHETIC, SELF_GENERATED/)).toBeTruthy()
    expect(calls.some(c => c.path === '/me' && c.user === 'alice')).toBe(true)
  })

  it('switching the demo user reloads as that user and hides author-only actions', async () => {
    render(<App/>)
    expect(await screen.findByRole('button', { name: /SMT 라인 사건/ })).toBeTruthy()
    const userSelect = screen.getByDisplayValue('작성자 Alice')
    await act(async () => { fireEvent.change(userSelect, { target: { value: 'bob' } }) })
    await waitFor(() => expect(calls.some(c => c.path === '/me' && c.user === 'bob')).toBe(true))
    await waitFor(() => expect(screen.queryByRole('button', { name: /SMT 라인 사건/ })).toBeNull())
  })

  it('shows the server error text when a mutation is refused', async () => {
    // The click handler lets the rejection escape (unchanged app behaviour); capture exactly that one here.
    const vitestHandlers = process.listeners('unhandledRejection')
    const escaped: unknown[] = []
    process.removeAllListeners('unhandledRejection')
    process.on('unhandledRejection', e => escaped.push(e))
    try {
      render(<App/>)
      const button = await screen.findByRole('button', { name: '소형 픽스처 사건' })
      failPost = { status: 409, detail: 'case already exists' }
      await act(async () => { fireEvent.click(button) })
      expect(await screen.findByText('409: case already exists')).toBeTruthy()
      expect(calls.find(c => c.method === 'POST')?.path).toBe('/cases')
      await waitFor(() => expect(escaped.map(String)).toEqual(['Error: 409']))
    } finally {
      process.removeAllListeners('unhandledRejection')
      vitestHandlers.forEach(h => process.on('unhandledRejection', h))
    }
  })

  it('navigates to the audit screen and shows the verified hash chain', async () => {
    render(<App/>)
    await screen.findByRole('heading', { name: '품질 운영 현황' })
    await waitFor(() => expect(screen.getAllByText('C1').length).toBeGreaterThan(0))
    nav('감사 · 보안')
    expect(await screen.findByRole('heading', { name: '감사 및 보안' })).toBeTruthy()
    expect(await screen.findByText('감사 해시 체인 무결')).toBeTruthy()
  })

  it('queue lists open work and "열기" opens the document screen for that case', async () => {
    render(<App/>)
    await waitFor(() => expect(screen.getAllByText('C1').length).toBeGreaterThan(0))
    nav('할 일')
    const row = (await screen.findByText('review NCR v2')).closest('tr')!
    expect(within(row).getByText('결재 검토')).toBeTruthy()
    fireEvent.click(within(row).getByRole('button', { name: '열기' }))
    expect(await screen.findByRole('heading', { name: '문서 및 결재' })).toBeTruthy()
  })
})
