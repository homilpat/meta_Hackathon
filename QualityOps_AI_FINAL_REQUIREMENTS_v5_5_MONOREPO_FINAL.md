# QualityOps AI — 최종 요구사항 명세서 v5.5 MONOREPO FINAL
### 기존 기능 동결 + R0 구조 개편 + G9/G10 + Meta LIVE + 단계별 수용 게이트

- **기준:** 2026-10-29 · Meta Global AI Developer Hackathon 제출용 실무 지향 합성 데이터 MVP
- **실제 저장소:** `homilpat/meta_Hackathon` / `main`. **최근 확인 커밋:** `58d316a5f394d0f2ab0b83a4b0a0b42137c65b5b` (G8, 2026-10-29 KST). 이것은 기준 시점일 뿐이며 개발 착수 전에 원격 HEAD/작업 트리 재확인이 필수다.
- **승계·우선순위:** 기존 v5.5의 기능 요구사항(D0~D8, Experience Memory, 원본 대조 검증, 보안, 감사, 문서 출력)은 전부 유지한다. 이 문서는 **프로젝트 레이아웃, 작업 순서, 완료 조건**에서 이전 문서보다 우선한다. 기능 범위는 확장하지 않는다.
- **문서의 성격:** 목표 요구사항 + 마지막 확인 시점의 구현 근거. `BUILT`는 개발 로그의 구현 기록이며 실제 사용자 환경의 모든 기능이 검증되었다는 보증이 아니다. 실공장 검증 및 실제 ROI 측정 주장은 하지 않는다.

## 1. 제품 목적과 문제 정의

분산된 SPI/AOI/설비·LOT·검사 이력, SOP/FMEA/과거 8D를 **Quality Case**에 연결하고, 이상 감지→위험 평가→긴급 봉쇄→부서별 원인 조사→영구조치→효과 검증→예방 표준화→종결을 한 화면에서 관리한다. Meta 모델은 증거 조회와 초안을 지원하지만 **실행, 원인 확정, 출하 판정, 서명**을 자동으로 하지 않는다. 보고서와 DB/문서 원본의 양방향 일치성, 적용 버전, 승인 전제조건을 서버가 확인한다. **과거 동일·유사 사건의 검증된 조치를 현재 적용 조건과 함께 우선 제안한다. 관련 이력이 없으면 `NO_RELEVANT_HISTORY`를 표시하고 기존 증거 기반 D0~D8 조사로 진행한다. 미지 사건에 대한 교차 사례 조합 및 새로운 해결책 생성은 해커톤 이후 로드맵이다.**

핵심 가설: 동일 인원이 더 많은 사건을 관리하고 반복 문서·자료 취합 시간을 줄일 수 있다. **인원·시간·불량률의 절감 효과는 측정 전까지 추정하지 않는다.**

### 1.1 저장소 확인 현황 — G8 시점 스냅샷

**스냅샷 HEAD:** `58d316a` (2026-10-29 KST). 이 표는 작업 시작 시 반드시 새 HEAD에서 갱신한다.

| 단계 | 저장소상 현황 | 코드/계약 및 후속 검증 |
|---|---|---|
| S0~S7 / G0~G4 | BUILT(기존) | FastAPI, React, 합성 PCB/SPC, Evidence, ML/XAI, 조사·문서·감사; 변경·회귀 보호 |
| G1 Meta LIVE | `BLOCKED_NO_CREDENTIALS` | `docs/META_LIVE_LOG.md` 기준 테스트 더블만. 다른 기능 개발의 블로커로 취급하지 않음 |
| PREFLIGHT | BUILT | `workflow.py` 승인 흐름과 버전 정책의 단일 게이트 통합 기록, 회귀 보호 |
| G5 — D4 | BUILT | 실험·반증 기반 원인 판정, `app/causes.py` / `tests/test_v5_5_g5_d4.py` |
| G6 — D5/D6 | BUILT | 조치 선정, 실행과 효과 검증, 실패 시 재조사 / `app/effect.py` |
| G7 — D7/D8 | BUILT | 통제 문서 개정·교육·종결·재개방 / `app/registry.py`, `app/closure.py` |
| G8 — 검증·경험 재사용 | BUILT(오프라인) | `app/factcheck.py`, `validation.py`, `experience.py`, `taskrouter.py`, `investigator.py` (LIVE 별도) |
| **R0 — 모노레포 전환** | **NOT_STARTED(최근 확인 시점)** | 본 문서 §19, 구조/CI/경로 통합과 완전 회귀 테스트 |
| **G8 집중 보완** | **PENDING_AUDIT** | 새로운 종결 사례 상태·수치 오류 반례·권한 회귀만 검사; 재구현 금지 |
| **G9 — Human Docs** | **NOT_STARTED(최근 확인 시점)** | 사람 편집, diff, 제안, 재검증, 동시성, 승인 스냅샷 |
| **G10 — 최종 내보내기** | **NOT_STARTED(최근 확인 시점)** | 승인 스냅샷 DOCX/PDF, 단일 D0~D8 E2E, 산출물 일치 검증 |
| 최종 안정화 | NOT_STARTED | Meta LIVE 조건부 + 반복 데모 + CI / E2E / 문서 정리 |

**최근 저장소 작업 기록:** `pytest 226 passed`, Ruff 통과, 새 DB Alembic 통과, Vite 빌드 통과, G8 HTTP 시나리오 41/41. 이는 **이전 환경에서 기록된 결과**로, R0 이후에는 새로운 경로에서 재실행·입증해야 한다. GitHub Actions의 최신 실행 성공은 별도 확인 대상이다.

**구체적 잔여 위험:** `app/experience.py`의 종결 사례는 재발 미관찰 `NOT_YET_OBSERVED`로 검색되므로 즉시 `KNOWN` 성공 사례로 단정하지 않는다. `factcheck.py`는 정형·표면 표현 검증이 중심이므로 수치 복합 문장의 반례를 추가한다. Meta LIVE는 실모델·실도구 호출 미검증이다. 오래된 로컬 `qualityops.db`는 기존 기록상 스키마 불일치가 있어 **새 scratch DB만** 데모·마이그레이션 검증에 쓴다.

## 2. 불변 원칙 / 변경하지 않을 것

1. 기존 FastAPI·SQLAlchemy/Alembic·React `/app`·S0~S7 및 G0~G8 동작 보존. 디렉터리 위치는 R0 계약대로 변경하되 기능·인터페이스를 보존한다. 동등 API/테이블을 별도로 중복 구축하지 않는다.
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
| FR-22 | **P0 (G10)** | 최종 승인본 DOCX/PDF 출력과 필드·수치·양식 누락 검증 |
| FR-23 | P1 | 부서 할 일/기한/에스컬레이션, 멀티 케이스 관리 UI |
| FR-24 | P1 | 실측 작성시간·수정시간·LLM 호출·토큰·지연·비용 분리 추적 |
| FR-25 | P1 | `TaskRouter`가 결정론 계산에 LLM을 호출하지 않으며 장애 시 수기 경로 유지 |
| FR-26 | P1 | 공정 중립 데이터 계약 및 PCB 어댑터, 다른 공정 최소 contract fixture |
| FR-26A | **P0** | **동일·유사 사건 발생 시 과거 해결 이력 자동 탐색, 검증된 기존 조치의 우선 추천, 현재 적합성 확인과 담당자 선택 기록** |
| FR-26B | **P0** | **과거 조치가 FAILED/INCONCLUSIVE/재발이면 성공 해결책으로 표시하지 않고 차이·실패 이유·대체 조사 경로 제시** |
| FR-26C | P1 | Meta 하이브리드 조사: 백엔드가 단계·권한·검증 제어, Meta는 가설별 증거 부족 분석·읽기 전용 Tool Calling·다음 조사 제안 |
| FR-26D | P1 | 추천 근거(유사성 요인·과거 사건 ID·효과 증거·조건 차이), 담당자 승인/거절 이유 및 새로운 조치 결과 추적 |
| **FR-26E** | **P0** | **Experience Memory: 자연어 증상/원인/조치 설명과 D4~D8의 검증된 구조화 결과를 원본 버전·접근 권한과 함께 검색 가능한 사례로 축적. 모델 자체 재학습 없이 신규 경험 검색 반영** |
| **FR-26F** | **P0** | **KNOWN / ANALOGICAL 두 추천 모드. 동일 문제는 적용 조건을 확인한 검증 조치를 우선 추천하고, 유사 문제는 성공·실패와 조건 차이를 설명한 후 기존 조치의 검토·재검증을 제안. 관련 이력이 없으면 `NO_RELEVANT_HISTORY`로 표시하고 일반 D0~D8 조사로 진행. 미지 문제에 대한 교차 사례 조합·신규 해결책 생성은 해커톤 이후 로드맵** |
| **FR-26G** | **P0** | **실패·효과 불충분·재발 사례는 음성 근거(negative precedent)로 검색; 현 상황에서 왜 재사용을 경계하는지 표시하며 자동 원인 확정·조치 승인 금지** |
| **FR-26H** | P1 | 의미 검색과 구조화 필터의 결합·검색 근거 추적. 벡터 DB·파인튜닝·지식그래프 구축은 검색 품질/기간 여유가 입증되지 않으면 불필요 |
| FR-27 | P2 | 실제 MES/QMS/ERP·출하·설비 연동 (별도 보안·현장 승인 후) |
| FR-28 | P2 | SSO/MFA/TLS/KMS/WORM·다중사업장 분리·운영성 보장 |
| FR-29 | P2 | 풍부한 동시 편집 CRDT, 대규모 벡터 검색 및 다중 에이전트 |

## 6. 데이터 계약·상태·검증 구현 지침

### 6.1 기존 데이터 재사용

`QualityCase`, `SourceAsset`, `SourceEvent`, `Evidence`, `DataQualityIssue`, `User`, `Assignment`, `DocumentVersion`, `DocumentClaim`, `Review`, `ApprovalEvent`, `WorkflowEvent`, `ModelRun`, `ChangeImpact` 등 기존 스키마 유지. 변경 전 기존 Alembic 히스토리/테스트 조회. 필요 시 신규 테이블 추가, 과거 기록 파괴 금지.

### 6.2 논리 엔터티 목표 (기존 G2~G4 엔터티 중복 생성 금지)

아래는 **개념적 계약**이다. `WorkflowPolicy`, `EvidenceQuality`, `ProcessContext`, `AffectedObject`, `TriageAssessment`, `TeamMembership`, `Action`, `ActionEvent` 등 **이미 생성된 스키마·라우트·감사 이벤트를 우선 조사하여 재사용**한다. 똑같은 역할의 신규 테이블을 만들지 않는다. 기존 이력은 새 정책/서명 모델 도입 뒤에도 읽을 수 있어야 한다.

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
- `HistoricalCaseMatch(current_case_id, prior_case_id, matched_factors, differing_factors, retrieval_version, evidence_refs, assessed_at)`
- `PriorActionOutcome(prior_case_id, action_id, cause_id, effectiveness_status, verification_evidence, recurrence_status, applicability_conditions, evaluated_at)`
- `ReuseRecommendation(current_case_id, prior_case_id, prior_action_id, recommendation_type, rationale, similarity_factors, applicability_checks, warnings, source_version, created_at)`
- `RecommendationDecision(recommendation_id, reviewer_id, decision, reason, selected_action_id, decided_at)`
- `InvestigationTrace(case_id, hypothesis_refs, selected_tool, tool_arguments_redacted, evidence_refs, finding_status, proposal_reason, timestamp)`
- `ExperienceCase(prior_case_id, process_context, symptom_text, symptom_features, verified_cause_refs, action_outcome_refs, recurrence_state, applicability_conditions, scope_acl, source_revision, approved_snapshot_hash, indexed_at)` *(기존 historical record의 검색 projection일 수 있으며 독립 테이블 필수 아님)*
- `ExperienceRetrieval(query_case_id, query_snapshot_hash, mode, matched_case_ids, matched_factors, differing_factors, rejected_case_ids, retrieval_method_version, at)`
- `ExperienceProposal(case_id, mode, prior_case_refs, negative_precedent_refs, hypothesis, recommended_checks, proposed_action, unknowns, status, author, at)`
- `ExperienceFeedback(proposal_id, human_decision, reason, related_experiment_refs, actual_d6_outcome_ref, recurrence_status, reviewed_at)`

**위 개념 엔터티는 실제 DB 설계 전에 기존 historical retrieval·action·audit 구조와 중복 여부를 조사한다.** 기록이 없는 상태를 임의로 `SUCCESS`로 간주하지 않으며, 과거 해결책의 효과 검증 여부와 재발 여부를 별도 속성으로 저장한다.

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

## 6.5 과거 유사 사건 기반 의사결정 지원 (P0, G8)

**목표:** 재발/유사 품질 문제가 발생했을 때, 담당자가 과거 기록을 처음부터 다시 탐색할 필요 없이 **이미 효과를 검증한 조치를 먼저 검토**하도록 돕는다. 단순 유사 문서 검색이나 무조건 과거 방식 재적용이 아니다.

1. 현재 사건의 공정·불량 유형·설비·자재·조건·LOT 범위·이상 신호를 구조화하여 기존 historical retrieval에서 유사 사건을 찾는다. 완전 일치와 부분 유사성을 구분하고, 조회 근거·누락 정보·정렬 사유를 보여준다. **근거 없는 유사도 퍼센트 생성 금지.**
2. 검색된 사건의 D4 원인 판정, D5 조치, D6 효과 검증 및 사후 재발 기록을 확인한다. `VERIFIED_EFFECTIVE / FAILED / INCONCLUSIVE / UNKNOWN`을 구분하고 **성공 검증+현재 적용 조건 충족** 사례를 상단에 추천한다.
3. 현재와 과거의 **같은 점과 다른 점**을 화면에 표시한다. 조치 성공 이력은 추천 근거이지 **현재 근본 원인 확정이나 실행 허가가 아니다.** 현 설비·공정 조건, 안전성, 적용 가능성, 정책 등을 확인한다.
4. 담당자에게 **`과거 검증 조치 우선 검토` / `추가 원인 조사` / `다른 조치 검토`** 세 선택지를 제공한다. 선택·사유·담당자·시간·근거 스냅샷을 감사 기록에 남긴다. 선택이 곧 D5 승인·D6 실행 완료를 의미하지 않는다.
5. 조치가 실패했거나 효과 미확인·재발한 경우 **'과거 성공 조치'로 추천하지 않는다.** 실패·재발 이유를 제시하고 Meta가 현재 조건에 따른 추가 데이터 조회나 구별 실험을 제안하도록 한다. 동일 증상이라도 다른 원인 가능성을 유지한다.
6. 이후 D6 효과 결과와 D7 변경·D8 종결 이력은 검증된 형태로 축적하여 다음 사건 검색에 반영한다. 시스템이 실시간으로 모델 파라미터를 자체 학습하거나 검증되지 않은 사례를 정답으로 추가한다고 주장하지 않는다.
7. **한 사건 데모 수용 기준:** 과거 유사 사건 발견 → 검증된 기존 조치와 현재 조건 비교 표시 → 담당자 선택 → 현재 D4/D5 검증 절차 유지 → 선택 기록. **실패/재발 사례 한 건은 추천 제외/경고되는 반례 테스트로 검증.** 별도 상용 QMS 구현이나 A/B 시스템 개발은 필수가 아니다.

### 6.5.1 Experience Memory — 동일·유사 사례 축적 및 검증된 조치 재사용 (P0, G8)

**해결할 문제:** 기존 사건의 자연어 설명과 구조화된 원인·조치·효과·재발 기록을 누적하고 **현재 사건과 동일하거나 충분히 유사한 과거 경험을 재사용**한다. Meta 모델의 가중치 자동 학습·온라인 파인튜닝은 수행하지 않는다. 과거 사례가 없는 미지 문제에 대한 새로운 해결책 생성은 **해커톤 이후 확장 과제**다.

**축적 파이프라인:**

1. D2의 문제 설명(원문) + 공정/설비/LOT/측정 패턴(구조화 특징) + D4 검증된/미검증 원인 + D5 조치 + D6 효과 검증 + D7 적용 조건 + D8 결론·재발 상태를 **원본 Case/Revision/Evidence/Approval에 연결**한다.
2. 자유 텍스트에서 증상·조건·원인 후보·조치·결과를 추출할 수 있지만, AI 추출값은 **PROPOSED**로 저장하고 규칙·원본 또는 사람 검토 전에는 **VERIFIED**로 승격하지 않는다. 텍스트 단독으로 성공·인과성을 확정하지 않는다.
3. 기존 historical retrieval·관계형 DB·문서 검색을 우선 재사용한다. 공정/범위/접근권한/유효 개정의 **선필터 → 용어/BM25 및 가능한 경우 embedding 의미 검색 → 검증 상태·조치 효과·현재 적용 조건에 따른 재정렬** 순서. 검색 품질의 측정 근거가 없으면 별도 벡터 DB 설치 금지. 원문과 구조화 결과를 모두 보존한다.
4. 신규 사건 또는 검증된 수정이 생기면 관련 검색 projection/index를 갱신하고 **버전·갱신 시각·근거 snapshot**을 기록한다. **미검증/폐기/철회/권한 밖 이력**을 추천 근거로 사용하지 않고, 승인이 취소되거나 효과가 바뀐 사례의 캐시를 무효화한다.

**조사 모드:**

- `KNOWN` — 동일한 문제 유형과 검증된 인과/조건이 재현되는 경우. 성공 이력·적용 조건·필요한 현장 확인사항을 제공하고 **과거 검증 조치를 우선 검토**하도록 담당자에게 묻는다. 자동 적용하지 않는다.
- `ANALOGICAL` — 유사 증상·공정·설비·조건을 공유하는 경우. 과거의 성공과 실패 사례를 **동시에** 보여주고 차이점 및 기존 조치를 현재 환경에 적용하기 전 확인할 항목을 제안한다. **과거 효과의 현재 일반화 금지**. 이번 범위에서 타 문제들의 경험을 조합한 신규 해결책 창작은 제외한다.
- `NO_RELEVANT_HISTORY` — 신뢰할 만한 유사 사례가 없으면 **과거 검증 해결책 추천을 생략**하고 사유·검색 범위를 표시한다. 해당 사건의 D0~D8 일반 증거 기반 조사와 인간 판단은 계속 가능하나, 타 사건의 원리를 결합해 새로운 해결책을 추론·제안하는 경험 전이 기능은 수행하지 않는다.

**추천 안전 계약:** 매 제안에 `mode`, 현재 문제/과거 사건 ID, 유사점·차이점, 과거 **D6 결과**(성공/실패/불충분/미확인), 재발 정보, 적용 조건, 반례, 출처 버전, 미확인 사항, 다음 확인/실험, 사람 선택 상태를 포함한다. 조치의 효과가 후일 부정되면 과거의 추천 근거도 stale로 전환한다. **지식 유사성 ≠ 현재 원인의 확정, 실패 사례 ≠ 현재 조치의 무조건 실패**.

**G8 최소 수용 테스트:** (a) 현재 조건에 부합하는 검증 성공 사례가 우선 추천됨, (b) 동일 증상이나 설비 조건이 달라 맹목적 재사용이 차단됨, (c) 과거 실패·재발의 경고가 반영됨, (d) **유의미한 과거 사례가 없을 때** `NO_RELEVANT_HISTORY`로 표시하고 경험 기반 추천은 하지 않음(일반 조사 흐름은 유지), (e) 결과/개정 취소 시 검색/추천 재평가, (f) 권한 없는 사례 비노출, (g) Meta OFFLINE에서도 구조화 검색/수동 검토 가능. 정상 데모는 **하나의 대표 동일/유사 사건**으로 통합하고, 매칭 없는 경우는 추천 생략 회귀 테스트만 수행한다.

### 6.5.2 하이브리드 오케스트레이션 책임

- **FastAPI Workflow Orchestrator:** D0~D8 상태, 권한, 정책 게이트, 실제/모의 조치와 감사 이벤트 통제.
- **서버 Task Router:** 규칙/SQL/통계/검증 작업과 AI 추론 요청 구분, 중단·타임아웃·예산·재시도 제어.
- **Meta Investigation Agent:** 유사 사건과 증거 부족 검토, 다음 읽기 전용 도구 선택, 가설 비교, 추가 실험 및 과거 조치 우선 검토 제안.
- **Tool Executor:** 조회 도구 allowlist·사건 접근·출력/입력 계약·데이터 외부 전송 정책 집행. AI가 승인/실행 도구 직접 호출 금지.
- **Validation Engine + 사람:** 근거/원인/효과/조치 적합성 독립 검증 및 최종 판정/승인. Meta LIVE 불가 시 과거 이력 검색·결정론적 추천 및 수동 선택은 유지.

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

## 11. 우선순위·일정 원칙 (최신)

**현재 기준선:** G0~G8/PREFLIGHT는 최신 코드·기록에서 확인된 범위를 보존한다. 승인된 작업의 재구현을 금지한다. G1 Meta LIVE는 `BLOCKED_NO_CREDENTIALS`로 분리한다.

**최종 순서:** `R0(모노레포·모듈화·CI) → A(G8 집중 보완) → B(G9 Docs) → C(POST-G9 통합 감사) → D(G10 승인본 DOCX/PDF + E2E) → E(Meta LIVE 자격 증명 있을 때만) → F(최종 안정화)`. E는 외부 자격증명에 의존하므로 독립 분기로 진행하며, G9/G10의 결정론적 구현을 멈추지 않는다. 다만 **LIVE 연동 성공을 주장하려면 E=PASS가 필요**하다.

**마감 우선순위:** R0 도중 회귀가 발생하면 해당 변경을 소규모로 되돌리거나 고쳐서 안정성을 최우선으로 확보한다. 단일 합성 품질 사건의 전체 데모와 필수 반례를 우선한다. 공정 추가 실데이터 연결, 벡터 DB, 복잡한 멀티 에이전트, 전면 재학습 등은 이번 범위 밖이다.

## 12. 완료 정의(DoD)

- [ ] G0~G8/PREFLIGHT의 변경 전·후 테스트 기준선을 확보하고, 이미 구현한 기능은 중복 구현하지 않음.
- [ ] R0의 `frontend/src`, `frontend/tests`, `backend/src`, `backend/tests` 구조와 독립 CI/통합 CI가 정상 통과.
- [ ] D0 긴급 조치(팀 구성 전)와 D1~D8 정상 사건 완결 E2E.
- [ ] 핵심 오류(D2 수치/LOT, D3 미실행, D4 무증거 원인, D6 무효 효과, D7 가짜 개정, D8 조기 종료)를 서버가 차단.
- [ ] 4M·5Why·Fishbone 입력은 **가설과 검증**까지 추적; 원인과 SHAP/추천 혼동 없음.
- [ ] Evidence 신뢰도/수정 반영, 정책별 선후관계, 고객사 양식 버전 검증.
- [ ] 인간 Docs 편집·AI 제안/수락 분리, 승인 스냅샷 불변, 변경 영향 반영.
- [ ] 실제로 확인한 명령/출력에 기반한 pytest·Ruff·migration·frontend build·HTTP/UI 검증.
- [ ] LIVE Meta 테스트는 성공 여부 사실대로 기록하고 비밀키 유출하지 않음.
- [ ] **G9 완료 기준:** Docs 화면과 DB/증거/정책/양식 사이의 검증·승인 일관성 확인. DOCX/PDF 출력 일치는 **G10 별도 범위**.
- [ ] README/SECURITY/HACKATHON_WORK_LOG 최신화, synthetic/POC 한계 공개.

### 참고 원칙
8D는 다부서 문제 해결 체계이며, D5는 영구조치의 **선정·적합성 검증**, D6는 **실행·효과 확인**, D8은 팀 결과 승인·종료와 공헌 인정까지 포함한다. 고객사 요구사항이 있으면 그것의 유효 버전을 정책/TemplateContract에 명시한다.

## 13. G5~G9 우선순위·실패 경계 확정 (원 요구사항; 현재 G5~G8 구현 기록 있음)

1. **PREFLIGHT 선행 수정:** 기존 `workflow.py`의 D2/D3/D4 승인 API가 `WorkflowPolicy`가 판단하는 것과 충돌하지 않도록 **한 검증 함수/서비스를 권위 있는 진입점**으로 지정한다. 문서 전용 승인과 긴급 실행의 종류·게이트는 분리한다. 기존 D2→D3→D4 승인 이력은 유지하고, 긴급 `ActionEvent`는 문서 승인 없이 합법적 경로로 허용한다. **구 정책 시점의 승인 이력 무효화 금지.**
2. **G5:** 구조화 D4 다원인·반증·재현 실험·검토자 승인. 가설 생성과 원인 확정 UI/API 분리.
3. **G6:** D5 원인별 영구 조치 선택·사전 타당성. D6 실행/사전 등록 효과 기준/통계적 비교/실패 시 재진입. 기존 `Action`, `ActionEvent` 활용.
4. **G7:** SOP/FMEA/Control Plan **유효 개정 및 배포 증빙**과 D8 잔여 위험·고객 통보·종결 게이트. 합성/시뮬레이션 문서 표시.
5. **G8:** Historical Harness의 유사 사건·과거 D6 검증 조치를 연결하여 적용 조건 확인 후 우선 추천하고, 실패·재발·미확인 건은 경고/재조사한다. Meta의 Evidence-Gap 자율 Tool Calling을 서버 정책 아래 통합한다. `app/factcheck.py`, `app/report.py`, `app/ncr.py`가 서로 다른 승인 판단을 하지 않도록 **일관된 구조화 Claim 검증 서비스**로 단계적 통합. DB exact 조회와 비정형 문서 검색 분리, `TemplateContract`는 결정론적 필수 항목 검증. **RAG/NLI 성공만으로 승인 금지.**
6. **G9:** `DocumentVersion/Claim` 유지, 수기 편집·409·버전별 증거/정책/양식/규칙 해시. AI diff 제안은 사람 수락 전 적용 금지. 승인된 기존 스냅샷과 이전 승인 이벤트는 변경하지 않음.
7. **POST-G9:** 코드·업무·데이터/보안 통합 감사 → `docs/implementation/POST_G9_REFACTOR_PLAN.md` → **P0 오류와 승인 우회만 수정**. 성능 튜닝·코드 스타일·아키텍처 대공사는 위험과 ROI를 평가해 G10 전후로 미룰 수 있음.
8. **필수 무결성 테스트:** 기존 S6 승인/감사, D0 신호/긴급 D3, D3 계획·실행·독립 확인, 원인 근거, D6 실패, D8 조기 종료, source revision, 구 정책 승인 이력, Meta offline, 동시 편집, 권한 우회.

**개발 완료와 사용 준비를 구분:** 해커톤 G9까지 완성되더라도 실제 현장 배포에 필요한 SSO/MFA, 계약/DLP, 현장 연동, 암호화, 운영 및 품질시스템 검증은 별도 과제다.

## 14. 최종 데모 범위·기존 QMS 대비 문제 정의

**프로젝트 문제:** 기존 품질 시스템의 단순 사건 기록·양식 관리에 추가로, 분산 데이터와 증거 확인의 반복 작업, 과거 검증 조치의 재사용 부족, 유사 사건 재발 시 동일 시행착오, 생성된 보고서의 원본 불일치, 수정 후 승인 무결성 문제를 줄이는 데 초점을 둔다. **모든 상용 QMS에 이 기능이 없다고 주장하지 않는다.**

**단일 합성 시나리오:** 제조 이상 감지 → D0/D1/D2/D3 → 과거 동일·유사 사건 알림(검증된 조치와 현재 조건 차이 제시) → '기존 방식 우선 검토할까요?' 담당자 선택 → 필요 시 Meta가 추가 조사 → D4 검증 → D5/D6 조치/효과 → D7/D8 → 보고서 수기 오류 삽입 시 원본 대조 차단 → 재검증 → 승인 DOCX/PDF. 실제 공장 실행·해커톤 성능 개선율을 허위 주장하지 않는다.

**데모 최소 증빙:** 해당 유사 사건·과거 효과 검증 원본 ID, 성공/재발 여부, 현재 적용 조건과 차이, 추천 이유, 사람의 선택/사유, Meta 도구 요청/실제 실행 로그 구분, 검증 오류 코드, 최종 단계·서명·버전 기록.

**범위 제외:** 별도 상용 QMS 복제, 4개 비교 실험군/30건 대규모 평가, 모델 자체 재학습, 모든 공정 실증, 실제 생산라인 조치 자동 실행. 기능 성공은 우선 한 대표 사건의 E2E + 필수 부정 테스트(매칭 없음 1개 fixture 포함)로 증명한다.

## 15. 기능 동결 결정 (v5.5 — 해커톤 MVP 최종 범위)

**이 문서로 해커톤 기능 범위를 동결한다.** 앞으로 추가할 기능은 심사 필수 조건/실제 오류/데모 수행 불가능 문제에 한해 예외 승인한다. 핵심 목표는 **한 건의 품질 문제를 D0~D8까지 안전하게 추적하고, 과거 성공·실패를 활용해 Meta가 새 조사를 제안하고, 사람이 검증/승인하는 완결된 흐름**이다.

**반드시 구현/검증:** G5~G7 업무·효과·종결 / G8 증거·문서 검증 + `KNOWN/ANALOGICAL` 경험 기반 추천 + 서버 통제 Meta 읽기 전용 Tool Calling / G9 Docs 편집·재검증 / G10 출력·단일 사건 데모 / Meta LIVE 스모크(키 확보 시). 과거 사례는 **실효성 검증 결과 및 실패 사례와 함께** 제공; 결과 축적은 자동 모델 재학습이 아닌 검증된 기록 검색 가능화.

**이번에 더 확장하지 않을 것:** 파운데이션 모델 파인튜닝, 모델 재학습 인프라, 그래프 DB 필수 도입, 복잡한 다중 에이전트, 자동 공정 제어/출하 승인, 실제 MES/ERP 연동, 상용 QMS 복제, 다수 공정 실증, 30건 이상 벤치마크, 과장된 ROI 추정, 화려한 대시보드 우선 개발.

**범위 통제:** 기존 FR(특히 P0), 권한·증거·감사·승인·실험 안전 요구를 기능 동결이라는 이유로 삭제하지 않는다. G8 기능이 일정에 위협되면 기존 이력 DB와 텍스트 검색·확정 조치 효과 정보만으로 최소 동작을 우선 확보하고, 별도 벡터 DB·경험 전이 기능 개발은 중단한다. 모든 기능은 `SIMULATED`와 `LIVE VERIFIED`를 구분하며, **G10 이후 LIVE 성공 전에는 Meta 추론의 실제 성능을 주장하지 않는다.** Meta LIVE 인터페이스 계약은 G8에서 테스트 더블과 스키마 검증으로 사전 확인하고, 권한 있는 API 키가 확보되면 G10 이전이라도 최소 스모크 테스트를 조기 실행할 수 있다.

**정직한 가치 주장:** '제조 현장의 경험을 검색·대조해 다음 해결 방향을 빠르게 검토하도록 지원한다'가 목표다. 단일 데모만으로 일반적 의사결정 시간 단축이나 모든 신규 불량 해결 능력이 입증되었다고 주장하지 않는다.

## 16. 해커톤 이후 로드맵 (이번 구현·테스트·데모 대상 아님)

- **미지 문제에 대한 경험 전이 추론:** 직접적인 과거 사례가 없을 때 다양한 공정·문제의 검증된 지식을 연결해 새로운 원인 가설·해결책 후보·구별 실험을 제안하는 기능. 별도 데이터 품질/안전성 평가와 전문가 검증을 전제로 한다.
- **선택적 모델 고도화:** 충분한 승인·효과 검증 이력이 확보되고 성능 비교로 가치가 입증될 때만 임베딩 모델 고도화나 학습을 검토한다.
- 해커톤 MVP에서는 **사례 누적·검색·유사 사례의 검증된 조치 재사용**까지만 완료한다. 미지 사건은 `NO_RELEVANT_HISTORY`로 안내하고 기존 일반 조사 절차로 처리한다.


## 17. G10 최종 출력·통합 데모·정합성 계약 (필수)

**목표:** G9에서 승인된 8D의 불변 snapshot을 기준으로 **DOCX와 PDF를 생성**하고, 화면·DB·내보낸 파일이 같은 사건·상태·수치·근거·개정·승인자를 가리키는지 검증한다. 템플릿은 기존 검증된 `TemplateContract`를 사용하며, 최신 데이터가 승인 뒤 바뀌었다면 신규 검토/재승인이 필요한지 정책으로 판단한다.

- **Export:** D0~D8 주요 내용, 5W2H, IS/IS NOT, 원인·실험, 조치 이행·효과 검증, 예방 개정, 담당자 검토/승인, 증거 출처, 버전, 시뮬레이션 고지를 포함. 내보낸 시점/해시와 승인 snapshot 버전을 남긴다.
- **PDF/DOCX 검증:** 필수 표/필드 누락, 숫자·단위·LOT 불일치, 잘린 텍스트, 재출력 뒤 내용 변경, 승인 안 된 초안/만료 승인본 출력은 명확히 오류 처리한다. PDF 렌더링과 페이지 시각 점검을 포함한다.
- **통합 정상 데모:** 합성 사건 발생 → D0~D3 → 과거 동일/유사 사건의 **검증된 조치 우선 추천**(과거 실패·재발 경고 포함) → 사람의 선택 → Meta 도구 호출 기반 조사·가설 → D4~D8 검토/승인 → 결과 Experience Memory 재등록 → 승인본 DOCX/PDF.
- **필수 실패 데모:** 사람의 수기 수치·LOT 조작 뒤 자동 재검증/승인 차단; 조치 계획만 있고 실행 증거 없는 D6/종결 차단; 과거 이력이 없는 경우 `NO_RELEVANT_HISTORY` 및 정상 조사 계속. 비교군 시스템은 만들지 않는다.
- **실험 주장 범위:** 대표 합성 사건 1건의 end-to-end + 필요한 소규모 반례 fixture. 성능·시간 절감·수상 가능성 등의 수치는 실제 측정/공식 규칙 없이는 주장하지 않는다.

## 18. Meta LIVE·안정화·제출 준비 (최종 범위)

1. **실제 연동:** 정당하게 발급된 Meta API 키를 환경 변수·비밀 저장소로만 주입. `/provider.live_status`/스모크 경로를 사용해 실모델 ID, 호출 성공, 실제 tool choice, 인자, 도구 실행, 근거 인용, 응답 스키마, 비용/지연, rate-limit/timeout/오류 복구를 확인한다. 키 없는 상태는 `BLOCKED_NO_CREDENTIALS`이며 테스트 더블 결과와 혼동하지 않는다.
2. **작업 분리:** D0~D8 정책·수치 계산·승인·문서 버전은 백엔드 결정론적 제어. Meta는 읽기 전용 조사 계획·문서 요약·가설/검증 제안 및 과거 사례 설명을 맡는다. 서버 도구 실행기에서 ACL/사건 범위/egress/요청 횟수와 비용 예산을 검사한다.
3. **디버깅 우선순위:** P0 = 데이터/승인 우회·보안/감사 훼손·잘못된 결과 확정; P1 = E2E 단절·호출 실패/타임아웃·파일 출력 불일치; P2 = 사소한 UX/성능. P0 해소 없이 성공 주장 금지.
4. **검증 커맨드:** 기존 테스트 스위트와 변경 모듈 테스트, Ruff, Alembic 신규/기존 DB 업그레이드, 웹 빌드, 백엔드 HTTP, 프론트엔드 E2E, DOCX/PDF 렌더 검사. 각 수행 명령/성공 여부를 로그에 기록한다.
5. **최종 문서:** `HACKATHON_WORK_LOG.md`, `docs/V5_IMPLEMENTATION_STATUS.md`, `README.md`, `SECURITY.md`, 데모 실행 매뉴얼을 실제 동작/제약에 맞게 정리한다. 실제 공장 데이터/실행이 없다는 점을 명시한다.
6. **기능 동결:** 해커톤 기간 신규 기능 추가 없음. 미지 사건 새로운 해결책 생성·모델 가중치 재학습·멀티 에이전트·대규모 벤치마크는 이후 로드맵에만 둔다.

## 19. R0 — 해커톤 제출 전 필수 모노레포 구조 및 모듈화 계약 (P0)

### 19.1 디렉터리 구조 — 요구사항의 일부

**저장소 루트는 `frontend/`, `backend/`, `docs/`, `prompts/`를 분리**하고, 소스와 테스트는 각 애플리케이션 하위에 둔다. 요구사항과 공통 운영 문서는 루트에 둔다. 아래는 목표 구조이며 빈 폴더를 채우기 위한 형식적 파일 생성은 불필요하다.

```text
meta_Hackathon/
├── frontend/
│   ├── src/
│   │   ├── api/                   # 공유 API 클라이언트, request/response 타입
│   │   ├── components/            # 공통 컴포넌트
│   │   ├── features/              # eightd, documents, experience, investigation 등
│   │   ├── hooks/
│   │   ├── types/
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── tests/                      # unit, integration, e2e는 실제 테스트가 있을 때
│   ├── public/                     # 기존 사용분만
│   ├── package.json
│   ├── package-lock.json
│   ├── vite.config.ts
│   └── tsconfig.json
├── backend/
│   ├── src/
│   │   └── app/                   # 기존 app 패키지; 실제 비즈니스 책임 분리
│   │       ├── main.py
│   │       ├── db.py              # 전면 분할 필수 아님
│   │       ├── workflow.py
│   │       ├── eightd.py
│   │       ├── experience.py
│   │       ├── factcheck.py
│   │       ├── validation.py
│   │       ├── investigator.py
│   │       └── ...                # 기존 모듈 재사용; 불필요한 재작성 금지
│   ├── tests/                     # 기존 Python 테스트 전부 보존
│   ├── scripts/                   # 기존 실행/평가/스모크 스크립트
│   ├── migrations/                # 기존 Alembic revision 보존
│   ├── pyproject.toml
│   └── alembic.ini
├── docs/
│   ├── architecture/              # 구조 감사 및 dependency map
│   ├── testing/                   # 테스트 계약·추적표·실행 증거
│   ├── implementation/            # 구현 상태, 변경·통합 결과
│   └── evaluations/               # 실제 관측 평가 결과
├── prompts/
│   └── QualityOps_AI_CODEX_MASTER_R0_G10_FINAL.md
├── QualityOps_AI_FINAL_REQUIREMENTS_v5_5_MONOREPO_FINAL.md
├── README.md
├── SECURITY.md
├── HACKATHON_WORK_LOG.md
├── PROJECT_SCOPE.md
├── .gitignore
└── .github/workflows/
    ├── ci.yml                     # 전체 검증 orchestration: backend/frontend → integration
    ├── backend-ci.yml             # 재사용 workflow (권장)
    ├── frontend-ci.yml            # 재사용 workflow (권장)
    └── integration-ci.yml         # 재사용 workflow (권장)
```

**파일 배치 원칙:** 루트에 중복 `app/`, `web/`, `tests/`, `scripts/`를 상시 병행 운영하지 않는다. 이동 과정의 임시 호환 계층이 필요한 경우 기한·제거 조건을 기록한다. 기존 `app/static/web` 빌드 자산은 **서버가 제공할 수 있게 동일 계약으로 유지**하거나 동등한 새 위치로 옮긴다. 실제 Node 빌드 산출물의 Git 추적 여부는 기존 배포/CI 동작을 먼저 분석한 뒤 결정한다.

### 19.2 기술 계약 — 폴더 이동 중 불변

| 분야 | 완료 조건 (반드시 증명) |
|---|---|
| Python packaging | `backend/pyproject.toml`에서 `backend/src/app` 패키지 설치·import 가능; `python -m pytest`가 올바른 패키지를 가리킴 |
| FastAPI | 기존 `create_app`, `app.main:app`, `GET /health`, 모든 공개 API 경로와 스키마 유지 |
| SQLite | DB URL이 **실행 작업 디렉터리에 따라 임의로 바뀌지 않도록** 명시적으로 처리; 기존 사용자 DB를 손상하지 않음 |
| SQLAlchemy/Alembic | 기존 `db.py` 모델·revision ID/순서/히스토리 불변; 새 scratch DB head 업그레이드, diff/drift 검사 |
| React/Vite | `frontend/src`, 프록시 경로, 빌드 산출물, `GET /app` 및 기존 `/ui` fallback 유지 |
| 환경변수·보안 | `.env`, 키, DB, 다운로드 원본 데이터, 토큰이 커밋·로그에 포함되지 않음 |
| 스크립트 | `backend/scripts`의 `python -m scripts...` 및 평가 스크립트가 새 실행 위치에서 정상 동작 |
| docs | 루트 최신 명세서·`prompts/` 및 `docs/`의 상대 링크 모두 유효; 과거 문서는 참고용으로 구분 |
| 배포 | 프론트 변경 및 Backend 배포 간 번들 경로 차이로 `/app` 404가 발생하지 않음 |

### 19.3 모듈화 원칙 — 경로만 옮기는 것으로 끝내지 않기

- **프론트엔드:** 비대해진 `web/src/App.tsx`를 기존 화면 단위(`dashboard`, `eightd`, `evidence`, `spc`, `experience`, `investigation`, `documents`, `audit`)로 분리한다. 공통 API 호출/타입/상태/컴포넌트를 재사용하고 현재 UI 디자인과 업무 동작을 유지한다. 무의미한 추상 계층은 만들지 않는다.
- **백엔드:** 이미 모듈화된 `causes`, `effect`, `closure`, `experience`, `factcheck`, `investigator`, `tools`, `policy`는 유지한다. `main`, `workflow`, `eightd`의 API/서비스 혼재는 **기준 동작을 테스트로 증명할 수 있는 부분만** 분리한다. 모델 정의를 큰 파일에서 억지로 분산시키지 않는다.
- **테스트:** `backend/tests`와 `frontend/tests`에서 실제 실행되는 테스트를 분리한다. 통합 테스트는 필요에 따라 `backend/tests/e2e` 또는 `frontend/tests/e2e`로 명시한다. **폴더 존재 자체를 테스트 통과로 주장하지 않는다.**
- **호환성:** 공개 HTTP·문서 해시·승인 결과·과거 경험 검색 순서·감사 체인·데이터 상태·Meta 도구 schema는 리팩터링으로 변경하지 않는다.

### 19.4 CI/CD — 세 영역의 조건부 의존성

- **Backend CI:** Python 3.12, 패키지 설치, 전체 pytest, Ruff, 새 DB Alembic head/drift, FastAPI 기본 HTTP/권한/감사 점검.
- **Frontend CI:** Node 환경, `npm ci`, TypeScript 검사, Vite 빌드, 실제 존재하는 프론트 테스트 실행, 주요 화면 렌더·API 연결 검증.
- **Integration CI:** Backend CI와 Frontend CI가 **성공한 같은 커밋**에 대해서만 수행. 신규 scratch DB에서 `/app`·`/ui`·API·D0~D8·Experience Memory·ClaimValidator·승인·감사·Meta TEST_DOUBLE을 확인. 별도 워크플로 파일 구성 시 GitHub Actions의 **cross-workflow `needs`가 바로 동작하지 않는다는 점**을 고려하여 `workflow_call` 재사용 워크플로 + 최상위 `ci.yml`의 `needs`를 사용하거나 동등한 검증 가능한 DAG를 구성한다.
- **Meta LIVE:** 비밀키 없는 공개 CI에는 강제하지 않는다. LIVE가 빠졌으면 별도 `BLOCKED_NO_CREDENTIALS/NOT_RUN`으로 표시한다. LIVE 테스트 더블의 PASS를 실제 LIVE PASS로 치환 금지.

### 19.5 R0 수용 기준 (모두 필수)

1. 폴더 레이아웃과 앱별 `src/tests` 구분이 실제 코드·테스트를 포함한다.
2. 기존 Python/React 의존성 설치, dev 실행, build, 서비스 경로가 정상이다.
3. 기존 226개로 기록된 테스트에 대해 **변경 전 기준선과 변경 후 실제 실행 결과**를 비교한다. 테스트 수 변화가 있으면 추가·합리적 이동 사유를 기록하며 **기존 검증 제거는 금지**.
4. 권한·승인·증거·정정·8D 단계 상태·Experience Memory·ClaimValidator·Meta TEST_DOUBLE·감사 체인 계약이 동일하다.
5. Python import, pytest discovery, Alembic, Vite proxy, static assets, scripts, docs 링크가 정상이다.
6. Backend/Frontend/Integration CI의 실제 실행 결과가 성공이며 통합 CI가 의존 검증을 우회하지 않는다.
7. 파일 이동·모듈 분리는 작은 커밋으로 수행하고 변경 원인과 결과를 `docs/architecture/REFACTOR_AUDIT.md`에 기록한다.
8. 필수 검증 미실행/실패가 있으면 R0는 `PASS`가 아니다. 롤백/수정 후 재검증한다.

## 20. R0 이후 G8 보완, G9·G10 및 최종 검증 게이트

### 20.1 G8 집중 보완 (재구현 금지)

- **경험 재사용:** 새로 D8 종결한 사건이 차기 사건 검색에 반영되는지; `VERIFIED_EFFECTIVE`와 `NOT_YET_OBSERVED`를 구별 표시하는지; 실패·재발 사례를 성공으로 오추천하지 않는지; 권한·시점·사이트 차단과 폐기 후 stale 처리를 유지하는지.
- **ClaimValidator:** 수치 둘 이상인 문장, `value` 대 본문 값, 잘못된 LOT/단위/분모, 대체된 원본, 약한 증거, 잘못된 '실행 완료'/원인 확정, 반올림 정상 사례를 **추가 반례로 확인**한다. 문제를 재현한 경우만 수정하고 테스트한다.
- **TaskRouter/Meta:** 결정론적 검증은 서버, 읽기 전용 도구는 모델에 제공한다. 모델 장애 시 수동 검증과 과거 사례 검색은 유지한다.

### 20.2 G9 Human Docs 완료 조건

1. 사용자 초안 편집(문장·수치·Claim·Evidence ID), 이전/새 버전 diff 및 신규 버전 저장.
2. 작성 중/검토 중/승인 완료 상태에 맞는 편집 권한; 승인본 불변.
3. 편집 시 기존 `factcheck.validate` + `validation.run`을 재사용하여 DB/증거/품질/LOT/단위/문서/정책/양식 hash를 재검증.
4. 변경 후 `BLOCK`인 문서의 승인 거부; stale validation/hash를 신규 승인에 재사용 금지.
5. 동시 편집·검토 중 변경·원본 정정·정책 버전 변경 등 충돌 차단(가능한 경우 409)과 원자성/감사 기록.
6. **Meta 제안 기능**은 사람이 수락하기 전 read-only 제안·diff만 보여준다. 수락 후에도 재검증. Meta 키 미존재 시 수동 편집·서버 검증은 정상 작동하고 AI 제안은 블로커로 표시.
7. 관련 테스트/HTTP/브라우저/빌드/DB 검사와 문서 내용 일치가 전부 PASS.

### 20.3 G10 최종 출력 및 E2E 완료 조건

1. **승인된 불변 스냅샷**을 기준으로 D0~D8 내용을 DOCX와 PDF에 출력(실제 파일 존재·열림·페이지 확인).
2. 사건 ID, LOT·단위·핵심 수치, 근거 ID, 원인/실험, 조치·효과, 예방 개정, 서명·결재 정보, 합성 데이터 고지가 UI/API/승인본/출력물에서 일치.
3. 원본 정정/승인 hash 불일치/미결 조건/미승인 문서일 경우 최종 승인 출력 차단 또는 명시적 DRAFT 출력으로 분리.
4. 단일 합성 사건 `SPC → D0~D8 → 과거 경험 추천 → 사람 선택 → Docs 수정/재검증 → 종결 → DOCX/PDF → 경험 축적 → 다음 사건 재검색`을 반복 재현.
5. 대표 반례(잘못된 수치, 잘못된 LOT, 실행 증거 없는 효과 주장, 조기 종결, 과거 실패 조치 선택)가 차단됨.
6. Backend/Frontend/Integration CI 및 핵심 E2E 통과. Meta LIVE 자체는 **자격 증명 있을 때만 별도 E=PASS**.

### 20.4 Dependency-aware execution gate / Explicit exit criteria — 공통 정책

```text
R0-A 기준선/의존성 분석
   ├── R0-B backend/ 이동·테스트·스크립트·Alembic
   └── R0-C frontend/ 이동·화면 모듈화·테스트
                 └── R0-D 통합 경로/CI
                       └── R0-E 구조 감사·전체 회귀 = R0 PASS
                             └── A G8 보완 PASS
                                   └── B G9 PASS
                                         └── C POST-G9 AUDIT PASS
                                               └── D G10 PASS
                                                     └── F 안정화 완료
E Meta LIVE: 자격 증명 독립 분기, 실행 시 LIVE 결과와 스모크·도구 검증 별도 PASS
```

- **단계 종료 기준(Exit Criteria):** 요구사항과 테스트의 대응표, 정상·반례·회귀 실행 결과, 설치/빌드/스키마/HTTP/UI 확인, 중요한 불변식, 실제 SHA와 상태 보고가 모두 충족돼야 `PASS`.
- **Dependency Gate:** 차단된 선행 기능에 의존하는 **수용·최종 완료 주장만** 제한한다. 비의존 구현, 문서화, 독립적인 스모크는 가능하다. 단 의존성이 풀리기 전에 통합 PASS를 선언하면 안 된다.
- **상태:** `PASS`, `PARTIAL`, `BLOCKED`, `NOT_STARTED`, 외부키에만 `BLOCKED_NO_CREDENTIALS`, `NOT_RUN`. 기존 구현 문서의 `BUILT`와 실제 단계 합격 `PASS`를 혼동하지 않는다.
- **P0 오류:** 권한·승인 우회, 외부 데이터 유출, 불변 감사 훼손, 수치·결과 허위 확정, 산출물 위변조가 있으면 의존 경로 즉시 중단·수정. P1 데모 단절을 G10 완료 전에 해소.
- **안정화 종료:** 새 scratch DB 단일 명령 재현, 최신 HEAD의 CI 및 E2E 통과, 내보낸 파일 점검, 문서·사용법·제약·합성 고지 최신화. 미검증 LIVE는 미검증 상태로 남기고 주장하지 않는다.

## 21. 요구사항 추적성, 파일 경로 기준 및 인수 형식

- **Source of Truth:** 이 명세서(무엇을 만들지) > `prompts/QualityOps_AI_CODEX_MASTER_R0_G10_FINAL.md`(어떻게 실행할지) > `docs/implementation/V5_IMPLEMENTATION_STATUS.md`(실제 관측 상태) > 작업 로그(시간별 기록). 정책과 구현이 다른 경우 명세서를 조용히 고치지 말고 차이를 기록/승인받아야 한다.
- **진행 보고:** 각 R0/A/B/C/D/E/F 구간별 `예상 선행조건 → 수행 내용 → exit criteria 증거(실행 커맨드·결과) → 미통과 항목/원인 → PASS/PARTIAL/BLOCKED → SHA/푸시 여부 → 다음 unlock 가능한 구간` 표기.
- **경로 이전:** 이전 `app/`, `web/`, `tests/`, `scripts/`, `migrations/` 문서 경로는 옛 구조다. **실행 명령과 새 문서에는 반드시 실제 파일의 새 경로**를 사용한다. 검증용 이력 문서의 과거 경로·결과를 삭제하지 않는다.
- **미구현 테스트:** 실제로 존재하지 않는 Frontend 테스트·Meta LIVE·실환경 데이터/ROI 실험은 `NOT_RUN` 또는 `NOT_IMPLEMENTED`로 구분하고 성공이라고 기록하지 않는다.
- **최종 인수 자료:** README 실행법, `docs/architecture/REFACTOR_AUDIT.md`, 요구사항↔코드↔테스트 추적표, 최신 구현 상태, 감사/보안 한계, G10 DOCX/PDF 검증 증거, Meta LIVE 로그, 데모 재현 순서, 작업 커밋 목록.


---

## 22. Agent-First UX 전환 계약 (v5.6 추가 요구사항, 기존 v5.5 계약 보존)

### 22.1 목표와 범위
- **목표:** 기존 G0~G10 전체 도메인 기능을 삭제·간소화·재구현하지 않고 사용자 진입점만 대화형 QualityOps Agent 중심으로 통합한다. 사용자는 자연어 요청 후 증거, 분석, 작업 상태, 승인 요청, 문서, 이력을 같은 대화 안에서 확인한다.
- **제품 형태:** Agent-First + 독립 업무 관리(내 할 일/부서 할 일) + 필요 시 열리는 기존 전문 상세 화면. 주 진입점은 Agent이고 기존 UI는 회귀 검증 및 Meta 장애 시 수동 경로로 보존한다.
- **명시적 비범위:** 다중 LLM 에이전트 도입, 기존 Backend 도메인 모듈 병합, 기존 Gate 우회, AI의 독자적 승인/조치 실행/원인 확정, 실제 제조 데이터로 전환, 인증·배포 체계 완성.
- **Source of Truth:** 1~21절의 기존 승인·증거·상태·데이터·API·보안 계약을 상속한다. 22절과 충돌하면 기존 안전/검증 계약 우선. 다른 구현 전략이 필요할 때 먼저 차이와 테스트를 문서화한다.

### 22.2 사용자 정보구조 및 화면
- 기본 라우트/화면: **AI Agent**. 기존 Case selector와 현재 사용자(데모 X-User) 컨텍스트, SYNTHETIC 표시, Meta 상태를 계속 보여준다.
- **독립적으로 계속 접근 가능한 업무 화면:** 내 할 일, 부서 할 일(기존 /queue?scope=mine|department), 검토/승인 대기, Case 진행 상태 및 차단 사유, 문서 편집·Diff, 감사 이력. 별도 승인 대기 백엔드 테이블을 중복 생성하지 않는다. 기존 Queue의 REVIEW/BASIS_CHECK/REDRAFT/ANSWER_COMMENT 등을 그대로 사용한다.
- **대화 내 동적 결과 컴포넌트:** 출처 표시된 증거 테이블(LOT/근거 ID/버전), SPC 차트와 이상 신호, ML 예측·SHAP의 비인과적 설명, RAG 과거 사례·실패 사례, D0~D8 타임라인/차단 사유, 문서 초안·validation issues·Diff, 승인/반려 카드(실제 권한 확인), 완료된 승인본의 DOCX/PDF 링크, 관련 감사 이벤트.
- 상세 컴포넌트는 **실제 서버 응답**을 바인딩한다. 하드코딩된 '성공', 'LIVE', '승인됨' 배지와 합성 UI를 실측 결과처럼 표시하는 것은 금지한다.
- 접근성: 키보드 탐색, 상태의 문자 표현(색만으로 구분 금지), 로딩/실패/재시도/빈 결과, 좁은 화면 대응, 재진입 시 사건/작업 상태 복원.

### 22.3 Agent의 권한과 책임
1. 자연어 요청 → **구조화된 intent, 대상 case/LOT, 사용자 role, 실행 계획**으로 변환한다. 모호한 사건 식별자는 조용히 추정하거나 다른 Case에 쓰지 않고 사용자 확인을 요구한다.
2. 기존 \`taskrouter.py\`, \`investigator.py\`, \`tools.py\`, SPC/ML, \`experience.py\`, \`validation.py\`, \`workflow.py\`, \`export.py\` 및 기존 API를 우선 **어댑터로 재사용**한다. UI 전용 중복 업무 규칙 생성 금지.
3. 사전 조회·분석·추천은 자동 수행 가능. 서버에 변화를 만드는 동작은 allowlist에 등록된 명시적 tool schema 및 **서버 권한/상태 검사**를 통과해야 한다. 문서 초안 작성, 검토 요청 등 각 작업의 사용자 승인 필요 여부는 기존 엔드포인트 계약에 따른다.
4. **AI가 자기 승인·타인 역할 가장·실제 조치 EXECUTED 기록·원인 CONFIRMED 판정·D8 종결을 자의적으로 수행하지 않는다.** 해당 서버 결정이 요구하는 근거와 인간 승인·권한을 유지한다.
5. 자동 실행 순서는 dependency-aware. 막힌 단계에서 **PAUSED/NEEDS_HUMAN/BLOCKED**를 표시하고 허용된 다음 작업만 제안한다. 이미 승인된 입력을 AI 추론으로 덮어쓰지 않는다.
6. 수행 결과는 불변 감사 이벤트와 링크를 통해 확인 가능하도록 한다. conversation log는 승인 기록의 대체물이 아니다.
7. 사용자 권한은 세션의 인증 주체(데모 단계에서는 기존 X-User)에서 서버가 결정한다. 사용자 문장이나 모델이 반환한 role/user ID를 신뢰하지 않는다.

### 22.4 Agent 실행 상태와 복구
- 최소 실행 상태: \`PLANNED → RUNNING → NEEDS_HUMAN / BLOCKED / FAILED / COMPLETED\`; 재개 전 서버의 case/document/policy/evidence 최신 상태를 재조회한다.
- 쓰기 도구의 idempotency key, optimistic version/hash, 재시도 안전성, timeout, 중복 클릭 방어를 정의한다. 동일 요청 재전송으로 중복 조치/승인이 생기면 P0.
- DB를 변경하는 에이전트 도구에 과도한 권한을 부여하지 않는다. 프롬프트 인젝션/외부 문서에 들어 있는 명령은 데이터로만 처리한다. 원본 검증과 외부 egress 제한은 기존 서버에서 강제한다.
- Meta LIVE 실패·키 미설정 시 **AI 오프라인 상태를 명확히 표시**하고 내 할 일, 승인, 수동 8D, 문서 편집/검증, 기존 UI가 동작해야 한다. TEST_DOUBLE 결과를 LIVE로 표기하지 않는다.
- 진행 중 앱 새로고침·역할/Case 변경·모델 오류에도 서버 작업 상태를 잃지 않는다. 백엔드에 영속 작업 저장이 필요하면 기존 DB 마이그레이션으로 분리하고 재개 테스트를 추가한다. 대화 메시지 재표시는 실제 서버 상태와 동기화한다.

### 22.5 기능별 UX 보존 매핑
| 기존 기능 | Agent 인터페이스 | 보존할 상세/수동 경로 |
|---|---|---|
| SPC / source / ML | 원인 조사의 필요 데이터 자동 조회·인라인 차트 | 원본 차트, 데이터 워크스페이스 |
| Investigator / RAG / Experience | 근거·비교 결과 카드와 next-evidence 설명 | 원본 상세·검색 결과 |
| D0~D8 / approval gates | 단계별 다음 허용 작업과 차단 이유 | 기존 8D 화면, 역할별 승인/수동 실행 |
| Documents / G9 | 인라인 수정 제안·검증 결과 / 상세 Diff 진입 | 기존 문서 편집기 |
| Queue | '내 할 일 알려줘', 승인 요청 알림 | **내 할 일 / 부서 할 일 독립 메뉴 필수** |
| Audit / History | 근거로 이동 가능한 로그·이력 카드 | 감사·이력 상세 화면 |
| G10 Export | 승인된 DOCX/PDF 다운로드 카드 | 기존 문서/보고서 다운로드 |
| Provider | LIVE/TEST_DOUBLE/OFFLINE 정확한 라벨 | 수동 경로 항상 가능 |

### 22.6 Agent-First 전환의 비기능/평가 지표
- **기능 동등성:** 같은 서버 초기 상태, 사용자 role, 입력, 근거 버전이면 기존 UI와 Agent 경로는 동일한 도메인 상태·문서 hash/validation·승인 및 감사 결과를 생성한다. 표현과 agent interaction log만 달라도 된다.
- **안전성:** 서버 Gate 우회 0건, 타 사용자 승인 0건, 외부 데이터 누출 0건, 거짓 확정 0건, 중복 mutation 0건.
- **편의성:** 동일 시나리오에서 사용자 조작 수, 완료 소요 시간, 오류/되돌리기 횟수를 기존 UI와 비교해 보고한다. 목표 수치는 측정 전 임의 확정하지 않는다.
- **관측성:** tool 이름/입력의 민감 정보 제거본/소요 시간/성공·실패/대상 Case·서버 감사 ID를 확인 가능하게 한다. latency/token/cost는 LIVE 측정 결과가 있을 때만 수치로 주장한다.
- **대표 시나리오:** "L02 이상 분석 → 증거 및 과거 실패 이력 → D4 가설 → 검증 필요 표시 → 인간 승인 → D6 효과 평가 → 문서 편집·Diff → 검증 → D8 종결 → PDF/DOCX" (실행/승인 없는 단계를 자동 완료하지 않는다).

### 22.7 전환 단계 (AG) 및 필수 수용 테스트
- **AG0 — Baseline & compatibility (선행):** 최신 main SHA, API/DB/openapi, 기존 G0~G10 기능, Queue, 247 backend/13 frontend 기록과 실제 최신 검사 결과를 수집한다. 기존 UI·E2E 보존. Gate: baseline 테스트와 CI PASS.
- **AG1 — Agent shell/UI:** Figma Make를 참조하되 UI만 구성. Agent 기본 화면, Case/role, message, dynamic cards, queue navigation, provider badge, fallback. Gate: layout/accessibility 및 기존 메뉴 정상.
- **AG2 — Read-only tools:** intent planner + read-only tool registry, evidence/SPC/RAG/ML/history/queue. Gate: 근거 연결/권한 필터/무근거 주장 차단, 타 Case 혼동 차단, OFFLINE 동작(수동 경로).
- **AG3 — Safe actions & human gates:** 기존 업무 API에 allowlisted writes, confirmation, server-side role validation, pause/resume, idempotency/retry. Gate: AI 승인 시도·Gate bypass·중복 클릭·stale versions 모두 거부.
- **AG4 — Document/export & end-to-end:** G9 editing/validation/Diff, G10 verified DOCX/PDF, D0~D8 real HTTP success/failure plus existing UI parity. Gate: 최종 결과/감사 동일성.
- **AG5 — UX/Meta LIVE evaluation & release:** 실제 작업 효율 측정, browser/a11y/manual fallback, fresh DB twice, full Backend/Frontend/Integration CI. LIVE는 API credential 있을 때 별도 조건부 검증; 미검증이면 \`BLOCKED_NO_CREDENTIALS\`로 보고하며 AG 오프라인 기능 PASS와 구분.
- **AG 필수 반례:** AG-T01 다른 LOT/Case 혼동 → 확인 필요; T02 서버 권한/승인 없이 D4 CONFIRMED·D8 CLOSED 시도 → 차단; T03 D6 FAIL → D4 재개; T04 잘못된 수치/근거→BLOCK; T05 오래된 문서 승인→409; T06 인젝션된 문서 명령 무시; T07 AI 장애 중 내 할 일·승인·수동 편집 동작; T08 새로고침 후 상태 복원; T09 같은 mutation 재시도 중복 없음; T10 기존 UI/Agent 결과 동등; T11 승인본 출력과 DRAFT 제한; T12 역할 전환 시 다른 사용자의 할 일 표시 금지.
- 테스트 추적표는 \`docs/testing/REQUIREMENT_TEST_TRACEABILITY.md\`에 **실제 코드 경로/테스트 이름/실행 결과**를 추후 구현 단계에서 추가한다. **이 절은 요구사항이며 현재 완료 상태를 뜻하지 않는다.**

### 22.8 완료 정의
AG0~AG5의 구현·실행 결과를 실제 코드와 테스트로 검증하고, 기존 G0~G10 회귀 0건, 권한/승인/ClaimValidator 일관성, HTTP E2E, Figma 설계와 실 UI 매핑, 독립 Queue와 수동 fallback 확인 후에만 Agent-First UX 전환 완료로 선언한다. 현재 Meta LIVE 미검증 상태를 자동으로 해제하지 않는다.
