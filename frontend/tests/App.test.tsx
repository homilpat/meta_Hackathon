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

const menu = () => within(screen.getByRole('navigation', { name: '주 메뉴' }))
const nav = (label: string) => fireEvent.click(menu().getByRole('button', { name: new RegExp(`^${label}`) }))
const tools = () => fireEvent.click(screen.getByRole('button', { name: /전문 도구/ }))

describe('App shell', () => {
  it('opens on the Agent screen with honest offline status and the manual fallback when the agent API is absent', async () => {
    render(<App/>)
    expect(await screen.findByRole('heading', { name: '품질 조사 워크스페이스' })).toBeTruthy()
    await waitFor(() => expect(screen.getAllByText('C1').length).toBeGreaterThan(0))
    expect(screen.getByText('AI 연결 안 됨')).toBeTruthy()
    expect(screen.getByText('AI 오프라인 · 서버 규칙 플래너')).toBeTruthy()
    expect(await screen.findByText('Agent 서비스에 연결할 수 없습니다')).toBeTruthy()
    expect(screen.queryByText(/LIVE 검증됨/)).toBeNull()
    expect(calls.some(c => c.path === '/agent/runs?case_id=C1' && c.user === 'alice')).toBe(true)
    expect(calls.some(c => c.path === '/me' && c.user === 'alice')).toBe(true)
    // the fallback leads to the manual work queue
    fireEvent.click(within(screen.getByText('Agent 서비스에 연결할 수 없습니다').closest('section')!).getByRole('button', { name: '내 할 일' }))
    expect(await screen.findByRole('heading', { name: '내 할 일' })).toBeTruthy()
  })

  it('keeps the dashboard with the synthetic notice one click away', async () => {
    render(<App/>)
    await waitFor(() => expect(screen.getAllByText('C1').length).toBeGreaterThan(0))
    nav('사건 · 개요')
    expect(await screen.findByRole('heading', { name: '품질 운영 현황' })).toBeTruthy()
    expect(screen.getByText('시험용 데이터')).toBeTruthy()
  })

  it('every existing screen stays reachable under the specialist tools group', async () => {
    render(<App/>)
    await screen.findByRole('heading', { name: '품질 조사 워크스페이스' })
    expect(screen.queryByRole('button', { name: '감사 · 보안' })).toBeNull()
    tools()
    expect(screen.getByRole('button', { name: /전문 도구/ }).getAttribute('aria-expanded')).toBe('true')
    for (const label of ['D0~D8 진행', 'SPC 라인 모니터링', '제조 데이터 · 증거', '품질 예측 · XAI', 'AI 품질 조사', '과거 품질 사례', '문서 · 결재', '변경 영향 분석', '감사 · 보안'])
      expect(menu().getByRole('button', { name: new RegExp(`^${label}`) })).toBeTruthy()
  })

  it('switching the demo user reloads as that user and hides author-only actions', async () => {
    render(<App/>)
    await waitFor(() => expect(screen.getAllByText('C1').length).toBeGreaterThan(0))
    nav('사건 · 개요')
    expect(await screen.findByRole('button', { name: /시험 사건 \(SMT 라인\)/ })).toBeTruthy()
    const userSelect = screen.getByDisplayValue('작성자 Alice')
    await act(async () => { fireEvent.change(userSelect, { target: { value: 'bob' } }) })
    await waitFor(() => expect(calls.some(c => c.path === '/me' && c.user === 'bob')).toBe(true))
    await waitFor(() => expect(screen.queryByRole('button', { name: /시험 사건 \(SMT 라인\)/ })).toBeNull())
  })

  it('shows the server error text when a mutation is refused', async () => {
    // The click handler lets the rejection escape (unchanged app behaviour); capture exactly that one here.
    const vitestHandlers = process.listeners('unhandledRejection')
    const escaped: unknown[] = []
    process.removeAllListeners('unhandledRejection')
    process.on('unhandledRejection', e => escaped.push(e))
    try {
      render(<App/>)
      await waitFor(() => expect(screen.getAllByText('C1').length).toBeGreaterThan(0))
      nav('사건 · 개요')
      const button = await screen.findByRole('button', { name: '시험 사건 (소형)' })
      failPost = { status: 409, detail: 'case already exists' }
      await act(async () => { fireEvent.click(button) })
      expect(await screen.findByText('지금은 할 수 없습니다 · 나중에 다시 시도해 주세요')).toBeTruthy()
      expect(calls.find(c => c.method === 'POST')?.path).toBe('/cases')
      await waitFor(() => expect(escaped.map(String)).toEqual(['Error: 409']))
    } finally {
      process.removeAllListeners('unhandledRejection')
      vitestHandlers.forEach(h => process.on('unhandledRejection', h))
    }
  })

  it('navigates to the audit screen and shows the verified hash chain', async () => {
    render(<App/>)
    await waitFor(() => expect(screen.getAllByText('C1').length).toBeGreaterThan(0))
    tools()
    nav('감사 · 보안')
    expect(await screen.findByRole('heading', { name: '감사 기록' })).toBeTruthy()
    expect(await screen.findByText('기록이 바뀌지 않았습니다')).toBeTruthy()
  })

  it('queue lists open work and "열기" opens the document screen for that case', async () => {
    render(<App/>)
    await waitFor(() => expect(screen.getAllByText('C1').length).toBeGreaterThan(0))
    nav('내 할 일')
    expect(await screen.findByRole('heading', { name: '내 할 일' })).toBeTruthy()
    const row = (await screen.findByText('review NCR v2')).closest('tr')!
    expect(within(row).getByText('결재 검토')).toBeTruthy()
    expect(calls.some(c => c.path === '/queue?scope=mine')).toBe(true)
    fireEvent.click(within(row).getByRole('button', { name: '열기' }))
    expect(await screen.findByRole('heading', { name: '문서 및 결재' })).toBeTruthy()
  })

  it('department and approval menus read the same server queue', async () => {
    render(<App/>)
    await waitFor(() => expect(screen.getAllByText('C1').length).toBeGreaterThan(0))
    nav('부서 할 일')
    expect(await screen.findByRole('heading', { name: '부서 할 일' })).toBeTruthy()
    nav('승인 대기')
    expect(await screen.findByRole('heading', { name: '승인 대기' })).toBeTruthy()
    expect(within((await screen.findByText('review NCR v2')).closest('tr')!).getByText('결재 검토')).toBeTruthy()
    expect(calls.filter(c => c.path === '/queue?scope=department').length).toBeGreaterThan(0)
  })
})
