"""Routes of spec v5.15 §30: customer DOCX forms (DOC-OUT-01..04) and missing inputs (ASK-RESUME-01..03)."""

import hashlib
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import customer_docx as cd
from app import input_requests as ir
from app.model_provider import ModelProvider
from app.workflow import Actor, log, now, require_case, require_role, run_idempotent

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def make_v515_router(sessions: sessionmaker, current_user, provider: ModelProvider | None = None) -> APIRouter:
    from app.db import (
        CustomerTemplate,
        CustomerTemplateExport,
        CustomerTemplateProposal,
        InputRequest,
    )

    router = APIRouter()
    Who = Annotated[Actor, Depends(current_user)]
    IdemKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=80)]

    def template(session: Session, template_id: int):
        t = session.get(CustomerTemplate, template_id)
        if t is None:
            raise HTTPException(404, "Template not found")
        return t

    def for_case(session: Session, case_id: str, t, actor: Actor) -> None:
        if (cust := cd.customer_of(session, case_id)) != t.customer:
            raise HTTPException(403, f"다른 고객사의 양식입니다 (양식 {t.customer}, 사건 {cust or '미확인'})")

    # --- DOC-OUT-01: register --------------------------------------------------------------------------------
    @router.post("/customer-templates", status_code=201)
    def register(body: cd.TemplateIn, key: IdemKey, actor: Who):
        require_role(actor, "AUTHOR")  # the quality engineer who answers the customer

        def run(session: Session) -> tuple[int, dict]:
            return cd.register(session, body, actor)
        return run_idempotent(sessions, "customer_template", key, actor, run)

    @router.get("/customer-templates")
    def list_templates(actor: Who, customer: str | None = None) -> list[dict]:
        with sessions() as session:
            q = select(CustomerTemplate).order_by(CustomerTemplate.id)
            if customer:
                q = q.where(CustomerTemplate.customer == customer)
            return [{k: v for k, v in cd.template_out(session, t).items() if k != "fields"} for t in session.scalars(q)]

    @router.get("/customer-templates/{template_id}")
    def get_template(template_id: int, actor: Who) -> dict:
        with sessions() as session:
            return cd.template_out(session, template(session, template_id))

    # --- DOC-OUT-02: AI proposal ------------------------------------------------------------------------------
    @router.post("/customer-templates/{template_id}/proposals", status_code=201)
    def propose(template_id: int, actor: Who) -> dict:
        require_role(actor, "AUTHOR")
        with sessions() as session:
            t = template(session, template_id)
            sl, protected = t.slots, t.data_origin != "SYNTHETIC"
        res = cd.propose(provider, sl, protected)  # outside any transaction
        with sessions.begin() as session:
            row = CustomerTemplateProposal(template_id=template_id, mode=res["mode"], model=res["model"],
                                           status=res["status"], sent=res["sent"], reply=res["reply"],
                                           proposal=res["proposal"], issues=res["issues"], usage=res["usage"],
                                           created_by=actor.id, created_at=now())
            session.add(row)
            session.flush()
            return {"proposal_id": row.id, **{k: res[k] for k in ("status", "mode", "model", "issues", "proposal")}}

    # --- DOC-OUT-03/04: confirm, preview, export --------------------------------------------------------------
    @router.post("/customer-templates/{template_id}/mapping", status_code=201)
    def confirm(template_id: int, body: cd.MappingIn, key: IdemKey, actor: Who):
        require_role(actor, "AUTHOR")

        def run(session: Session) -> tuple[int, dict]:
            return 201, cd.confirm(session, template(session, template_id), body, actor)
        return run_idempotent(sessions, f"customer_template_mapping:{template_id}", key, actor, run)

    def mapping_for(session: Session, t):
        """The confirmed mapping of this version, else a reusable one of the same structure (DOC-OUT-04)."""
        return cd.latest_mapping(session, t) or cd.reusable(session, t)

    @router.get("/cases/{case_id}/customer-templates/{template_id}/preview")
    def preview(case_id: str, template_id: int, actor: Who) -> dict:
        with sessions() as session:
            require_case(session, case_id, actor)  # the case first: no form lookup for outsiders
            t = template(session, template_id)
            for_case(session, case_id, t, actor)
            return cd.fill_view(session, t, mapping_for(session, t), case_id)

    @router.get("/cases/{case_id}/customer-templates/{template_id}/export")
    def export(case_id: str, template_id: int, actor: Who, mode: Literal["draft", "final"] = "draft") -> Response:
        with sessions.begin() as session:
            require_case(session, case_id, actor)  # the case first: no form lookup for outsiders
            t = template(session, template_id)
            for_case(session, case_id, t, actor)
            m = mapping_for(session, t)
            view = cd.fill_view(session, t, m, case_id)
            if mode == "final" and view["final_blocked_by"]:
                raise HTTPException(409, "완성본 출력 불가: " + "; ".join(b["message"] for b in view["final_blocked_by"]))
            data = cd.render(t, view, final=mode == "final")
            text = cd.text_of(data)
            if mode == "final" and (miss := [s["id"] for s in view["slots"]
                                             if s["status"] == "FILLED" and str(s["shown"]) not in text]):
                raise HTTPException(500, f"출력 파일에 값이 없습니다: {miss[:5]}")  # read back, as export.py does
            sha = hashlib.sha256(data).hexdigest()
            used = sorted({s["source"] for s in view["slots"] if s["status"] in ("FILLED", "UNAPPROVED")})
            session.add(CustomerTemplateExport(template_id=t.id, template_version=t.version,
                                               mapping_id=m.id if m else None, case_id=case_id, mode=mode,
                                               case_data_version=view["case_data_version"], file_sha256=sha,
                                               sources=used, created_by=actor.id, created_at=now()))
            log(session, case_id, actor, "CUSTOMER_FORM_EXPORTED",
                f"{t.customer}/{t.name} v{t.version} mapping v{view['mapping_version']} {mode} {sha[:12]} "
                f"data {view['case_data_version']}")
            name, version = t.name, t.version
        from urllib.parse import quote
        return Response(data, media_type=DOCX, headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(f'{case_id}_{name}_v{version}_{mode}_{sha[:12]}.docx')}",
            "X-File-SHA256": sha, "X-Template-Version": str(version),
            "X-Mapping-Version": str(view["mapping_version"]), "X-Case-Data-Version": view["case_data_version"]})

    @router.get("/cases/{case_id}/customer-exports")
    def exports(case_id: str, actor: Who) -> list[dict]:
        with sessions() as session:
            require_case(session, case_id, actor)
            return [{"template_id": e.template_id, "template_version": e.template_version, "mapping_id": e.mapping_id,
                     "mode": e.mode, "case_data_version": e.case_data_version, "file_sha256": e.file_sha256,
                     "sources": e.sources, "by": e.created_by, "at": e.created_at}
                    for e in session.scalars(select(CustomerTemplateExport).where(
                        CustomerTemplateExport.case_id == case_id).order_by(CustomerTemplateExport.id))]

    # --- ASK-RESUME ---------------------------------------------------------------------------------------------
    def request(session: Session, request_id: int, actor: Actor):
        r = session.get(InputRequest, request_id)
        if r is None:
            raise HTTPException(404, "Request not found")
        require_case(session, r.case_id, actor)
        return r

    @router.post("/cases/{case_id}/calculations/held", status_code=201)
    def calc(case_id: str, body: ir.CalcIn, key: IdemKey, actor: Who):
        """Compute when the inputs are there; otherwise hold the action and ask (ASK-RESUME-01)."""
        require_role(actor, "AUTHOR")

        def run(session: Session) -> tuple[int, dict]:
            require_case(session, case_id, actor)
            return ir.start(session, case_id, body, actor)
        return run_idempotent(sessions, f"held_calc:{case_id}", key, actor, run)

    @router.get("/cases/{case_id}/input-requests")
    def list_requests(case_id: str, actor: Who) -> list[dict]:
        with sessions() as session:
            require_case(session, case_id, actor)
            return [ir.request_out(session, r) for r in session.scalars(select(InputRequest).where(
                InputRequest.case_id == case_id).order_by(InputRequest.id))]

    @router.post("/input-requests/{request_id}/suggestions", status_code=201)
    def suggest(request_id: int, actor: Who) -> dict:
        from app import egress
        from app.db import InputEvent, IntakeFile

        with sessions() as session:
            r = request(session, request_id, actor)

            def protected_of(fid):
                return egress.tier_of(session, session.get(IntakeFile, fid)) != "RAW"
            res = ir.suggest(session, r, provider, protected_of)
        with sessions.begin() as session:
            session.add(InputEvent(request_id=request_id, kind="SUGGESTED", payload=res, actor_id=actor.id,
                                   created_at=now()))
        return res

    @router.post("/input-requests/{request_id}/answers", status_code=201)
    def answer(request_id: int, body: ir.AnswerIn, key: IdemKey, actor: Who):
        require_role(actor, "AUTHOR")

        def run(session: Session) -> tuple[int, dict]:
            return ir.answer(session, request(session, request_id, actor), body, actor)
        return run_idempotent(sessions, f"input_answer:{request_id}", key, actor, run)

    @router.post("/input-requests/{request_id}/resume", status_code=201)
    def resume(request_id: int, key: IdemKey, actor: Who):
        require_role(actor, "AUTHOR")

        def run(session: Session) -> tuple[int, dict]:
            return ir.resume(session, request(session, request_id, actor), actor)
        return run_idempotent(sessions, f"input_resume:{request_id}", key, actor, run)

    return router
