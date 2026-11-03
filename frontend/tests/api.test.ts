import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, readable, request } from '../src/api/client'

const reply = (status: number, body: string) => vi.fn(async () => new Response(body, { status }))
afterEach(() => vi.unstubAllGlobals())

describe('request', () => {
  it('sends the demo user header and parses JSON; GET carries no idempotency key or body', async () => {
    const f = reply(200, '{"id":"bob"}'); vi.stubGlobal('fetch', f)
    expect(await request('bob', '/me')).toEqual({ id: 'bob' })
    const [path, init] = f.mock.calls[0] as unknown as [string, RequestInit]
    expect(path).toBe('/me')
    expect(init.headers).toEqual({ 'X-User': 'bob' })
    expect(init.body).toBeUndefined()
  })

  it('adds JSON content type and a fresh Idempotency-Key for mutations', async () => {
    const f = reply(201, '{}'); vi.stubGlobal('fetch', f)
    await request('alice', '/cases/C1/ncr', 'POST', { a: 1 }, true)
    await request('alice', '/cases/C1/ncr', 'POST', { a: 1 }, true)
    const h = f.mock.calls.map(c => (c as unknown as [string, RequestInit])[1].headers as Record<string, string>)
    expect(h[0]['Content-Type']).toBe('application/json')
    expect(h[0]['Idempotency-Key']).toMatch(/^[0-9a-f-]{36}$/)
    expect(h[0]['Idempotency-Key']).not.toBe(h[1]['Idempotency-Key'])
    expect((f.mock.calls[0] as unknown as [string, RequestInit])[1].body).toBe('{"a":1}')
  })

  it('returns non-JSON bodies as text', async () => {
    vi.stubGlobal('fetch', reply(200, '<html>doc</html>'))
    expect(await request('alice', '/x')).toBe('<html>doc</html>')
  })

  it('turns an error status into ApiError with the server detail', async () => {
    vi.stubGlobal('fetch', reply(409, '{"detail":"stale content hash"}'))
    await expect(request('bob', '/x', 'POST', {})).rejects.toEqual(new ApiError(409, '지금은 할 수 없습니다 · 나중에 다시 시도해 주세요'))  // a technical reason is not shown
    vi.stubGlobal('fetch', reply(422, '{"detail":[{"loc":["body"],"msg":"bad"}]}'))
    const e = await request('bob', '/x', 'POST', {}).catch(x => x)
    expect(e).toBeInstanceOf(ApiError)
    expect(e.status).toBe(422)
    expect(e.message).toBe('예상치 못한 오류입니다 · 나중에 다시 시도해 주세요')  // a message no rule knows: words, not the raw JSON
  })
})

describe('readable errors', () => {
  it('turns a validation error list into words with what to do next, never raw JSON', () => {
    expect(readable(422, { detail: [{ loc: ['body', 'reason'], msg: 'Field required' }, { loc: ['body', 'value'], msg: 'Input should be a valid number' }] }))
      .toBe('입력을 확인해 주세요 · 사유 값이 없습니다 · 값 숫자여야 합니다 · 표시된 칸을 고친 뒤 다시 시도해 주세요')
    expect(readable(422, { detail: [{ loc: ['header', 'Idempotency-Key'], msg: 'String should have at least 8 characters' }] }))
      .toBe('화면 오류입니다 · 새로고침 후 다시 시도해 주세요')  // a field the person never sees
    expect(readable(403, { detail: 'Not assigned to this case' })).toBe('권한이 없습니다 · 이 사건에 배정되지 않았습니다 · 사건 담당자에게 배정이나 권한을 요청하세요')
    expect(readable(502, {})).toBe('예상치 못한 오류입니다 · 나중에 다시 시도해 주세요')
    expect(readable(418, { detail: 'teapot' })).toBe('예상치 못한 오류입니다 · 나중에 다시 시도해 주세요')
    expect(readable(422, { detail: [{ loc: ['body', 'x'], msg: 'Something new' }] })).toBe('예상치 못한 오류입니다 · 나중에 다시 시도해 주세요')
    expect(readable(409, { detail: '완성본 출력 불가: 제출 필수 값이 없습니다' })).toBe('지금은 할 수 없습니다 · 완성본 출력 불가: 제출 필수 값이 없습니다 · 나중에 다시 시도해 주세요')
  })
})
