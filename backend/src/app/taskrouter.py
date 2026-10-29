"""Task Router (structure D, FR-25): which work the server does and which a language model may assist.

SERVER tasks are numbers, rules, statistics, retrieval filters and approvals; they never call a model. MODEL
tasks only produce proposals (DRAFT / PROPOSAL / UNKNOWN) through read-only tools; when no LIVE provider is
configured they are OFFLINE and the listed SERVER fallback keeps the workflow usable.
"""

ROUTES = {
    "SPC_LIMITS_AND_RULES": ("SERVER", "app.spc"),
    "CLAIM_VALIDATION": ("SERVER", "app.factcheck.validate"),
    "TEMPLATE_CONFORMANCE": ("SERVER", "app.validation.contract_issues"),
    "EFFECTIVENESS_STATISTICS": ("SERVER", "app.effect.evaluate"),
    "EXPERIENCE_RETRIEVAL": ("SERVER", "app.experience.retrieve"),
    "DOCUMENT_RETRIEVAL": ("SERVER", "app.validation.search_documents"),
    "EVIDENCE_GAP_ANALYSIS": ("SERVER", "app.causes.evidence_gaps"),
    "WORKFLOW_GATES_AND_APPROVAL": ("SERVER", "app.eightd.approval_gate / app.policy"),
    "INVESTIGATION_PLAN": ("MODEL", "POST /cases/{id}/investigations (read-only tools)"),
    "CASE_COMPARISON_NARRATIVE": ("MODEL", "POST /cases/{id}/investigations with hybrid=true"),
}
FALLBACK = {"INVESTIGATION_PLAN": ["EVIDENCE_GAP_ANALYSIS", "EXPERIENCE_RETRIEVAL"],
            "CASE_COMPARISON_NARRATIVE": ["EXPERIENCE_RETRIEVAL"]}


def route(task: str, provider_mode: str | None) -> dict:
    kind, where = ROUTES[task]
    if kind == "SERVER":
        return {"task": task, "route": "SERVER", "where": where, "calls_model": False}
    if provider_mode is None:
        return {"task": task, "route": "OFFLINE", "where": where, "calls_model": False,
                "fallback": FALLBACK.get(task, [])}
    return {"task": task, "route": "MODEL", "where": where, "calls_model": True, "provider_mode": provider_mode}


def table(provider_mode: str | None) -> list[dict]:
    return [route(t, provider_mode) for t in ROUTES]
