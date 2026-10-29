# QualityOps AI — 최종 Codex MASTER 실행 프롬프트 (R0 → G10)
### v5.5 MONOREPO FINAL / 실행 게이트 + 단계별 Exit Criteria + 3계층 CI

> **이 문서 한 개가 최종 실행 지침이다.** `prompts/QualityOps_AI_CODEX_MASTER_R0_G10_FINAL.md`에 둔다.
>
> **요구사항 Source of Truth:** 루트의 `QualityOps_AI_FINAL_REQUIREMENTS_v5_5_MONOREPO_FINAL.md`.
>
> **최근 검토 커밋:** `58d316a`(2026-10-29 KST G8). 착수 시 반드시 실제 최신 HEAD 확인. 현재 HEAD를 가정하고 무조건 기존 단계를 재실행하지 않는다.
>
> **금지:** G0~G8 재구현/삭제, 기존 테스트 삭제·완화, 새 벡터 DB·멀티 에이전트·공정 데이터 실연동 추가, 권한·감사 약화, 무근거 LIVE/ROI 주장, `git push --force`.

## 0. Codex에 보낼 MASTER 명령 — 그대로 복사

```text
You are continuing the EXISTING homilpat/meta_Hackathon repository,
not creating a new application. Read these in order:
1) QualityOps_AI_FINAL_REQUIREMENTS_v5_5_MONOREPO_FINAL.md
2) prompts/QualityOps_AI_CODEX_MASTER_R0_G10_FINAL.md
3) docs/V5_IMPLEMENTATION_STATUS.md (or its moved canonical path),
   HACKATHON_WORK_LOG.md, README.md, SECURITY.md, existing code and tests.

First: inspect real HEAD, branch, remotes, uncommitted changes, directory
layout, baseline pytest, ruff, frontend build, Alembic and CI. Do not assume
that older path names or historical test results are current.

Run phases in order:
R0-A baseline/dependency audit;
R0-B backend/src + backend/tests move and packaging;
R0-C frontend/src + frontend/tests move and React modularization;
R0-D integration, static routing, Python scripts, docs and 3-area CI;
R0-E full baseline parity, regression and R0 acceptance;
A G8 focused fixes only;
B G9 human docs versioned editing and validation;
C post-G9 integration audit;
D G10 verified DOCX/PDF and synthetic E2E;
E Meta LIVE (only if legal credentials present; independently gated);
F final stabilization.

MANDATORY dependency-aware execution gate:
Before each phase, declare prerequisite status and a verifiable exit checklist.
A phase is PASS only if its mandatory criteria were actually executed and
passed; distinguish BUILT(code exists), PASS, PARTIAL, BLOCKED, NOT_RUN.
Independent tasks can run in parallel, but downstream dependent ACCEPTANCE
may NOT pass until upstream gates pass. P0 access/approval/egress/audit/data
issues hard-block affected paths. Missing Meta credentials block ONLY LIVE.

R0 must preserve all G0-G8/PREFLIGHT behavior, API contracts, DB migration
history, approval/policy/template/evidence hash semantics, meta tool schemas,
Experience Memory semantics, front-end behavior, D0-D8 state transitions,
and hash-chained audit logs. Move code and tests carefully. Replace old
root app/web/tests/scripts/migrations layout with frontend and backend
apps; docs and requirements stay at repo root per spec.

At each phase: run relevant positive, negative and regression tests, full
pytest where feasible, Ruff, Alembic fresh scratch DB and safe migration
checks, frontend typecheck/build and real UI/API smoke as applicable.
Use only scratch databases for migration/replay testing, NEVER the known
schema-inconsistent old qualityops.db. Log exact commands, exit statuses,
counts and errors. Fix regressions rather than weakening assertions.

Build GitHub Actions Backend CI, Frontend CI and Integration CI with verifiable
same-SHA dependencies (e.g. reusable workflows + top-level needs). Do not
pretend independent workflows have cross-workflow 'needs'. Do not claim CI
success unless run evidence is available.

On PASS: update docs, commit small tested changes, non-force push to the
verified intended branch if authorized, report SHA and CI status. On failure:
PARTIAL/BLOCKED with reproducer, blocker and next feasible independent work.
Never execute a submission, delete user data or expose secrets.
```

---

## 1. 공통 Dependency-aware Execution Gate

### 1.1 Phase DAG

```text
CURRENT HEAD + baseline parity
      │
      ▼
R0-A Architecture and test baseline
  ├──────────────┬───────────────────────────┐
  ▼              ▼                           │
R0-B backend     R0-C frontend               │
  └──────────────┴──────────────┐            │
                               ▼            │
                      R0-D integration/CI    │
                               ▼            │
                      R0-E full parity = R0 PASS
                               │
                               ▼
                         A G8 targeted audit
                               ▼
                         B G9 Docs PASS
                               ▼
                         C post-G9 audit PASS
                               ▼
                         D G10 export/demo PASS
                               ▼
                         F stabilization

E Meta LIVE is independent and credential-gated. LIVE demo claims need E PASS.
```

**Hard gate:** 뒤 단계의 승인본/배포용 인수 상태를 PASS로 선언할 때 필요한 선행 결과가 실제 PASS여야 한다. **Soft gate:** 영향을 받지 않는 UI 골격, 데모 문서, 모델 도구 스모크 준비는 별도 수행 가능. **External gate:** `MODEL_API_KEY`가 없으면 E=`BLOCKED_NO_CREDENTIALS`, 오프라인 개발과 테스트 지속.

### 1.2 상태 정의

- `BUILT`: 구현 파일/테스트가 존재(실행 확인을 의미하지 않음).
- `PASS`: 단계의 필수 Exit Criteria가 최신 HEAD에서 실제 성공.
- `PARTIAL`: 일부 구현 또는 테스트 실패·미실행으로 완료 불가.
- `BLOCKED`: 선행 게이트/P0/외부 조건으로 필수 작업 진행 불가.
- `BLOCKED_NO_CREDENTIALS`: Meta LIVE만. 다른 단계에 전염 금지.
- `NOT_STARTED` / `NOT_RUN`: 수행하지 않았거나 증거 없음.

**완료 기준은 실행 전에 선언하고, 모든 항목에 `PASS/FAIL/NOT_RUN`과 증거를 붙여야 한다.** 변경 없고 관련 없는 검사는 `NOT_APPLICABLE`로 근거와 함께 구분 가능하지만 필수 테스트를 생략하는 핑계로 사용하지 않는다.

### 1.3 공통 Exit Criteria

- [ ] 실제 HEAD·branch·dirty tree·원격·CI 상태 확인.
- [ ] 해당 단계 정상·부정·회귀 테스트 수행; 테스트 삭제/완화 없음.
- [ ] Backend pytest 전체 및 Ruff 실행; 정확한 passed/failed/warnings 기록.
- [ ] Alembic migration graph와 fresh scratch DB upgrade + drift 검사; 변경된 경우 유효 DB 백업 사본으로 upgrade 검증.
- [ ] Frontend build/typecheck; 변경한 경우 UI smoke/렌더/API 호출 검증.
- [ ] API HTTP와 승인·권한·감사·비밀정보 유출/egress 회귀 확인.
- [ ] 실제 결과·미수행 사항·한계를 구현 상태 및 작업 로그에 기록.
- [ ] PASS인 커밋의 SHA, non-force push, CI 성공 여부 또는 `NOT_VERIFIED` 기록.

---

## 2. R0 — 모노레포 이전 및 실제 모듈화 (G9 전에 수행)

### R0-A — 의존성 및 기준선 인벤토리

실제 `app/`, `web/`, `tests/`, `migrations/`, `scripts/`, `docs/`와 Python imports, `create_app`, package configuration, Vite proxy, React build, static bundle, `/app`/`/ui`, DB paths, CI triggers, 문서 상대 링크를 조사한다. 과거 R0 프롬프트보다 최신 코드가 우선이다. 기존 커밋/브랜치 변경 사항은 건드리지 않는다.

**Exit:** 전체 파일 매핑(`old -> new`), 변경 전 테스트·build·migration 기준선, 공개 API·DB·설치·정적 출력 계약 목록, 작업 단위/롤백 지점 마련. `docs/architecture/REFACTOR_AUDIT.md`에 기록. 하나라도 없으면 R0-B/C의 위험한 대규모 변경을 금지.

### R0-B — Backend `src/tests` 분리

- 기존 `app/` → `backend/src/app/`; `tests/`의 Python 테스트 → `backend/tests/`.
- `scripts/` → `backend/scripts/`; `migrations/` → `backend/migrations/`.
- Python 패키지 메타데이터·설치 설정 → `backend/pyproject.toml`, Alembic 설정 → `backend/alembic.ini`.
- 기존 `app` 패키지명과 SQLAlchemy 테이블/모델/마이그레이션 ID를 **유지**. src layout import를 실제 설치로 검증한다.
- `app.main:app`, `create_app`, Python `-m scripts...`, 스크립트 경로와 DB URL을 새 root에서 동작하도록 수정.
- `db.py`를 단순히 크다는 이유로 쪼개지 않는다. `main/workflow/eightd`는 이미 별도 도메인으로 나뉜 로직과 중복하지 않도록 최소 분리한다.

**Exit:** `backend`에서 editable install, 모든 Python imports/pytest/ruff 통과, scratch Alembic 업그레이드·drift 0, 기존 `/health` + 주요 HTTP 응답 동일, 정책/검증/감사/Experience Memory/Meta TEST_DOUBLE 계약 유지.

### R0-C — Frontend `src/tests` 분리 및 화면 모듈화

- 기존 `web/` → `frontend/`로 이동하고 `frontend/src`, `frontend/tests`를 사용한다.
- `App.tsx`를 실제 화면 단위 `features/dashboard`, `eightd`, `evidence`, `spc`, `experience`, `investigation`, `documents`, `audit` 등으로 나눈다. 공통 `components`, `api/client`, `types`, 필요한 `hooks`에 공유 코드를 정리한다.
- 디자이너 의도·동작·URL·사용자 역할·표시 데이터·응답 해석을 바꾸지 않는다. 신규 API 계약·디자인 시스템 교체·무의미한 계층 추가 금지.
- 기존 frontend 테스트 도구가 없으면 **의미 있는 최소 테스트 도구/런너만** 택하고 실제 렌더/화면 전환/API 실패 회귀 케이스를 마련한다. 테스트 없음인데 `npm test` 성공으로 주장하면 안 된다.

**Exit:** React/TypeScript 검사, Vite production build, 사용자·사건 전환, 주요 화면 smoke, API 요청, 기본 정상/실패 렌더 테스트 통과. 새 파일의 import 및 코드 스플리팅 결과 정상.

### R0-D — Frontend–Backend 통합, docs 경로 및 3영역 CI

- Frontend `dist`가 실제 FastAPI에서 `/app`으로 제공되는 경로를 보존. `/ui` 구형 fallback 유지. 정적 빌드 산출물의 추적·배포 정책은 기존 repo와 CI를 검사한 뒤 결정.
- Vite proxy, 앱 base path, CORS 여부, 파일 다운로드, env vars, DB 상대 경로, Python script CWD, backend packaging 파일 포함 여부 확인.
- 루트 요구사항 명세서 유지; 개발용 이 프롬프트는 `prompts/`; `docs/` 세부 문서를 architecture/testing/implementation/evaluations로 논리 정리하되 **과거 기록을 삭제하지 않는다**. 링크/상대경로 일괄 검증.
- GitHub Actions: `backend-ci.yml`(Python 3.12, full pytest, ruff, alembic, HTTP), `frontend-ci.yml`(Node `npm ci`, typecheck, build, 실제 frontend tests), `integration-ci.yml`(새 scratch DB + 전체 API/React/experience/audit/E2E), `ci.yml`(동일 커밋 backend/frontend 성공 후 integration 실행). workflow_call/`needs` 사용 또는 동등 검증 가능한 DAG.
- 백엔드만 수정한 PR에서도 통합 판정이 누락되지 않도록 path filter의 비우회성을 검증한다. 실모델 API 키 없는 환경은 MOCK 성공을 LIVE로 표기하지 않는다.

**Exit:** 실제 `/app`·`/ui`·API HTTP, 개발 proxy, CI 각 영역, 통합 의존성이 통과. README 개발/테스트 명령이 최신 구조로 동작하고 문서 링크가 유효함.

### R0-E — 결과 동등성 검증 및 R0 완료

- 기준선 대비 이전 226개로 기록된 Python 테스트가 누락·완화 없이 현재 코드에서 실행되는지 검증한다(과거 개수와 달라도 변경 이유를 기록). 신규 프론트 테스트 실제 실행 확인.
- src layout, 정확한 import/module path, 설치/빌드, migration graph, `/app` static, `/ui` legacy, 모든 핵심 API, SPC/D0-D8, validation, Experience Memory, 감사 해시 및 회귀 검증.
- 새 scratch DB에서 단일 정상 E2E와 필수 권한/원인/승인 차단 반례를 검증한다.
- 완전 동일 출력을 보장할 수 없는 비결정적 로그/시각만 예외 사유를 기록; 실질 상태·정책 판정은 동일해야 한다.
- 버그가 생기면 **해당 변경만 수정/롤백**, 사용자 작업 전부 되돌리거나 Git 강제 푸시하지 않는다.

**R0 Exit — 모두 필수:** `frontend/src/tests`, `backend/src/tests`에 실질 코드가 있고, 모든 import/패키지/DB/스크립트/CI/문서 경로가 정상, 백엔드·프론트·통합 테스트 성공, 이전 API·승인·증거·감사·Meta TEST_DOUBLE 결과 회귀 없음, docs 감사 작성, 최종 커밋/푸시/CI 확인. 실패하면 R0 `PARTIAL/BLOCKED`, G9 **최종 인수 검증** 허용 금지.

---

## 3. A — G8 집중 감사 및 꼭 필요한 보완

**선행 조건:** 실제 HEAD에서 G8 관련 코드·마이그레이션·테스트 존재 확인. `backend/src/app/experience.py`, `backend/src/app/factcheck.py`, `backend/src/app/validation.py`, `backend/src/app/taskrouter.py`, `backend/src/app/investigator.py`, `backend/src/app/tools.py`를 먼저 읽는다.

**작업 내용 (기능 확장 금지):**

1. 기존 Experience Memory의 `KNOWN` / `ANALOGICAL` / `NO_RELEVANT_HISTORY` 동작 유지.
2. D8 종결 사례의 효과 검증 성공과 재발 관찰 상태를 별도 표시. 현재 `NOT_YET_OBSERVED`는 `NONE`으로 간주하지 않는다. 재발 관찰이 끝나지 않은 성공 사례도 *효과 검증 참고 사례*로 검색할 수 있어야 한다. 검증되지 않은 무재발을 근거로 `KNOWN`을 부여하지 않는다.
3. 과거 실패·불충분·재발 조치를 검증된 해결책으로 우선 추천하지 않는다. 현재 설비·공정·LOT 조건이 다르면 필수 확인 사항을 보여준다.
4. 추천 이후 사람의 `REVIEW_PRIOR_RESPONSE` / `INVESTIGATE_MORE` / `CONSIDER_ALTERNATIVE` 선택을 감사 기록에 남기되 D4 원인 확정, D5 승인·실행을 자동 수행하지 않는다.
5. `backend/src/app/factcheck.py`: 한 문장에 올바른 숫자와 잘못된 숫자가 섞여 있을 때의 `TEXT_VALUE_MISMATCH` 허점 여부를 **실패 재현 테스트부터 작성**한다. LOT 혼합, 복수 단위, 증거 대체, 잘못된 실행·원인 주장도 반례 추가. 반례가 재현되는 경우에만 최소 수정. 올바른 수치·반올림을 과차단하지 않는다.
6. G8의 문서 검색/TemplateContract가 권한·사이트·고객·적용 기간으로 **검색 이전**에 필터링되는지 확인.
7. BM25+용어 매핑의 한계를 문서화하되, 별도 임베딩/벡터 DB 구축은 하지 않는다.

**A Exit Criteria — 모두 충족해야 PASS:**

- [ ] 기존 `KNOWN` 추천, 다른 조건의 `ANALOGICAL`, 무관 사건의 `NO_RELEVANT_HISTORY`가 각각 테스트됨.
- [ ] `NOT_YET_OBSERVED`가 `NONE`으로 잘못 표시·승격되지 않으며, 축적된 종결 사건을 다음 사건에서 검색할 수 있음.
- [ ] 실패·재발 사례는 경고로만 제공되고 자동 적용/승인되지 않음.
- [ ] 인간 결정과 추천 취소·만료 기록이 감사 로그에 남음.
- [ ] 수치·LOT·단위·문서 최신성·출처 변경의 정상/오류 반례 테스트 통과.
- [ ] 기존 모든 테스트, Ruff, 마이그레이션, 해당 HTTP smoke 통과.

**Unlock:** A=PASS → B G9의 수정·재검증 통합 허용. A가 실패하면 Docs UI 골격 작업은 가능하지만 검증·승인 완료로 표시 금지.

---

## 4. B — G9 Human Docs Workspace 구현

**선행 조건:** A=PASS, 기존 문서·Claim·검증·승인 저장 구조 검토. 재사용 대상: `DocumentVersion`, `DocumentClaim`, `ValidationRun`, `ApprovalEvent`, 정책 게이트 및 해시 감사.

**구현 요구:**

- D2/D3/D4 기반 문서 및 D5~D8 관련 사용자 문서 내용을 기존 UI에서 조회·편집. 실제 저장 모델이 다른 단계는 동일한 통합 문서 버전 계약으로 렌더링하되 **새로운 승인 소스를 이중 생성하지 않는다**.
- 문장·값·분모·단위·Claim·Evidence 링크 수정, 편집 전후 Diff, 사유, 수정자, 저장 시각.
- Draft 편집은 **새 버전**. 승인본은 읽기 전용 스냅샷으로 보존. 원본 제조 DB와 문서 초안 수정은 분리.
- 수동 편집 또는 AI 수정 제안 수락 후 `factcheck.validate` + `TemplateContract` + evidence/source/policy/template/rules version 재검증. `PASS/WARN/BLOCK` 사유 화면 표시. WARN 승인 가능 여부는 기존 정책에 따름.
- AI 수정은 제안 Diff 형태로 반환. 사용자가 수락 전 DB/문서 자동 변경 금지. API 키 없으면 수동 편집·검증은 정상 작동, AI 제안 기능만 명시적 OFFLINE.
- 저장·승인에 optimistic concurrency (`If-Match`/expected version 또는 동등한 해시) 사용. 충돌·스테일 검증·승인 해시 불일치·새 정책은 적절한 `409/403`.
- 모든 검증·승인은 **같은 문서 버전 및 동일 source/evidence/policy/template/rules 스냅샷**에 귀속. 원본 변경은 과거 승인본을 덮어쓰지 않고 후속 경로를 재검증 대상으로 표시.
- 역할/사건 접근·작성자/승인자 분리·append-only 감사·idempotency 회귀 유지.

**B Exit Criteria:**

- [ ] 작성자가 문서 수정 → 새 버전 저장 → API/React에 변경 내용과 Diff 표시.
- [ ] 이미 승인된 이전 버전 및 감사 해시는 변경되지 않음.
- [ ] 잘못된 수치·LOT·근거 또는 미실행 조치의 사실 주장 편집 시 BLOCK; 정상 문장 PASS.
- [ ] 승인 직전 근거·정책·양식이 바뀌면 예전 검증 결과의 승인 재사용 불가.
- [ ] 동시 편집/편집 중 검토/스테일 승인에 대한 409 또는 적절한 정책 거부.
- [ ] AI 제안은 실제 수락 전 미적용; 수락 후 재검증; no-key 수동 경로는 PASS.
- [ ] 권한·자기 승인·사건 범위·감사 로그 정상 및 반례 테스트 통과.
- [ ] 새 migration의 fresh upgrade·compatibility와 전체 테스트/Ruff/프론트 빌드/UI smoke 통과.

**Unlock:** B=PASS → C의 G9~G8 연결 통합 감사 및 D의 최종 스냅샷 기반 출력 **인수 검증** 가능.

---

## 5. C — POST-G9 통합 감사 (P0/P1만 우선 해결)

**선행 조건:** B=PASS.

**검증 범위:** 하나의 합성 사건에서 SPC→D0 triage→D1 team→D2 facts→D3 containment (planned/executed/independently verified)→D4 hypothesis/experiment/qualified cause→D5 cause-linked action selection→D6 execution + precommitted effectiveness→D7 SOP/FMEA revision/deployment/training→D8 verified closure. History 추천, 담당자 선택, Docs 편집·재검증, 출처 정정, 승인 이력, 사건 재개방까지 포함.

**추가 부정 테스트:**
- 통계 신호만으로 결함/원인 확정 금지, D0 긴급 조치의 합법적 예외 허용.
- 다른 사람/사이트/공정/고객 문서·사례 유출 차단.
- SHAP·과거 사례·Meta 제안만으로 D4 확정 차단.
- 계획만 있는 D3/D5를 실행 완료로 허위 표기 금지.
- D6 미실행·표본 부족·변경된 검사 조건·사후 조작한 기준으로 EFFECTIVE 금지.
- 최신 개정 없는 D7·미해결 조치 있는 D8 종결 금지.
- 승인/서명 중 소스·정책·템플릿 변경·동시 저장·취소된 과거 추천 처리.
- 외부 호출은 SYNTHETIC + 외부 전송 승인 데이터만, 비밀정보 egress 차단.

**C Exit Criteria:**

- [ ] **성공 E2E:** 합성 D0→D8 CLOSED + 이전 조치 참고 + 편집/재검증 + 감사 검증.
- [ ] **실패 E2E:** 부적합 원인/조치/증거 또는 D6 효과 실패 → 적절한 BLOCK/재진입.
- [ ] P0=0 미해결. 데모를 차단하는 P1=0 미해결(해결하지 못하면 C=PARTIAL).
- [ ] 승인 본문 해시·policy/template/evidence 버전 일관성 및 audit chain 무결성 검증.
- [ ] 전체 pytest/Ruff/migrations/frontend build/실제 HTTP E2E 통과.
- [ ] `docs/implementation/POST_G9_REFACTOR_PLAN.md`: 발견 내용, P0/P1 조치 및 P2 추후 항목, 실제 검증 결과 기록.

**Unlock:** C=PASS → D의 승인본 기반 최종 출력·전체 데모 인수 완료 가능. C 실패 시 독립 렌더러 개발은 가능하나 **최종 승인본 내보내기 검증 PASS 금지**.

---

## 6. D — G10 DOCX/PDF 출력 및 단일 대표 사건 데모

**선행 조건:** C=PASS(승인 스냅샷 기반 인수 검증). 독립적인 출력 템플릿/스타일 코드는 선행 작업 가능.

**구현:**

1. D0~D8 승인된 사건/문서 스냅샷·실행/효과·원인·근거·문서 개정·담당자 서명·감사 요약을 하나의 명확한 보고서 구조로 조립.
2. DOCX와 PDF **실제 파일을 생성**. 파일명, MIME, 다운로드 경로, 생성자·생성일·스냅샷 해시를 포함. 생성한 파일을 실제로 열어 유효성 확인.
3. 보고서 필수 필드 및 원본 스냅샷의 주요 값·단위·LOT·문서 버전·승인자·근거 ID와 **출력 결과의 일치**를 검증. 비승인 초안을 승인 보고서처럼 내보내지 않는다.
4. 기존 합성 SMT 사건 하나로 SPC→D0~D8→과거 사례 검색·사람 선택→D6 효과 검증→Docs 편집→종결→파일 출력→Experience Memory 등록을 재현 가능한 데모로 제공.
5. 잘못된 수치, 실패했던 해결책, 원인 미확정, 잘못된 승인, source revision 등 **실패 장면**도 1~2개 포함하되 추가 벤치마크는 만들지 않는다.
6. 데모를 새 scratch DB에서 반복 가능하게 하고, 브라우저 새로고침·오류 응답·서버 재기동 경로 검증.
7. README에 합성 데이터·시뮬레이션·Meta LIVE 여부·재현 명령을 명시.

**D Exit Criteria:**

- [ ] 승인한 동일 스냅샷에서 DOCX와 PDF 실물 생성, 파일 파싱·열기 성공.
- [ ] 핵심 수치·LOT·근거·D0~D8 상태·서명/해시·문서 개정이 출력물과 일치.
- [ ] 미승인/스테일/차단 문서를 최종 승인 출력물로 위장할 수 없음.
- [ ] 한 합성 사건의 전체 정상 E2E 반복 성공(새 DB, 재실행, URL/화면/다운로드 확인).
- [ ] 적어도 1개 부정 E2E에서 적절한 검증 차단, 감사 이력 보존.
- [ ] 전체 테스트/Ruff/migrations/프론트 빌드/HTTP·브라우저 동작 검증.
- [ ] UI/README/로그에 실측 ROI나 실공장 성과를 허위로 주장하지 않음.

**Unlock:** D=PASS → 최종 데모 패키지(오프라인 결정론적 기능) 인수 가능. Meta LIVE 관련 주장은 E=PASS를 별도로 요구.

---

## 7. E — Meta LIVE 조건부 검증 (독립 분기)

**선행 조건:** 합법적인 `MODEL_API_KEY`가 실제 실행 환경에 존재하고, egress 정책과 synthetic 허용 데이터가 준비됨. 설정되지 않은 경우 이 단계는 `BLOCKED_NO_CREDENTIALS`; A~D 개발/검증 계속 가능. 테스트 더블은 LIVE의 대체 합격 근거가 아니다.

**실행:**

- 기존 `scripts.meta_smoke` 및 `scripts.meta_investigate_smoke`로 실제 model/provider 호환성과 Tool Calling 계약 확인.
- LIVE로 `get_evidence_gaps`, `search_experience`, `search_documents` 등 허용된 read-only 도구 선택·인자·결과 처리 확인.
- 현재 사건/과거 사례 적용 조건의 비교, 실패 사례 경고, 추가 증거 요청, 한계/UNKNOWN 표현 확인.
- 모델 응답 JSON·schema·tool IDs·권한·egress·timeout·rate limit·token usage·지연과 실패 복구 확인.
- 검증 실패/에러는 `LIVE_FAILED`, 사용 가능한 실제 검증이 없으면 `NOT_VERIFIED`로 표시. key 노출 금지.

**E Exit Criteria:**

- [ ] 제공자 응답이 실제 LIVE API에서 성공하며 모델·요청/응답 시각을 기록(키 저장 금지).
- [ ] 적어도 1회 **실제 LIVE** read-only tool call 수행, 실행/결과 검증 및 호출 추적 기록.
- [ ] 올바른 모델 JSON/구조화 조사 결과가 서버 검증을 통과하거나 실패 원인과 한계를 정직하게 기록.
- [ ] 도구/서버 정책이 잘못된 접근·승인·실행을 차단함.
- [ ] 전체 Meta LIVE 로그에서 `TEST_DOUBLE`과 `LIVE`가 구별됨.

**중요:** 실제 API 호출은 시도했지만 최종 보고서가 검증 실패라면 **E=PARTIAL**이지 PASS가 아니다. `MODEL_API_KEY` 없음은 **E=BLOCKED_NO_CREDENTIALS**. **전체 시스템 PASS와 Meta LIVE PASS를 별도로 보고한다.**

---

## 8. F — 최종 안정화 및 인수

**선행 조건:** D=PASS. E는 별도 등급: LIVE 시연 제출이면 E=PASS 필수, 오프라인 결정론적 데모에는 E 미완료를 명시.

**F Exit Criteria:**

- [ ] 완료된 기능/부분 구현/차단 기능을 `BUILT / PARTIAL / BLOCKED / NOT_DONE`으로 최신화.
- [ ] `README.md`, `SECURITY.md`, `HACKATHON_WORK_LOG.md`, `docs/implementation/V5_IMPLEMENTATION_STATUS.md`, `docs/evaluations/META_LIVE_LOG.md`를 실제 결과에 맞게 최신화.
- [ ] pytest, Ruff, Alembic fresh+safe upgrade, 프론트 빌드, HTTP/브라우저 E2E 전체 재실행 기록.
- [ ] Meta 경로·도구 호출·Data egress·조치 승인·감사 체인이 회귀하지 않음.
- [ ] 단일 사건 재현 안내, 실패 사례 1개, DOCX/PDF 검증, 초기화 방법과 데모 사용자 역할이 명확함.
- [ ] 재현 불가능하거나 미검증된 성과·수상 가능성·ROI 수치를 주장하지 않음.
- [ ] 작업이 완료된 경우 최종 커밋 SHA, 푸시/CI 상태, 잔여 리스크 및 차단 항목 보고.

**최종 상태는 분리하여 보고:**

```text
BACKEND_WORKFLOW: PASS | PARTIAL | BLOCKED
G8_RELIABILITY: PASS | PARTIAL | BLOCKED
G9_DOCS: PASS | PARTIAL | BLOCKED
POST_G9_INTEGRATION: PASS | PARTIAL | BLOCKED
G10_EXPORT_DEMO: PASS | PARTIAL | BLOCKED
META_LIVE: PASS | PARTIAL | BLOCKED_NO_CREDENTIALS | NOT_VERIFIED
SECURITY_LIMITS: [demo X-User only, synthetic data, no real deployment claim...]
DEMO_READY: YES | NO (with reason)
SUBMISSION_READY: YES | NO (with reason, submission itself NOT performed)
```

---

## 9. 최종 실행 명령 / CI 점검 (R0 이후 새 구조 기준)

```bash
# repository root; first inspect actual package scripts and config.
cd backend
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check .
# NOTE: before Alembic commands, configure an isolated scratch DATABASE_URL.
python -m alembic upgrade head
python -m alembic check
python -m scripts.meta_smoke             # only with lawful credentials; exit 2 = not run
python -m scripts.meta_investigate_smoke  # only with lawful credentials
cd ../frontend
npm ci
npm run build
# run a real frontend test command only when package.json declares it;
# otherwise configure the minimal fitting test runner in R0-C, then run it.
```

**중요:** 위 명령의 DB URL, 설치 옵션, 프론트 스크립트 이름은 **실제 R0 결과**로 확인한 뒤 적용한다. 기존 `qualityops.db` 파일은 스키마 불일치 기록이 있어 직접 변경·테스트하지 않는다. Python 모듈은 `backend`에서 실행한다. 새 경로를 쓰지 않고 루트에서 옛 `pytest`만 통과한 결과로 R0를 PASS로 선언하지 않는다.

**GitHub Actions:** 다음을 증명한다: `backend-ci` 성공, `frontend-ci` 성공, 해당 SHA의 `integration-ci` 성공, 통합 job의 `needs`가 upstream 성공을 요구, 단일 실행에 결합된 경로가 `main` 및 PR에서 작동. 수동 스크립트가 성공해도 CI 상태 미조회면 `CI_NOT_VERIFIED`.

## 10. 검증 사례 — 반드시 결과를 남길 시나리오

| ID | 검증 시나리오 | 기대 결과 | 주 단계 |
|---|---|---|---|
| TC-R0-01 | 백엔드 import/packaging/health after move | 동일 계약 | R0 |
| TC-R0-02 | frontend Vite proxy + `/app` + `/ui` | 성공 | R0 |
| TC-R0-03 | backend/frontend CI 실패했을 때 integration gate | integration 완료 선언 차단 | R0 |
| TC-R0-04 | 새 scratch DB migration, old DB 보호 | 성공·원본 불변 | R0 |
| TC-A-01 | closed case 재검색, 재발 `NOT_YET_OBSERVED` | 검색됨/KNOWN 무근거 승격 금지 | A |
| TC-A-02 | 과거 실패·재발 조치 선택 | 추천 성공 사례 금지·감사 | A |
| TC-A-03 | 한 문장에 맞는 수치와 틀린 수치 혼합 | 수치 불일치 탐지 | A |
| TC-B-01 | Docs 수정 후 새 버전 + diff + 재검증 | 이전 승인본 불변 | B |
| TC-B-02 | 3.2%→2.1%, 다른 LOT 증거, 원인 확정 거짓 | BLOCK | B |
| TC-B-03 | 동시 편집/검토 중 원본 정정/정책 변경 | 적절한 거부, 감사 무결성 | B |
| TC-B-04 | no-key AI proposal + 수동 편집 | AI OFFLINE, 수동 PASS | B |
| TC-C-01 | 성공 경로 D0→D8 + 경험 선택 + 문서 편집 | CLOSED + audit verify | C |
| TC-C-02 | D6 효과 실패/미실행·D8 조기 종결 | 차단·재조사 | C |
| TC-D-01 | 승인 snapshot DOCX/PDF 생성·파일 열기 | 동일 LOT/수치/버전/승인자 | D |
| TC-D-02 | 미승인/스테일 문서 최종 출력 | 차단 또는 명확한 DRAFT 분리 | D |
| TC-E-01 | Meta LIVE 실제 도구 1회 이상 사용 | LIVE 호출·검증·기록 | E |
| TC-F-01 | fresh DB 최종 시연 2회 | 재현 가능한 결과 | F |

위 표는 **추가 필수 수용 사례**를 요약한 것이며 기존 8D 요구사항 §9의 20개 수용 반례와 기존 테스트를 대체하지 않는다. 코드와 테스트 파일명/실행 커맨드/실패 원인을 `docs/testing/REQUIREMENT_TEST_TRACEABILITY.md`에 기록한다.

## 11. 단계 종료 보고 형식 (매 단계 동일)

```text
PHASE: R0-A / R0-B / R0-C / R0-D / R0-E / A / B / C / D / E / F
HEAD_BEFORE: <sha>
DEPENDENCIES: <phase + PASS/PARTIAL/BLOCKED status>
EXIT_CRITERIA:
  - <ID>: PASS / FAIL / NOT_RUN (actual command + observed evidence)
STATUS: PASS / PARTIAL / BLOCKED / BLOCKED_NO_CREDENTIALS
CHANGED_FILES: <path and purpose>
MIGRATIONS: <revision IDs, scratch result, data safety>
TESTS: <pytest actual counts, Ruff exit, frontend actual tests/build, HTTP/UI/E2E>
CONTRACT_PARITY: <API, DB, policy, evidence, tool calling, audit>
CI: <same SHA backend/frontend/integration, PASS or NOT_VERIFIED>
COMMIT_PUSH: <SHA, branch, pushed or not, no force push>
UNLOCKED_NEXT: <only truly eligible downstream work>
BLOCKED_DEPENDENCIES: <what cannot be marked PASS>
RISKS: <P0/P1/P2, reproducer, mitigation>
```

### 종료 규칙

**R0를 완료하지 못한 채 G9 인수를 진행하지 않는다. G9·통합 감사가 미완료면 G10 승인본 출력을 완료로 표시하지 않는다. Meta LIVE 미검증은 별도 명시하고 TEST_DOUBLE로 대체 주장하지 않는다.** 모든 변경에서 신뢰 가능한 실제 실행 증거를 남긴다.


---

## 12. NEW — AG0~AG5 Agent-First UX 전환 실행 명령 (기존 R0~G10 이후, 신규 작업)

> 반드시 루트 요구사항 \`QualityOps_AI_FINAL_REQUIREMENTS_v5_5_MONOREPO_FINAL.md\` **§22**를 최신 추가 계약으로 읽는다. 이전 단계의 수행 기록·Gate·테스트는 재작성/삭제하지 않는다. Figma 지시문: \`prompts/FIGMA_MAKE_AGENT_FIRST_UI.md\`. **본 장은 개발 명령이며 구현 완료 기록이 아니다.**

### 12.1 Codex에게 보내는 실행 지시
\`\`\`text
You are implementing AGENT-FIRST UX (AG0 -> AG5) on homilpat/meta_Hackathon.
Read the root v5.5 MONOREPO FINAL specification including §22, the current master prompt,
README, V5_IMPLEMENTATION_STATUS, traceability and latest GitHub CI, and inspect actual code.
GOAL: show users one primary QualityOps AI Agent, while preserving all G0-G10 functionality,
the same API/domain semantics, same human approvals, validated evidence, full audit trail,
and independently accessible My Tasks / Department Tasks / approval and manual fallback UI.
Do NOT merge backend feature modules into one LLM prompt. Do NOT replace validators, workflow
gates, role enforcement, document versioning, or export conditions. Do NOT invent new approval
semantics or let the model directly modify DB records. Do NOT claim Meta LIVE success without
a successful validated external tool call.

Implement incrementally AG0 then AG1 then AG2 then AG3 then AG4 then AG5; stop for genuine
blocking dependencies, but proceed with independently testable work. Each phase must include
tests, observed evidence, limitations, commit SHA and CI. Prefer narrowly scoped refactors.
Keep existing frontend feature components and /queue?scope=mine|department; add a primary
Agent screen and reusable inline evidence/chart/D0-D8/approval/diff/export cards.
Reuse backend tools and endpoints, enforcing server-side access control and state transitions.
The agent is an orchestrator, not a privileged actor. Respect authorization and idempotency.
Pause at NEEDS_HUMAN; never auto-approve, fake action execution, confirm untested causes,
or close cases without all required conditions.
Use a read-only tool allowlist first. Add write workflows only after passing security tests.
Report per-phase: baseline SHA, dependency state, files changed, endpoint contracts, migrations,
unit/UI/HTTP E2E, negative tests, model/provider mode, CI status and remaining risks.
Do not mark tests PASS unless run. Do not redesign unrelated visual styles or delete old features.
\`\`\`

### 12.2 Phase DAG
\`\`\`text
Existing R0 / G0-G10 preserved & baseline verified
  └─ AG0 contract inventory / tests / baseline
       └─ AG1 Agent shell + Queue navigation + UI fallback
            └─ AG2 read-only tools + evidence cards
                 └─ AG3 safe writes, approvals, resumable tasks
                      └─ AG4 G9/G10 + parity E2E
                           └─ AG5 usability + regression + release evidence
Meta LIVE verification: independent credential-gated track, never simulated as LIVE
\`\`\`

### 12.3 Detailed execution / exit criteria
| Phase | Implement | Explicit exit criteria |
|---|---|---|
| AG0 | inspect repo and collect OpenAPI/role/route/test baseline; draw tool safety matrix read/write/human-only | current SHA/CI + full baseline tests + protected contracts documented; no feature code regression |
| AG1 | primary Agent UI, current Case/role context, online badge, chat timeline, task list links, manual screen fallback, responsive components | frontend typecheck/vitest/build, Queue existing tests and navigation, no broken static bundle |
| AG2 | server intent parser and read-only tool registry using existing adapters; render evidence/lot/version/SPC/RAG/ML/queue cards | ACL/LOT correctness, unsupported-cause guard, prompt-injection guard, deterministic offline contract tests; no new mutations |
| AG3 | allowlisted write tools, typed confirmation cards, human review workflow, pause/resume/revalidate, idempotency | unauthorized approval/false execution/stale hash/duplicate retries blocked; persisted task survives refresh and role switch; audit intact |
| AG4 | document editor/diff/validation/export from chat; same underlying endpoints as old UI; dual-route comparison | D0→D8 success and D6 failure via real HTTP; exported snapshot and audit matches old UI; full legacy regression |
| AG5 | compare user action count/time/errors; keyboard/mobile/error/Meta unavailable states; repeated fresh DB E2E, latest CI | documented measured results and risks; backend/frontend/integration jobs successful at same SHA; no fabricated LIVE pass |

### 12.4 Implementation boundaries
- Frontend reuse \`frontend/src/App.tsx\`, \`frontend/src/features/queue/Queue.tsx\`, \`frontend/src/features/eightd/EightD.tsx\`, \`frontend/src/features/documents/DocEditor.tsx\`, \`frontend/src/api/client.ts\`. New directory \`frontend/src/features/agent/\` is suggested, not mandatory. Preserve React feature boundaries, no monolithic App.tsx rewrite.
- Backend reuse \`backend/src/app/taskrouter.py\`, \`tools.py\`, \`investigator.py\`, \`workflow.py\`, \`validation.py\`, \`factcheck.py\`, \`experience.py\`, \`export.py\`; server API adapter/allowlist preferred over direct database access. New \`agent/\` package only if justified.
- Show server origin, effective version/hash/role, validation state and provenance per result card. Approval card must use real permission checks; never just change frontend state to 'approved'.
- Do not create speculative endpoint names as if they already exist; enumerate actual routes and add only missing capabilities, with API tests and migration as needed.
- Reuse real CI workflow and same SHA: backend, frontend, integration. New test names should be added to \`docs/testing/REQUIREMENT_TEST_TRACEABILITY.md\` after they actually exist.
- Existing spec §9 and §20.4 failure/stop rules remain binding.

### 12.5 New acceptance cases
AG-T01 wrong Case/LOT → clarify; AG-T02 bypass role/approval → 403/409;
AG-T03 D6 ineffective → D4 reopened; AG-T04 unsupported number/source → BLOCK;
AG-T05 stale version → blocked; AG-T06 retrieved prompt injection → treated as data;
AG-T07 model outage → Queue/manual workflow usable; AG-T08 refresh → persisted task;
AG-T09 duplicate retries → once-only mutation; AG-T10 prior UI vs Agent parity;
AG-T11 exported approved file vs draft denial; AG-T12 role switch no cross-user task leak.

### 12.6 Per-phase report template
\`\`\`text
PHASE: AG0 / AG1 / AG2 / AG3 / AG4 / AG5
BASE_SHA / HEAD_SHA:
DEPENDENCY_GATE:
CHANGED_FILES:
FUNCTIONAL_PARITY:
AUTOMATION_VS_HUMAN_BOUNDARY:
TESTS_RUN: (actual commands/results/counts)
SECURITY_NEGATIVE_TESTS:
REAL_HTTP_E2E:
FRONTEND_BUILD / BUNDLE_PARITY:
META: LIVE_VERIFIED / TEST_DOUBLE / BLOCKED_NO_CREDENTIALS
CI: exact run URL / PASS / CI_NOT_VERIFIED
RISKS / BLOCKERS:
EXIT: PASS / PARTIAL / BLOCKED / NOT_RUN
NEXT_UNLOCKED:
\`\`\`
