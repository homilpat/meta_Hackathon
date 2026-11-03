import type { J } from '../types'

export const uid = () => crypto.randomUUID()

/** A non-2xx answer; `message` is the text shown in the error bar ("지금은 할 수 없습니다 · ..."). */
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
  if (!r.ok) throw new ApiError(r.status, readable(r.status, j))
  return j
}

// What the error bar says (2026-11-03): fixed rules, never the model and never raw JSON. Errors happen most when
// the model is down, must read the same every time, and may hold case data that has no reason to leave.
const HEAD: Record<number, string> = { 401: '로그인이 필요합니다', 403: '권한이 없습니다', 404: '찾을 수 없습니다', 409: '지금은 할 수 없습니다', 413: '파일이 너무 큽니다', 422: '입력을 확인해 주세요', 429: '요청이 너무 많습니다' }
const NEXT: Record<number, string> = { 401: '사용자를 다시 선택해 주세요', 403: '사건 담당자에게 배정이나 권한을 요청하세요', 404: '새로고침 후 다시 찾아 주세요',
  409: '나중에 다시 시도해 주세요', 422: '표시된 칸을 고친 뒤 다시 시도해 주세요', 429: '잠시 후 다시 시도해 주세요' }
const FIELD: Record<string, string> = { reason: '사유', value: '값', unit: '단위', cell: '셀 위치', sheet: '시트', file_id: '파일', lot: 'LOT',
  period: '기간', mapping: '열 연결', name: '이름', customer: '고객사', comment: '의견', decision: '결정', q: '검색어', goal: '목표', content_base64: '파일 내용' }
const INTERNAL = new Set(['Idempotency-Key', 'X-User', 'token', 'base_version', 'file_sha256', 'content_sha256'])  // the screen's job, not the person's
const MSG: [RegExp, string][] = [[/^Field required$/, '값이 없습니다'], [/String should have at least (\d+) characters?/, '$1자 이상 입력해 주세요'],
  [/String should have at most (\d+) characters?/, '$1자 이하로 입력해 주세요'], [/valid integer/, '정수여야 합니다'], [/valid number/, '숫자여야 합니다'],
  [/should match pattern/, '형식이 맞지 않습니다'], [/^Input should be /, '허용된 값이 아닙니다: '], [/greater than or equal to (\S+)/, '$1 이상이어야 합니다'],
  [/less than or equal to (\S+)/, '$1 이하여야 합니다']]
const KNOWN: [RegExp, string][] = [[/^Not assigned to this case$/, '이 사건에 배정되지 않았습니다'], [/^Case not found$/, '사건이 없습니다'],
  [/^Unknown or missing X-User$/, '사용자가 선택되지 않았습니다'], [/^(\w+) role required$/, '$1 역할만 할 수 있습니다'], [/^Case already exists$/, '이미 있는 사건입니다'],
  [/^File not found$/, '파일이 없습니다'], [/^Document version not found$/, '문서 버전이 없습니다'], [/^Request not found$/, '요청이 없습니다'],
  [/^A newer version exists; this one is stale$/, '더 새 버전이 있습니다'], [/^Only the latest DRAFT version can be sent for review$/, '최신 초안만 검토 요청할 수 있습니다'],
  [/^No draft yet: analyze the files first$/, '아직 초안이 없습니다: 먼저 문서를 분석하세요']]
const UNEXPECTED = '예상치 못한 오류입니다 · 나중에 다시 시도해 주세요'  // anything the rules above do not know (user 2026-11-03)

export function readable(status: number, j: J): string {
  if (!HEAD[status]) return UNEXPECTED  // a server error or a status this screen does not know
  const head = HEAD[status]
  const next = NEXT[status] ?? ''
  const d = j?.detail ?? j
  const tail = next ? ` · ${next}` : ''
  const known = typeof d === 'string' ? KNOWN.find(([rx]) => rx.test(d)) : undefined
  // a reason written for people (Korean, from the server or the table above) says what to do; an English or
  // technical one does not, so the person sees only the head and what to do next (user 2026-11-03)
  const reason = typeof d === 'string' ? (known ? d.replace(known[0], known[1]) : d) : ''
  if (reason && /[가-힣]/.test(reason)) return `${head} · ${reason}${tail}`
  if (typeof d === 'string') return `${head}${tail}`
  if (Array.isArray(d)) {
    const parts = d.map((e: J) => (e.loc ?? []).filter((x: unknown) => !['body', 'query', 'path', 'header'].includes(String(x))).map(String))
    if (parts.some((loc: string[]) => loc.some(x => INTERNAL.has(x)))) return '화면 오류입니다 · 새로고침 후 다시 시도해 주세요'
    const items = d.map((e: J, n: number) => {
      const field = parts[n].map((x: string) => FIELD[x] ?? x).join(' ')
      const raw = String(e.msg ?? ''), rule = MSG.find(([rx]) => rx.test(raw))  // the first rule that fits, only
      if (!rule) return null  // a validation message no rule knows
      const msg = rule[1].replace('$1', raw.match(rule[0])?.[1] ?? '') + (rule[1].endsWith(': ') ? raw.replace(rule[0], '') : '')
      return field ? `${field} ${msg}` : msg
    })
    return items.includes(null) ? UNEXPECTED : `${head} · ${items.join(' · ')}${tail}`
  }
  return `${head}${tail}`
}
