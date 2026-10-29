# Figma Make — QualityOps AI Agent-First UX (UI generation prompt)

## Copy/paste into Figma Make

Design and implement a production-quality, responsive **Agent-First QualityOps AI** web app UI. This is a UI redesign of an EXISTING quality management application, not a new feature set. Keep existing operations, backend APIs, evidence logic, approvals and security untouched. The visible primary experience is one conversational QualityOps AI Agent; retain independent "내 할 일", "부서 할 일", "승인 대기", "작업 이력" and manual detail workflows as essential work surfaces.

**Language:** Korean labels, clear industrial/professional SaaS tone. Do not imitate generic AI chat branding. Use an understated neutral/light palette with clear state colors and accessible contrast; consistent spacing, typography, keyboard navigation and responsive mobile layout. Do not redesign business terminology, invent measurements, or show fictional success as real data. Build using reusable React-friendly components, real data props and loading/empty/error variants. Mock data only in explicitly labeled "디자인 예시" preview, never mix it with live data.

**Navigation:** desktop left sidebar: [AI Agent (default)], [내 할 일], [부서 할 일], [승인 대기], [사건 진행 현황], [작업 이력]. Utility links to detailed SPC/data, 8D, Docs edit/Diff, Audit remain available via context actions/fallback instead of becoming the main user flow. Persistent header: Case selector, process/LOT context, demo user/role selector, SYNTHETIC DATA label, Meta provider status (LIVE VERIFIED / KEY SET BUT UNVERIFIED / NO KEY / TEST_DOUBLE accurately), notification/pending tasks badge.

**Agent workspace:** central conversation; compact context header for Case ID, LOT/process, D0-D8 stage and blocking state. Chat composer with example intents: "L02 이상 신호 분석해줘", "현재 확인할 근거를 보여줘", "8D 보고서 초안 작성해줘", "내 할 일 알려줘", "승인 대기 문서 확인해줘". The agent replies with actual source-bound structured cards rather than prose alone. Display step-by-step orchestration progress with visible tool names/status, pending human actions, clear reason for stop and resumption.

**Inline component library:**
1. Evidence table with evidence IDs, LOT, timestamp, source revision, calculated vs observed, source link.
2. SPC X-bar/R or trend chart, signal/limits, explicit "statistical signal ≠ confirmed defect".
3. ML/SHAP/Experience cards, source references, failed precedents clearly marked, AI hypothesis ≠ established cause.
4. 8D stepper D0-D8 with unmet prerequisites and server gate reasons, not merely a decorative progress bar.
5. Human approval/request card: document version/hash, approver role, summary, evidence links, valid Approve/Reject only when server reports permission. No fake auto-approval.
6. Docs editor and diff drawer showing proposed vs accepted changes, validation warnings/BLOCK, new version and stale status.
7. Download card for approved DOCX/PDF with accurate "승인됨"/"DRAFT" distinction.
8. Audit timeline with actor, action, linked case/doc/version, timestamps.

**Task management:** retain full standalone "내 할 일" and "부서 할 일" tables with scope toggle, status filters, task owner, document version, reasons and "열기". Keep separate approval worklist and human decision flow. A task click opens the exact case/document/approval in the agent context or existing detailed panel, preserving back navigation. Agent phrase "내 할 일 알려줘" must display the same server task list. All task counts and approval states share the same canonical server source.

**User journeys:** A) Ask to analyze L02, see evidence + SPC + historical records + D4 unconfirmed hypotheses; stop for investigation and approval. B) Reviewer enters via My Tasks and approves only with correct role, checks version hash, then agent reflects updated state. C) D6 ineffective triggers reopening D4, not fake close. D) User edits NCR via diff, revalidates, and receives a verified DOCX/PDF only for eligible approved/closed output. E) Meta unavailable: agent is clearly offline but queue, approvals, 8D manual and document editing remain accessible.

**Interaction & states:** working dropdowns/cards/modals/tabs, detail drawers, loading skeletons, tool timeout/error/retry, empty tasks, blocked gate, stale evidence, cross-case clarification, disconnected model, permissions denied, two-user handoff. Persist UX state conceptually via server and never assume AI is logged in as another role. No irreversible-looking button without confirmation and actual state validation.

**Deliverables:** desktop (1440px) and mobile (390px) screens, reusable component variants, one full agent conversation with expanding evidence/approval/doc cards, My Tasks/Department Tasks, blocked-case state, offline provider state, and navigable prototype. Keep visual hierarchy compact: conversation first, tasks always one click away, detailed analysis available on demand. Include UI-to-real-API binding notes; if an endpoint is unknown, label it "backend mapping required" rather than inventing it.

**Non-negotiable:** No backend implementation, no swapping business logic for frontend fake flows, no deleting functional modules or approval checks, no mock data portrayed as LIVE. Use Figma output as UI reference; actual source code must be integrated and verified separately.
