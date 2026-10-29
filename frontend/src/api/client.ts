import type { J } from '../types'

export const uid = () => crypto.randomUUID()

/** A non-2xx answer; `message` is the text shown in the error bar ("409: ..."). */
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

// One request as demo user `user` (X-User header; no password). Mutations may carry an Idempotency-Key.
export async function request(user: string, path: string, method = 'GET', body?: unknown, idem = false): Promise<J> {
  const headers: Record<string, string> = { 'X-User': user }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (idem) headers['Idempotency-Key'] = uid()
  const r = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
  const text = await r.text(); let j: J; try { j = JSON.parse(text) } catch { j = text }
  if (!r.ok) throw new ApiError(r.status, `${r.status}: ${typeof j?.detail === 'string' ? j.detail : JSON.stringify(j?.detail ?? j)}`)
  return j
}
