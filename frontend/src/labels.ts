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
  // document, run and review states
  VALIDATED: '검증 통과', VALIDATION_FAILED: '검증 실패', INCOMPLETE: '미완료', BASIS_CHANGED: '기반 변경 · 확인 필요',
  REVALIDATION_REQUIRED: '재검증 필요', INFO_REQUESTED: '추가 정보 요청됨', PASS: '통과', WARN: '주의', BLOCK: '차단',
  DONE: '완료', PENDING: '대기', ASSIGNED: '배정됨', EXCEPTION: '예외', REOPENED: '재오픈', IN_PROGRESS: '진행 중',
  APPROVE: '승인', REJECT: '반려', REQUEST_INFO: '추가 정보 요청', REQUEST_CHANGES: '수정 요청', REQUEST_REVIEW: '검토 요청',
  NO_SCOPE_IMPACT: '범위 영향 없음', REVISE: '재작성 필요', ADDED: '추가', REMOVED: '삭제', CHANGED: '변경',
  JSON_ERROR: '응답 형식 오류', LIMIT_EXCEEDED: '한도 초과', LIVE: '실제 호출', TEST_DOUBLE: '시험용 응답',
  // actions and effect checks
  REQUESTED: '요청됨', PLAN_APPROVED: '계획 승인', EXECUTED: '실행됨', INDEPENDENTLY_VERIFIED: '독립 확인',
  RELEASED: '해제', NOT_EFFECTIVE: '효과 없음', MEETS_CRITERIA: '기준 충족', FAILS_CRITERIA: '기준 미달', SIMULATED: '모의 기록',
  HOLD: '보류', SORT: '선별', STOP_SHIP: '출하 중지', QUARANTINE: '격리', CUSTOMER_NOTIFY_REQUEST: '고객 통보 요청', OTHER: '기타',
  PROCESS_CHANGE: '공정 변경', EQUIPMENT_CHANGE: '설비 변경', SUPPORTS: '지지', REFUTES: '반박', VERIFIED: '확인됨',
  // D0, D1, D4
  SPC_SIGNAL: 'SPC 신호', SIGNAL_ONLY: '신호만 있음', LEAD: '리더', QUALITY: '품질', PRODUCTION: '생산', PROCESS: '공정',
  SUPPLIER: '협력사', CUSTOMER: '고객', MAN: '사람', MACHINE: '설비', MATERIAL: '자재', METHOD: '방법', MEASUREMENT: '측정',
  ENVIRONMENT: '환경', OCCURRENCE: '발생 원인', NON_DETECTION: '유출 원인', SYSTEMIC: '시스템 원인', AI_OPINION: 'AI 의견',
  // inspection records
  FAIL: '불합격', FALSE_ALARM: '오검출', REPAIRED: '수리 완료', NO_REPAIR: '수리 안 함', SHIPPED: '출하됨', IN_WIP: '재공',
  VALID: '정상', SUSPECT: '의심', CONFLICTED: '충돌', SUPPORTED: '근거 있음', MISSING: '근거 없음', NEEDS_HUMAN: '사람 확인 필요',
  SPI_VOLUME_LOW: 'SPI 체적 낮음', SPI_VOLUME_HIGH: 'SPI 체적 높음', SPI_VOLUME_SCATTER: 'SPI 체적 산포', AOI_FAIL_CONFIRMED: 'AOI 불량 확인',
  AOI_FALSE_ALARM: 'AOI 오검출', AOI_PASS: 'AOI 합격', AOI_MISSING: 'AOI 기록 없음', SOLDER_BRIDGE: '솔더 브리지',
  // checks and actions in past cases
  STENCIL_APERTURE_INSPECTION: '스텐실 개구부 검사', STENCIL_CLEAN: '스텐실 세척', STENCIL_THICKNESS_CHECK: '스텐실 두께 확인',
  STENCIL_REPLACE: '스텐실 교체', STENCIL_REPLACE_AND_INTERVAL: '스텐실 교체 · 세척 주기 변경', STENCIL_RECHECK: '스텐실 재점검',
  SPI_CALIBRATION_LOG: 'SPI 교정 기록 확인', SPI_RECALIBRATION: 'SPI 재교정', AOI_LIBRARY_REVIEW: 'AOI 라이브러리 점검',
  AOI_THRESHOLD_TUNE: 'AOI 판정 기준 조정', AOI_RERUN: 'AOI 재검사', REFLOW_PROFILE_LOG: '리플로우 프로파일 기록 확인',
  REFLOW_PROFILE_CHANGE: '리플로우 프로파일 변경', PRINTER_PRESSURE_ADJUST: '인쇄기 압력 조정', SQUEEGEE_WEAR: '스퀴지 마모',
  SQUEEGEE_REPLACE: '스퀴지 교체', XRAY_CROSS_SECTION: 'X-ray · 단면 분석', PASTE_SUPPLIER_CHANGE: '페이스트 공급사 변경',
  OPERATOR_ADJUDICATION: '작업자 재판정', CLEANING_INTERVAL_EXCEEDED: '세척 주기 초과', VERIFIED_NO_RECURRENCE: '재발 없음 확인',
  // audit events
  ACTION_EXECUTED: '조치 실행', ACTION_INDEPENDENTLY_VERIFIED: '조치 독립 확인', ACTION_PLAN_APPROVED: '조치 계획 승인',
  BASIS_CHECKED: '기반 변경 확인', D3_ACTION_PROPOSED: 'D3 조치 제안', D4_CONFIRMED: 'D4 원인 확정', D4_EXPERIMENT: 'D4 실험 기록',
  D4_HYPOTHESIS: 'D4 가설 등록', D5_OPTION_PROPOSED: 'D5 조치안 제안', D6_EFFECTIVE: 'D6 효과 있음', D6_PLAN: 'D6 검증 계획',
  D7_DEPLOYED: 'D7 수평 전개', D7_REVISION_DRAFTED: 'D7 개정안 작성', D7_REVISION_RELEASED: 'D7 개정 발효', D8_ACKNOWLEDGED: 'D8 확인 서명',
  D8_CLOSED: 'D8 종결', D8_REOPENED: 'D8 재오픈', DRAFT_CREATED: '초안 작성', DRAFT_EDITED: '초안 수정', EXPERIENCE_INDEXED: '과거 사례 등록',
  EXPERIENCE_RETRIEVED: '과거 사례 검색', EXPERIENCE_REVIEW_PRIOR_RESPONSE: '과거 조치 검토', INVESTIGATION_RUN: 'AI 조사 실행',
  POST_WINDOW_DATA: '검증 기간 이후 데이터', PROCESS_CONTEXT: '공정 정보 기록', REVIEW_REQUESTED: '검토 요청', TEAM_ACCEPT: '팀 수락',
  TEAM_ASSIGN: '팀 배정', TRIAGED: 'D0 판정', EXPORTED: '내려받기', ARCHIVED: '보관', URGENT_ACTION_REQUESTED: '긴급 봉쇄 요청',
  // data sources and issues
  SYNTHETIC_AOI_INSPECTIONS: 'AOI 검사 기록', SYNTHETIC_BOARDS: '보드 목록', SYNTHETIC_COMPONENTS: '부품 목록', SYNTHETIC_EQUIPMENT_EVENTS: '설비 기록',
  SYNTHETIC_HUMAN_VERIFICATIONS: '작업자 확인 기록', SYNTHETIC_LOTS: 'LOT 목록', SYNTHETIC_PANELS: '패널 목록', SYNTHETIC_PINS: '핀 목록',
  SYNTHETIC_REPAIR_DISPOSITIONS: '수리 처리 기록', SYNTHETIC_SHIPMENTS: '출하 기록', SYNTHETIC_SPI_MEASUREMENTS: 'SPI 측정 기록',
  INSPECTION_DISAGREEMENT: 'AOI와 작업자 판정 불일치', MISSING_AOI: 'AOI 기록 없는 보드', DUPLICATE_INSPECTION: '중복 검사', LATE_ARRIVAL: '늦게 들어온 기록',
  PCB_SMT: 'PCB SMT', SPI_MEAN_VOLUME_MM3: 'SPI 평균 체적 (mm³)', PROCESS_SIGNAL: '공정 신호', DETERMINISTIC_TEMPLATE_NO_AI: '템플릿 작성',
  SUPPLIER_NONCONFORMITY: '협력사 부적합', AUDIT_FINDING: '감사 지적', CHAT_UPLOAD: '대화 첨부', MANUAL: '직접 입력',
  // roles
  AUTHOR: '작성자', REVIEWER: '검토자', QA_PRODUCTION: 'QA/생산', PROCESS_ENGINEER: '공정 엔지니어', AGENT_ADMIN: 'AI 운영',
}

export const say = (code: string | null | undefined): string => (code ? PLAIN[code] ?? code : '-')

// Codes inside a server sentence ("SPI_VOLUME_LOW + AOI_FAIL_CONFIRMED") read as words too
export const words = (text: string): string => text.replace(/\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/g, c => PLAIN[c] ?? c)

// Any server value as words for a person: lists joined, objects as "key: value", never raw JSON.
export function show(v: unknown): string {
  if (v === null || v === undefined || v === '') return '-'
  if (Array.isArray(v)) return v.map(show).join(', ')
  if (typeof v === 'object') return Object.entries(v as Record<string, unknown>).map(([k, x]) => `${say(k)}: ${show(x)}`).join(' · ')
  return typeof v === 'string' ? say(v) : String(v)
}
