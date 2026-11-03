// One plain-language name per server code, shared by every screen (2026-11-03 readability pass). The code itself
// stays available as a tooltip; screens show what it means.
export const PLAIN: Record<string, string> = {
  // Experience Memory
  KNOWN: '검증된 해결책 있음', ANALOGICAL: '비슷한 사례 (재검토 필요)', NO_RELEVANT_HISTORY: '관련 사례 없음',
  PRIOR_RESPONSE: '과거 조치', NEGATIVE_PRECEDENT: '실패·재발 사례 (주의)', UNKNOWN_EFFECT: '효과 미확인',
  VERIFIED_EFFECTIVE: '효과 검증됨', RECURRED: '재발함', NONE: '재발 없음', NOT_YET_OBSERVED: '재발 관찰 전',
  FAILED: '실패', INSUFFICIENT: '효과 부족', INCONCLUSIVE: '판단 보류',
  REVIEW_PRIOR_RESPONSE: '이 조치를 검토', INVESTIGATE_MORE: '더 조사', CONSIDER_ALTERNATIVE: '다른 방법 검토',
  // finding classes
  OBSERVED: '기록에서 확인', CALCULATED: '서버 계산', HYPOTHESIS: '가설', UNKNOWN: '알 수 없음', REPORTED: '고객이 말한 내용',
  PROPOSAL: 'AI 제안',
  // document states
  DRAFT: '초안', IN_REVIEW: '검토 중', APPROVED: '승인됨', REJECTED: '반려됨', SUPERSEDED: '대체됨',
  // sources
  USER_ENTERED: '사용자 직접 입력', SOURCE_CELL: '원본 파일 셀', CUSTOMER_REPORTED: '고객 보고', CHECKED: '검증된 내부 자료',
  SYNTHETIC: '합성 시험 자료', UNKNOWN_ORIGIN: '출처 미확인',
  // held calculations
  NEEDS_INPUT: '답변 필요', ANSWERED: '답변됨 · 재개 대기', RESUMED: '계산 완료',
  // requests and replies
  OPEN: '진행 중', SUBMITTED: '회신 도착', ACCEPTED: '수용', NEEDS_REVISION: '보완 요청',
  // D0 triage
  SPC_ALARM: 'SPC 경보', AOI_FAIL: 'AOI 불합격', CUSTOMER_COMPLAINT: '고객 불만', DEFECT_CONFIRMED: '불량 확인됨', NO_DEFECT: '불량 아님',
  NCR_ONLY: 'NCR만', FULL_8D: '8D 진행', EMERGENCY_FULL_8D: '긴급 8D', LOW: '낮음', MEDIUM: '보통', HIGH: '높음',
  CLOSED: '종결', CONFIRMED: '확정', EFFECTIVE: '효과 있음',
}

export const say = (code: string | null | undefined): string => (code ? PLAIN[code] ?? code : '-')

// Any server value as words for a person: lists joined, objects as "key: value", never raw JSON.
export function show(v: unknown): string {
  if (v === null || v === undefined || v === '') return '-'
  if (Array.isArray(v)) return v.map(show).join(', ')
  if (typeof v === 'object') return Object.entries(v as Record<string, unknown>).map(([k, x]) => `${say(k)}: ${show(x)}`).join(' · ')
  return typeof v === 'string' ? say(v) : String(v)
}
