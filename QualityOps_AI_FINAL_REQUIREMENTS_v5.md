# QualityOps AI — 최종 통합 요구사항 명세서 v5

- **기준:** 2026-10-28 · Meta Global AI Developer Hackathon용 실무 지향 MVP
- **실제 저장소:** `homilpat/meta_Hackathon`, 확인 시 최신 커밋 `aafbba37e2d959d5688ef2e1e609ba78c0658ad2` (개발 에이전트가 시작할 때 HEAD 재확인)
- **승계:** v3의 근거 기반 보고서 설계 + v4의 D0~D8 현업 요구사항 + 구조 개선 5항목. 본 v5가 충돌 시 우선하며 보안·불변 감사·증거 연계 원칙은 축소하지 않는다.
- **문서의 지위:** 요구사항. 아래의 신규 기능은 구현됐다고 주장하지 않는다. 실제 배포·공장 적합성 인증이 아니다.

## 1. 제품 목적과 문제 정의

분산된 SPI/AOI/설비·LOT·검사 이력, SOP/FMEA/과거 8D를 **Quality Case**에 연결하고, 이상 감지→위험 평가→긴급 봉쇄→부서별 원인 조사→영구조치→효과 검증→예방 표준화→종결을 한 화면에서 관리한다. Meta 모델은 증거 조회와 초안을 지원하지만 **실행, 원인 확정, 출하 판정, 서명**을 자동으로 하지 않는다. 보고서와 DB/문서 원본의 양방향 일치성, 적용 버전, 승인 전제조건을 서버가 확인한다.

핵심 가설: 동일 인원이 더 많은 사건을 관리하고 반복 문서·자료 취합 시간을 줄일 수 있다. **인원·시간·불량률의 절감 효과는 측정 전까지 추정하지 않는다.**

### 1.1 구현 현황: 저장소 기반으로 확인

| 기능 | 상태(확인된 근거) | 설계에 대한 결론 |
|---|---|---|
| 합성 PCB SPI/AOI/사람 검토/정정, Evidence 및 Case | 기존 구현 (`README.md`, `app/db.py`) | 재사용. 실제 제조 연동으로 오인 금지 |
| SPC X̄-R/Western Electric 및 사건 자동 생성 | 기존 구현 (`README.md`) | 알람과 실제 불량 구분 필수 |
| D2 NCR, D3 격리 **계획**, D4 RCA **가설**, 순서상 승인 | 기존 구현 (`app/workflow.py`) | D0·D1·D5~D8 확대; 계획≠실행 |
| ClaimValidator: 인용 ID, 수치 재계산, 일부 인과 표현 | 기존 구현 (`app/report.py`) | 텍스트 사실 전체의 참·거짓 검증은 아님 |
| LightGBM/SHAP, 사례 검색/다음 점검 계획 | 기존 구현 (`README.md`) | 예측과 인과 증명은 분리 |
| 권한 분리, 버전·해시 승인, 감사, 변경 영향 | 기존 구현 (`SECURITY.md`, `app/workflow.py`) | 새 단계에서도 우회 금지 |
| Meta LIVE | 코드 경로 존재, 문서상 실제 성공 미검증 | 검증 성공 전 LIVE 성공 주장 금지 |
| D0/D1/D5~D8, Docs 편집, RAG/양식 계약, 현장 실행 증명 | 최종 설계의 추가 대상 | 단계별 테스트와 구현 필요 |

기존 `workflow.py`에는 `KINDS={ncr, containment, rca}`, `PREREQ={CONTAINMENT:NCR,RCA:CONTAINMENT}`와 `STEP`의 고정 맵이 있음. `report.py`는 근거 ID 존재, CALCULATED 숫자 재계산, 정규식 기반 단정 표현 차단을 수행하므로 **일치하는 인용 ID만으로 문장이 실제로 뒷받침됨을 보장하지 않는다.** `db.py`는 `QualityCase`, `SourceAsset/Event`, `Evidence`, `DocumentVersion/Claim`, `ApprovalEvent`, `WorkflowEvent`가 있고 이를 우선 확장한다.

## 2. 불변 원칙 / 변경하지 않을 것

1. 기존 FastAPI·SQLAlchemy/Alembic·React `/app`·테스트 구조 및 동작 중인 S0~S7 기능 보존. 동등 API/테이블을 별도로 중복 구축하지 않는다.
2. 제조 원본 데이터와 문서 편집은 분리. Docs에서 숫자 수정은 원본 수정이 아니라 **초안 변경**이다. 원본 정정은 권한 있는 별도 승인 이벤트.
3. `SIGNAL` ≠ 확인된 `DEFECT`, `D3_PLAN_APPROVED` ≠ `D3_EXECUTED`, `HYPOTHESIS` ≠ `CONFIRMED_CAUSE`, `D5_SELECTED` ≠ `D6_IMPLEMENTED`, `POST_METRIC_IMPROVED` ≠ `EFFECTIVE`.
4. 긴급 봉쇄는 D0 위험 판단 후 D1/D2 완결 이전에도 실행 가능. **안전 확보를 문서 순서 때문에 지연시키지 않는다.** 이후 사건에 연결하고 회고 검토한다.
5. AI·RAG·SHAP·NLI는 주장/추천/검색 기능. 실제 실행 확인·원인 확정·최종 효과·품질 승인 권한 없음.
6. 기존 승인본/감사 이벤트 삭제·덮어쓰기 금지. 변경은 신규 버전 및 연결/영향 분석으로 반영.
7. 외부 모델 호출은 합성/명시 승인 데이터만. 기존 fail-closed egress·비밀키 정책 회귀 금지.
8. 신규 feature는 CI 통과와 반례 테스트를 수반. *동작 확인*과 *계획*을 README/데모에 구분.

## 3. 실무 운영 아키텍처

```
[공정 어댑터] PCB SMT (현재 합성) / 추후 반도체·가공·배치
  │  시간·단위·품목·공정·LOT/제품식별·측정조건 정규화
  ▼
[Quality Event + Case + Evidence Registry]
  ├─ 증거 품질 상태 / 출처·개정·적용일 / 검증된 정정 이력
  ├─ SPC/ML (알람·위험 점수, 인과 증명이 아님)
  └─ Structured SQL / Document Retrieval (버전/권한 필터)
                    │
                    ▼
[Versioned Workflow Policy / D0~D8 State Engine]
  ├─ 위험 분류 / 긴급 선행 격리 / 인력 배정
  ├─ 계획 ↔ 실제 실행 ↔ 독립 확인
  ├─ 원인 가설 ↔ 실험 ↔ 검토 판정
  └─ 영구조치 ↔ 효과 판정 ↔ 예방 확산 ↔ 최종 종결
                    │
                    ▼
[AI Task Router]  결정론 계산·규칙은 서버 / 언어 작업은 Meta
  └─ Read-only tools, schema, citations, UNKNOWN/abstain
                    │
                    ▼
[Verification Engine]
  ├─ SQL 역대조 / Evidence reliability / 단위·시점·분모
  ├─ Claim ↔ Evidence 지원성 (의미 검증은 보조)
  ├─ Template Contract (RAG 후보, 결정론적 양식 검증)
  ├─ Cross-stage & change-impact rules
  └─ 승인 전 문서/증거/양식/규칙 버전 잠금
                    │
                    ▼
[Human Docs Workspace] draft/edit/diff/review/approve
                    │
                    ▼
[DOCX/PDF export + audit] 출력된 내용 ↔ 승인 snapshot 재검사
```

### 3.1 구조 개선 A — 정책 기반 Workflow Engine (최우선)

`PREREQ`의 단일 체인을 그대로 D8까지 연장하지 않는다. 공정·고객사·사건 위험에 따른 **버전 있는 WorkflowPolicy**를 저장하고 **작업의 시작 가능성**, **실행 권한**, **승인 조건**, **종결 조건**을 별도로 평가한다. 처음에는 DB/정적 JSON 정책 + 테스트 가능한 순수 함수로 구현한다. 거대한 BPMN 엔진 도입 금지.

권장 `WorkflowPolicy(policy_id, version, site, customer, process_type, severity, effective_from, effective_to, required_roles, draft_requirements, execution_permissions, approval_gates, closure_gates, hash, approved_by)`. 고객사 요구사항이 없으면 명시적 default policy 사용; 미확인 요구사항은 임의의 공식 준수로 표시하지 않는다.

### 3.2 구조 개선 B — Evidence Reliability (최우선)

증거 **존재**와 **신뢰 가능성/용도 적합성**을 분리한다. `VALID / SUSPECT / CONFLICTED / SUPERSEDED / UNVERIFIED` 상태를 `EvidenceQualityAssessment`로 별도 기록하고, 측정 출처·교정 상태·결측·단위·중복·원본 수정·시간 동기화·검사 조건 일치 여부를 판단한다. 불확실한 데이터는 D2 관측의 주석으로 쓸 수 있지만 D4 원인 확정/D6 효과 입증에 자동 사용하지 않는다. 품질 상태 변경은 근거와 감사를 남기고 관련 단계 재검증.

### 3.3 구조 개선 C — Hypothesis→Experiment→Decision (최우선)

D4는 Fishbone 그림 자체가 아니라 정규화된 `CauseHypothesis`, `WhyLink`, `Experiment`, `CausalDecision`을 핵심으로 한다. 발생/미검출/시스템 원인 구분, 4M/4M1E/6M 분류, 증거와 **반증**, 검증 계획, 실험 조건/재현성/판정기준, 검사·검토자. 원인은 복수 가능, 미검증은 `INCONCLUSIVE`. `SHAP`, 예측, 선례, NLI 합격만으로 `CONFIRMED` 불가.

### 3.4 구조 개선 D — Task-aware AI Router (권장)

`SQL/Python`이 숫자·단위·LOT·SPC·통계·승인 처리, RAG가 문서 후보 검색, `Muse Spark`가 요약·가설 질문·초안/재작성 **제안만** 처리. 캐시 기준은 사례·증거 snapshot·문서 정책·모델/프롬프트 버전. 외부 호출이 없거나 실패해도 수기 편집/서버 검증 경로 유지.

### 3.5 구조 개선 E — 공정 중립 Core + Adapter (확장 핵심)

기존 PCB 모델을 삭제하지 않고 `Case → ProcessContext / AffectedObject / Measurement / Inspection / Evidence / Action` 공통 스키마의 어댑터로 매핑. PCB 전용 `panel/board/pin/SPI/AOI`는 adapter에서 제공. 공정별 식별·통계 기준을 정책으로 분리하고, **새 공정 추가가 D0~D8 엔진을 수정하지 않도록** contract tests 추가. MVP에서는 제2공정의 최소 가상 fixture로 확장성만 증명하고 실제 적용 성공 주장 금지.

## 4. D0~D8 단계 계약

| 단계 | 산출물 | 완료 판단 / 반드시 차단할 오류 |
|---|---|---|
| **D0** 초기 심각도/범위/경로 | 신호 vs 불량, 고객·안전·출하 영향, `NCR_ONLY/FULL_8D/EMERGENCY` | SPC 알람을 불량 확정으로 오기 금지. 긴급 조치는 선행 허용. |
| **D1** 팀 | 팀장·품질·생산·공정/설비·필요시 공급사/고객 담당, 수락/기한 | 필수 담당자 미배정, 자기 승인 차단(정책별 예외 기록). |
| **D2** 문제 정의 | 5W2H, IS/IS NOT, LOT/품목/시간/분모/검출 | 실제 DB와 수치/시간/대상 불일치, 미확인 범위의 단정 차단. |
| **D3** 임시 봉쇄 | 대상 LOT·재고·출하, 계획/승인/실행/확인, 가상 실행 명시 | 계획만으로 완료, 미확인 출하정지·격리 완료 주장 차단. |
| **D4** 근본 원인 | 4M·5Why·Fishbone, 발생·미검출·시스템 원인, 실험/반증 | 추측·SHAP로 확정 차단; 검증 실험·권한 검토 필수. |
| **D5** 조치 선정 | 검증 원인별 대안 비교·위험·부작용·사전 적합성 | 원인과 무관하거나 미검증된 시정조치의 최종 선정 차단. |
| **D6** 실행과 효과 | 실행 이벤트, 사전 수용기준, 전/후 기간·표본·검사기준, 모니터링 | 실행 전 성공·표본 부족·제품믹스/검사조건 다른 비교의 확정 차단. 실패 시 D4/D5 재오픈. |
| **D7** 예방 | SOP/FMEA/Control Plan 개정·발효일·교육·유사라인 수평전개 | 문장에 '수정'만 적고 실제 승인 개정본/적용 기록 없는 경우 완료 차단. |
| **D8** 종결 | 단계별 완료 증거, 잔여 위험 승인, 고객 통보 요건, 팀 공헌·최종 서명 | 미완료 단계, 유효하지 않은 증거, 서명/양식/잔여 리스크 누락 시 종료 차단. |

긴급 D3 실행은 D0 뒤 D1 이전에도 가능하고, 정식 문서의 D3 승인과 분리한다. 부서별 담당자/검토자/실행자/독립 확인자 권한을 정책화한다.

## 5. 기능 요구사항 (FR) 및 우선순위

**P0 = 완결 데모 필수, P1 = 품질 차별화, P2 = 장기 확장.**

| ID | 등급 | 검증 가능한 요구사항 |
|---|---|---|
| FR-01 | P0 | SPC 신호와 확정 불량을 서로 다른 상태·이력으로 저장 |
| FR-02 | P0 | D0 위험 평가·8D 분기, 긴급 조치의 비순차 실행/감사 |
| FR-03 | P0 | D1 필수 역할 배정·수락·기한·예외 로그 |
| FR-04 | P0 | D2 5W2H/IS-IS NOT/검사 모수·영향 범위와 정확한 DB 필드 검증 |
| FR-05 | P0 | D3 격리 계획·승인·실제/합성 실행·독립 확인과 범위 추적 |
| FR-06 | P0 | D4 구조화 가설/4M·5Why/Fishbone 및 반증·실험·원인 판정 |
| FR-07 | P0 | D5 검증 원인별 조치 대안·선정·사전 위험 평가 |
| FR-08 | P0 | D6 조치 실행과 사전 정의 효과 계획·검증 결과 및 실패 분기 |
| FR-09 | P0 | D7 SOP/FMEA/Control Plan 유효 개정·적용·교육·전개 |
| FR-10 | P0 | D8 전 단계/증거/문서/승인/리스크 조건 원자적 확인 후 종결 |
| FR-11 | P0 | `WorkflowPolicy` 버전, 단계별 draft/execute/approve/close 조건 분리 |
| FR-12 | P0 | `EvidenceQualityAssessment` 상태/근거 및 확정 판정에 부적합 증거 차단 |
| FR-13 | P0 | 수치·LOT·날짜·단위·분모·주어·대상 등 모든 구조화 사실을 원본 역대조 |
| FR-14 | P0 | Claim-Evidence 연계·정정 및 원본 개정 시 선택적 재검증; 불명확하면 전체 재검증 |
| FR-15 | P0 | Docs에서 수기 초안 수정, 버전 충돌 409, 편집 후 검증 결과·오류 위치 노출 |
| FR-16 | P0 | AI 조회/작성 제안, 근거 부족 UNKNOWN 처리, 외부 유출 제한 |
| FR-17 | P0 | 승인본 불변, 사람 승인·실행 분리, 승인 시 문서/증거/정책/양식/검증 규칙 hash 일치 |
| FR-18 | P0 | 고객사·시점·공정별 `TemplateContract` 선택·필수 필드/양식/서명 규칙 검증 |
| FR-19 | P1 | 정형 SQL/비정형 메타데이터+BM25/필요 시 벡터 Hybrid RAG, ACL/개정 선필터 |
| FR-20 | P1 | 문장-증거 충돌 의미 감지는 보조; 거짓 경보/누락 측정 |
| FR-21 | P1 | Meta AI 수정안은 diff로 제안 후 사람 채택·재검증 |
| FR-22 | P1 | 최종 승인본 DOCX/PDF 출력과 필드·수치·양식 누락 검증 |
| FR-23 | P1 | 부서 할 일/기한/에스컬레이션, 멀티 케이스 관리 UI |
| FR-24 | P1 | 실측 작성시간·수정시간·LLM 호출·토큰·지연·비용 분리 추적 |
| FR-25 | P1 | `TaskRouter`가 결정론 계산에 LLM을 호출하지 않으며 장애 시 수기 경로 유지 |
| FR-26 | P1 | 공정 중립 데이터 계약 및 PCB 어댑터, 다른 공정 최소 contract fixture |
| FR-27 | P2 | 실제 MES/QMS/ERP·출하·설비 연동 (별도 보안·현장 승인 후) |
| FR-28 | P2 | SSO/MFA/TLS/KMS/WORM·다중사업장 분리·운영성 보장 |
| FR-29 | P2 | 풍부한 동시 편집 CRDT, 대규모 벡터 검색 및 다중 에이전트 |

## 6. 데이터 계약·상태·검증 구현 지침

### 6.1 기존 데이터 재사용

`QualityCase`, `SourceAsset`, `SourceEvent`, `Evidence`, `DataQualityIssue`, `User`, `Assignment`, `DocumentVersion`, `DocumentClaim`, `Review`, `ApprovalEvent`, `WorkflowEvent`, `ModelRun`, `ChangeImpact` 등 기존 스키마 유지. 변경 전 기존 Alembic 히스토리/테스트 조회. 필요 시 신규 테이블 추가, 과거 기록 파괴 금지.

### 6.2 새로운 논리 엔터티 (명칭은 구현 전에 충돌 확인)

- `ProcessContext(case_id, site, process_type, adapter_version, operation, equipment, recipe, config_hash)`
- `AffectedObject(case_id, object_type, object_id, parent_id, location, shipment_state, identity_source)`
- `WorkflowPolicy(id, version, applicability, effective_period, roles, gates, policy_hash)`
- `TriageAssessment(case_id, signal_kind, observed_defect, risk_flags, route, assessor, evidence_ids, time)`
- `TeamMembership(case_id, responsibility, user_id, accepted_at, due_at)`
- `EvidenceQualityAssessment(evidence_id, quality_state, reason, measurements, checked_by, version, timestamp)`
- `ActionExecution(action_id, action_type, target_snapshot, event_type, actor_id, occurred_at, verification_evidence, verifier_id, synthetic_flag)`
- `CauseHypothesis(id, case_id, cause_type, category, text, confidence_label, evidence_ids, counter_evidence_ids, status)`
- `WhyLink(parent_hypothesis, child_hypothesis, supporting_ids, falsification_criteria)`
- `Experiment(id, hypothesis_id, method, controlled_conditions, baseline, intervention, sampling, evidence_ids, reviewer, result)`
- `CausalDecision(hypothesis_id, decision, basis_experiment_ids, actor, time)`
- `CorrectiveAction(cause_id, candidate_options, risk_analysis, selection_decision, suitability_result)`
- `EffectivenessPlan(action_id, metric, baseline_window, post_window, min_sample, acceptance_rule, inspection_conditions, precommitted_at, reviewer)`
- `EffectivenessResult(plan_id, execution_id, observed_metrics, uncertainty, data_quality, decision, reviewer)`
- `PreventionDeployment(case_id, document_id, old_revision, new_revision, effective_at, affected_scopes, training_evidence, reviewer)`
- `TemplateContract(customer, site, process, effective_period, rules, contract_hash, authorized_by)`
- `ValidationRun(document_hash, evidence_hash, workflow_policy_hash, template_hash, rules_version, issues, validated_at)`
- `DocumentEdit(document_id, author, origin, old_hash, new_hash, reason, at)`

### 6.3 검증 결과

`PASS`(통과), `WARN`(검토 필요), `UNKNOWN`(증거 미확보), `BLOCK`(해당 행위 금지). *모든* WARN/UNKNOWN이 업무 전체를 막는 것은 아니다. **안전한 조사/긴급 조치 실행**은 가능하지만 원인 확정·효과 인증·종결 등 해당 위험 행위는 게이트별 차단한다.

### 6.4 검사 파이프라인

1. Pydantic/schema/역할·사건 접근 권한.
2. 구조화 원본 데이터의 정확 조회: object/LOT, 타임존, 단위, 분모, source revision, 검사 조건.
3. Evidence 존재 + 최신성 + 품질 상태/용도 적합성.
4. 구조화 claim 슬롯 별 DB 수치 재계산과 텍스트 표면값 불일치 감지. **정규식만으로 문장 전체 정확도 보장하지 않음.**
5. 원인/실행/효과/재발방지의 종류별 실증 근거와 반증 검토.
6. 문서 후보 RAG 조회 뒤 `TemplateContract` 규칙 검사, 적용일/개정/고객사 일치.
7. D0~D8 cross-stage workflow policy 게이트, 변경 영향/연쇄 재검증.
8. 승인 **직전** 문서·증거·정책·양식·규칙버전을 트랜잭션에서 재조회/해시 비교.
9. 출력 후 승인된 스냅샷과 DOCX/PDF 필드·수치·필수 표·서명란 일치성 검사.
10. 의미론 NLI/LLM 검토는 의심점 제시 **보조 신호**이고 최종 근거로 간주하지 않음.

## 7. Docs 및 Agent 인터페이스

- React `/app` 기존 UI 확장. Evidence sidebar / issue 위치 표시 / D0~D8 업무 탭 / 담당자·리뷰·승인 상태 / 재검증 버튼 / 변경 이력.
- `DRAFT`만 수정 가능; 승인된 문서는 스냅샷 유지 후 새 버전 생성. 동시 수정은 ETag/If-Match로 409, 이전 사용자 수정 덮어쓰기 금지.
- 입력에는 `classification`, `source_selector`, `value`, `unit`, `text`, `evidence_ids`, `version` 등 구조화 claim, 계산 필드는 잠금.
- Meta는 읽기 전용 도구와 승인된 합성 데이터로 `DRAFT / PROPOSAL / UNKNOWN` 출력. AI 제안은 diff 확인 후 사용자 수락 시에만 반영.
- Meta LIVE 성공 여부는 스모크 테스트 로그로 확인하고 없으면 503 및 명시적 오프라인 상태. mock을 LIVE로 표기 금지.

## 8. API 지침

**기존 경로를 우선 사용**하며 중복 REST 자원 금지. 개발 시작 시 `app/main.py` 및 라우트 목록 추출 후 구체 경로를 결정한다.

- `POST /cases/{id}/triage` 위험/진입 결정, `POST /cases/{id}/urgent-actions` 긴급 대응.
- `POST /cases/{id}/team` D1 책임·수락.
- `POST /cases/{id}/hypotheses` / `/experiments` / `/causal-decisions` D4.
- `POST /cases/{id}/actions` / `/effectiveness` D3/D5/D6.
- `POST /cases/{id}/prevention` / `/closure` D7/D8.
- `PATCH /cases/{id}/documents/{kind}/draft` / `POST .../validate` / `POST .../approve`.
- `GET /cases/{id}/documents/{kind}/export?format=docx|pdf`.

모든 상태 변경은 인가·idempotency·증거 snapshot·감사 기록. 기존 `ncr`/`containment`/`rca`와 의미 중복 시 **기존 API 확장**.

## 9. 수용 테스트 — 반드시 재현할 반례

1. SPC 신호만 발생했는데 결함 확정 처리 시도 → 차단.
2. 긴급 위험 신호인데 D1 팀 구성 미완료라 임시 격리를 못 함 → **조치 가능하도록** 통과.
3. D3 계획만 있는 상태에서 실제 실행 완료 승인 → 차단.
4. 실제 LOT A 증거 ID를 붙이고 문서에는 LOT B 주장 → 차단.
5. DB 3.2%를 Docs에서 2.1%로 수정 후 승인 → 차단.
6. 증거가 `SUSPECT/SUPERSEDED`인데 D4 원인 확정 → 차단.
7. 5Why 연결이 근거 없음/SHAP 상위 변수만 제시하고 원인 확정 → 차단.
8. 복수 원인이 함께 존재해도 단일 원인만 강요하지 않을 것.
9. D5 미검증 원인의 영구조치 최종 선정 → 차단.
10. D6 미실행, 표본 부족, 검사 기준 변화, 미리 정하지 않은 통과기준 → 효과 승인 차단.
11. D6 효과 실패 → D4/D5 재검토 및 실패 로그 보존.
12. D7 문서 내용에 FMEA 개정 완료라 적었지만 유효한 새 승인본 없음 → 차단.
13. D8 미결 조치·승인 없음·증거 변경됨 → 종료 차단.
14. 오래된 고객사 양식/다른 설비 SOP/접근 불가 문서 → 선택·인용 차단.
15. 동시 편집 2개 요청/검토 중 버전 변경 → 409 및 손실 업데이트 없음.
16. 승인된 문서를 AI가 바로 변경·원본 DB 수정·외부 전송 → 차단.
17. Meta 키 미설정/호출 실패 → 수동 사용 가능, LIVE 성공이라고 표시하지 않음.
18. 기존 S0~S7 테스트·audit hash chain·증거 변경 영향·권한 분리 회귀 없이 통과.
19. 정책 변경 후 구 정책으로 작성된 승인 요청 → 정책 스냅샷/적용 규칙에 따라 재검증, 부적절한 승인 차단.
20. 다른 공정용 가상 fixture가 코어 수정 없이 식별·문서·승인 정책을 수행.

## 10. 평가 설계 및 사업적 효과 증명

실제 공장 결과가 아닌 **합성 fixture 실험**임을 명확히 한다. 독립 정답집을 만들고 다음을 계측한다.
- Claim 정확성 / unsupported claim 탐지 recall·precision / 정상 claim 오차단율.
- 수치/LOT/시간·문서 개정 불일치 발견율, 위험한 단계 전이 차단율.
- D6 효과 판단의 false positive / inconclusive 처리 정확도.
- RAG recall@k 및 유효 기간·권한 필터 위반율.
- 수기 기준선 대비 문서 초안·검토·수정 완료 시간(측정된 경우만), API/Meta 지연·비용.
- 모델 LIVE vs 테스트 더블, 데이터 합성 vs 실환경 실증, 기술 성과 vs 사업효과 **각각 분리**.

## 11. 우선순위·일정 원칙

**G0** 기존 코드·테스트·리스크 감사 → **G1** Meta LIVE 통과 또는 명확한 블로커 기록 → **G2** WorkflowPolicy/EvidenceQuality 공통기반 → **G3** D0/D1·긴급 조치 → **G4** D2/D3 강화 → **G5** D4 실험·판정 → **G6** D5/D6 → **G7** D7/D8 → **G8** Claims 역검증/문서·양식 검색 → **G9** Docs 편집/승인 불변 → **G10** DOCX/PDF·통합 데모·평가.

**시간 제약 우선:** 1건의 합성 사건 D0~D8 정상 시나리오와 1건의 실패·재조사 시나리오, Docs에서 수치·원인 오류 수정 후 차단·재검증. 벡터 DB, 세밀한 Fishbone 그래픽, CRDT, 다공정 실데이터 연결은 **추가 기능**이며 필수 경로보다 앞세우지 않는다.

## 12. 완료 정의(DoD)

- [ ] 현재 HEAD의 변경점/GAP 문서화, 기존 기능 삭제 없음.
- [ ] D0 긴급 조치(팀 구성 전)와 D1~D8 정상 사건 완결 E2E.
- [ ] 핵심 오류(D2 수치/LOT, D3 미실행, D4 무증거 원인, D6 무효 효과, D7 가짜 개정, D8 조기 종료)를 서버가 차단.
- [ ] 4M·5Why·Fishbone 입력은 **가설과 검증**까지 추적; 원인과 SHAP/추천 혼동 없음.
- [ ] Evidence 신뢰도/수정 반영, 정책별 선후관계, 고객사 양식 버전 검증.
- [ ] 인간 Docs 편집·AI 제안/수락 분리, 승인 스냅샷 불변, 변경 영향 반영.
- [ ] 실제로 확인한 명령/출력에 기반한 pytest·Ruff·migration·frontend build·HTTP/UI 검증.
- [ ] LIVE Meta 테스트는 성공 여부 사실대로 기록하고 비밀키 유출하지 않음.
- [ ] 문서 출력과 화면의 필수 수치·서명·근거 일치 확인.
- [ ] README/SECURITY/HACKATHON_WORK_LOG 최신화, synthetic/POC 한계 공개.

### 참고 원칙
8D는 다부서 문제 해결 체계이며, D5는 영구조치의 **선정·적합성 검증**, D6는 **실행·효과 확인**, D8은 팀 결과 승인·종료와 공헌 인정까지 포함한다. 고객사 요구사항이 있으면 그것의 유효 버전을 정책/TemplateContract에 명시한다.
