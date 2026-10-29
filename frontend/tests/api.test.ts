import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, request } from '../src/api/client'

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
    await expect(request('bob', '/x', 'POST', {})).rejects.toEqual(new ApiError(409, '409: stale content hash'))
    vi.stubGlobal('fetch', reply(422, '{"detail":[{"loc":["body"],"msg":"bad"}]}'))
    const e = await request('bob', '/x', 'POST', {}).catch(x => x)
    expect(e).toBeInstanceOf(ApiError)
    expect(e.status).toBe(422)
    expect(e.message).toBe('422: [{"loc":["body"],"msg":"bad"}]')
  })
})
