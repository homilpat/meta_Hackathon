import type { Tone } from './types'

export const USERS = [
  ['alice', '작성자 Alice', 'AUTHOR'], ['dave', '작성자 Dave', 'AUTHOR'], ['bob', 'NCR 검토자 Bob', 'REVIEWER'],
  ['carol', 'NCR 검토자 Carol', 'REVIEWER'], ['erin', 'QA/생산 Erin', 'QA_PRODUCTION'], ['frank', '공정 엔지니어 Frank', 'PROCESS_ENGINEER'],
] as const
export const KINDS = [['ncr', 'NCR', 'D2 부적합 보고서', 'bob'], ['containment', 'CONTAINMENT', 'D3 임시조치 계획', 'erin'], ['rca', 'RCA', 'D4 원인 가설', 'frank']] as const
export const APPROVER_ROLE: Record<string, string> = { NCR: 'REVIEWER', CONTAINMENT: 'QA_PRODUCTION', RCA: 'PROCESS_ENGINEER' }

export const CLASS_TONE: Record<string, Tone> = { OBSERVED: 'green', CALCULATED: 'blue', HYPOTHESIS: 'violet', UNKNOWN: 'slate', PROPOSAL: 'teal' }
export const STATUS_TONE: Record<string, Tone> = {
  DRAFT: 'slate', IN_REVIEW: 'amber', APPROVED: 'green', REJECTED: 'red', INFO_REQUESTED: 'amber', SUPERSEDED: 'slate',
  REVALIDATION_REQUIRED: 'red', BASIS_CHANGED: 'amber', VALIDATED: 'green', VALIDATION_FAILED: 'red', FAILED: 'red', JSON_ERROR: 'red', LIMIT_EXCEEDED: 'amber',
}
