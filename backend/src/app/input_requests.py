"""Missing inputs asked, answered and resumed (spec v5.15 §30.2, ASK-RESUME-01..03).

When a server calculation lacks a required input (the inspected quantity of LOT 0007 for its defect rate), the
server records the missing field, the case, LOT and period, and the held action. Meta may point at the allowed
sources where the value could be (ids the server lists; never values), and the server asks for exactly that field
and the allowed answer types. An answer is either a number a person enters (USER_ENTERED, with who, when and the
case scope) or the location of an original cell (SOURCE_CELL: the server re-reads the file and records value,
sheet, cell and file hash). Neither becomes document evidence. Before resuming, the server checks permission,
LOT and period, the source again, and the value's type, unit and range; only then it computes, and the calculation
id links the inputs. Repeated answers and resume requests return the first result.
"""

import hashlib
import io
import json
import re

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.workflow import Actor, now

ACTIONS = {"defect_rate": ("defective_qty", "inspected_qty")}  # action -> (numerator field, denominator field)
LABEL = {"inspected_qty": "검사 수량", "defective_qty": "불량 수량"}
COUNT_UNITS = {"", "ea", "pcs", "pc", "개", "個", "count"}  # DECISION: quantities are counts; other units are refused
ANSWER_KINDS = ("USER_ENTERED", "SOURCE_CELL")


def all_records(session: Session, case_id: str) -> dict[str, dict]:
    """Every evidence row of the case with its record, whatever its validity (customer-reported, user-entered)."""
    from app.db import Evidence, SourceEvent

    return {v.evidence_id: {**json.loads(e.raw_json), "_validity": v.validity, "_type": e.entity_type}
            for v, e in session.execute(select(Evidence, SourceEvent).join(
                SourceEvent, Evidence.source_event_id == SourceEvent.id).where(Evidence.case_id == case_id))}


def qty(rec: dict, name: str):
    """A quantity of a record: an inspection row's own column, or a customer/user value {"field", "value"}."""
    v = rec.get(name) if name in rec else rec.get("value") if rec.get("field") == name else None
    if isinstance(v, str) and re.fullmatch(r"\d+", v.strip()):
        v = int(v.strip())
    return v if isinstance(v, int | float) and not isinstance(v, bool) else None


def lot_of(rec: dict, recs: dict) -> str | None:
    if rec.get("lot") is not None:
        return str(rec["lot"])
    if rec.get("intake_id") is not None:  # a customer value: the LOT the person confirmed in the same draft
        return next((str(r["value"]) for r in recs.values() if r.get("intake_id") == rec["intake_id"]
                     and r.get("field") == "lot"), None)
    return None


def find(recs: dict, lot: str, field: str) -> list[str]:
    return [k for k, r in recs.items() if qty(r, field) is not None and lot_of(r, recs) == lot]


# --- requests -------------------------------------------------------------------------------------------------
class CalcIn(BaseModel):
    action: str = Field("defect_rate", max_length=30)
    lot: str = Field(min_length=1, max_length=60)
    # 2026-10, 2026-10-27 or 2026-10-01..2026-10-31: a SOURCE_CELL answer's row date must fall in it
    period: str | None = Field(None, pattern=r"^\d{4}(-\d{2}){0,2}(\.\.\d{4}(-\d{2}){0,2})?$")


def in_period(day: str, period: str) -> bool:
    """ISO day against a period: a prefix (2026-10) or an inclusive range (A..B, each a prefix)."""
    lo, _, hi = period.partition("..")
    return day.startswith(lo) if not hi else lo <= day[:len(lo)] and day[:len(hi)] <= hi


def events(session: Session, request_id: int) -> list:
    from app.db import InputEvent

    return list(session.scalars(select(InputEvent).where(InputEvent.request_id == request_id)
                                .order_by(InputEvent.id)))


def request_out(session: Session, r) -> dict:
    ev = events(session, r.id)
    accepted = [e for e in ev if e.kind == "ANSWER_ACCEPTED"]
    resumed = next((e for e in ev if e.kind == "RESUMED"), None)
    status = "RESUMED" if resumed else "ANSWERED" if accepted else "NEEDS_INPUT"
    return {"request_id": r.id, "case_id": r.case_id, "action": r.action, "lot": r.lot, "period": r.period,
            "missing_field": r.missing_field, "missing_label": LABEL[r.missing_field], "held": r.held, "status": status, "question": r.question,
            "allowed_answers": list(ANSWER_KINDS), "created_by": r.created_by, "created_at": r.created_at,
            "events": [{"id": e.id, "kind": e.kind, "payload": e.payload, "by": e.actor_id, "at": e.created_at}
                       for e in ev],
            "result": resumed.payload if resumed else None}


def missing_of(session: Session, case_id: str, body: CalcIn) -> dict | None:
    """What a new held request would ask for (the facts the model writes its question from), or None when the
    inputs are all there or an open request already asks."""
    from app.db import InputRequest

    if body.action not in ACTIONS:
        return None
    recs = all_records(session, case_id)
    have = {f: find(recs, body.lot, f) for f in ACTIONS[body.action]}
    missing = next((f for f in ACTIONS[body.action] if not have[f]), None)
    if missing is None or session.scalar(select(InputRequest.id).where(
            InputRequest.case_id == case_id, InputRequest.action == body.action, InputRequest.lot == body.lot,
            InputRequest.missing_field == missing)):
        return None
    return {"action": "defect rate (defective / inspected)" if body.action == "defect_rate" else body.action,
            "lot": body.lot, "period": body.period, "missing_field": LABEL[missing],
            "known": {LABEL[f]: [qty(recs[i], f) for i in ids] for f, ids in have.items() if ids},
            "answer_types": ["a number the person types (unit: count)", "the sheet and cell of an original file"]}


QUESTION_PROMPT = """A quality calculation is held because one input is missing. Write the question to the quality
engineer in polite Korean, one or two sentences: name the LOT (and period if given) and the missing value, and say
the two ways to answer. Ask only for that value. If server_check lists problems of your previous question, fix them."""
QUESTION_SCHEMA = {"type": "json_schema", "json_schema": {"name": "input_question", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["question"],
    "properties": {"question": {"type": "string"}}}}}


def write_question(provider, need: dict) -> str:
    """The model writes the question (user 2026-11-04); the server checks it names the LOT and the missing value,
    and sends what is wrong back once. "" when there is no model or it never passes (the screen shows a notice)."""
    from app import limits
    from app.model_provider import ProviderError

    if provider is None:
        return ""
    feedback, q = [], ""
    for _ in range(1 + limits.get("AGENT_ANSWER_MAX_REPAIRS")):
        try:
            r = provider.chat([{"role": "system", "content": QUESTION_PROMPT},
                               {"role": "user", "content": json.dumps({**need, "server_check": feedback,
                                                                       "previous": q}, ensure_ascii=False)}],
                              [], response_format=QUESTION_SCHEMA)
            q = str(json.loads(r["message"].get("content") or "")["question"]).strip()[:300]
        except (ProviderError, ValueError, KeyError, TypeError):
            return ""
        feedback = [f"질문에 {x}이(가) 없습니다" for x in (need["lot"], need["missing_field"]) if x not in q]
        if q and not feedback:
            return q
    return ""


def start(session: Session, case_id: str, body: CalcIn, actor: Actor, question: str = "") -> tuple[int, dict]:
    """Compute when every input is there; otherwise record the held action and the model's question (one open
    request per case, action, LOT and missing field)."""
    from app.db import InputRequest

    if body.action not in ACTIONS:
        raise HTTPException(422, f"action must be one of {sorted(ACTIONS)}")
    recs = all_records(session, case_id)
    num_f, den_f = ACTIONS[body.action]
    have = {f: find(recs, body.lot, f) for f in (num_f, den_f)}
    missing = next((f for f in (num_f, den_f) if not have[f]), None)
    if missing is None:
        return 200, {"status": "COMPUTED", **calculate(session, case_id, body.action, body.lot, have[num_f],
                                                           have[den_f], recs)}
    open_ = session.scalar(select(InputRequest).where(
        InputRequest.case_id == case_id, InputRequest.action == body.action, InputRequest.lot == body.lot,
        InputRequest.missing_field == missing).order_by(InputRequest.id.desc()).limit(1))
    if open_ and request_out(session, open_)["status"] != "RESUMED":
        return 200, request_out(session, open_)
    r = InputRequest(case_id=case_id, action=body.action, lot=body.lot, period=body.period, missing_field=missing,
                     held={"action": body.action, "numerator": num_f, "denominator": den_f,
                           "have": {f: ids for f, ids in have.items() if ids}},
                     question=question, created_by=actor.id, created_at=now())
    session.add(r)
    session.flush()
    from app.workflow import log
    log(session, case_id, actor, "INPUT_REQUESTED", f"#{r.id} {body.action} LOT {body.lot}: {missing} missing")
    return 201, request_out(session, r)


def calculate(session, case_id, action, lot, num_ids, den_ids, recs) -> dict:
    from app.calculations import CalcError, compute

    num_f, den_f = ACTIONS[action]
    for i in den_ids:
        d, n = qty(recs[i], den_f), sum(qty(recs[j], num_f) for j in num_ids)
        if not d or d <= 0:
            raise HTTPException(422, f"{LABEL[den_f]}이 0 이하입니다 ({i}): 다시 확인해 주세요")
        if d < n:
            raise HTTPException(422, f"{LABEL[den_f]} {d}이 {LABEL[num_f]} {n}보다 작습니다 ({i})")
    try:
        c = compute(session, case_id, "quotient", num_ids, num_f, den_ids, recs=recs, denominator_field=den_f)
    except CalcError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"calculation": c, "rate_percent": round(c["value"] * 100, 4), "lot": lot,
            "inputs": [{"evidence_id": i, "field": f, "value": qty(recs[i], f), "source_type": recs[i]["_validity"]}
                       for f, ids in ((num_f, num_ids), (den_f, den_ids)) for i in ids]}


# --- where the value could be: the allowed sources, and the model's pointer ------------------------------------
def sources(session: Session, case_id: str) -> list[dict]:
    """Files of the case's intakes the server may show by structure: XLSX tables with their column headers."""
    from app.db import IntakeCaseLink, IntakeFile
    from app.inspection_layout import tables
    from app.intake import XLSX

    out = []
    links = {k.intake_id for k in session.scalars(select(IntakeCaseLink).where(IntakeCaseLink.case_id == case_id))}
    for f in session.scalars(select(IntakeFile).where(IntakeFile.intake_id.in_(links)).order_by(IntakeFile.id)):
        if f.media_type != XLSX:
            out.append({"id": f"F{f.id}", "file_id": f.id, "name": f.name, "tables": []})
            continue
        try:
            ts = tables(f.content)
        except HTTPException:
            ts = []
        out.append({"id": f"F{f.id}", "file_id": f.id, "name": f.name, "tables": [
            {"id": f"F{f.id}:{t['id']}", "sheet": t["sheet"], "range": t["range"],
             "columns": [{"id": f"F{f.id}:{t['id']}:{col}", "header": h} for col, h in t["columns"].items()]}
            for t in ts]})
    return out


SUGGEST_PROMPT = """A quality calculation is held because one input is missing. The server lists the files of this
case with their table column headers (no cell values). Point at the columns that most likely hold the missing
value for the given LOT, by their ids only, with a short reason. Return an empty list when nothing fits."""
SUGGEST_SCHEMA = {"type": "json_schema", "json_schema": {"name": "input_sources", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["candidates"],
    "properties": {"candidates": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["source_id", "reason"],
        "properties": {"source_id": {"type": "string"}, "reason": {"type": "string"}}}}}}}}


def suggest(session: Session, r, provider, protected_of) -> dict:
    """ASK-RESUME-01: Meta points at allowed sources; the server keeps only the ids it listed."""
    from app.egress import MASK_NOTE, Masker
    from app.inspection_layout import header_terms, languages, mask_header
    from app.model_provider import ProviderError

    src = sources(session, r.case_id)
    known = {c["id"]: (s, t, c) for s in src for t in s["tables"] for c in t["columns"]}
    if provider is None or not known:
        return {"status": "OFFLINE" if provider is None else "NO_SOURCES", "candidates": [], "mode": "OFFLINE",
                "model": None, "usage": {}}
    masker = Masker()
    heads = [c["header"] for s in src for t in s["tables"] for c in t["columns"]]
    terms = header_terms(languages(heads))
    protected = any(protected_of(s["file_id"]) for s in src)
    sent = {"missing": {"field": r.missing_field, "label": LABEL[r.missing_field], "lot": masker.mask(r.lot)
                        if protected else r.lot, "period": r.period},
            "sources": [{"file": s["id"], "tables": [{"id": t["id"], "columns": [
                {"id": c["id"], "header": mask_header(c["header"], terms, masker) if protected_of(s["file_id"])
                 else c["header"]} for c in t["columns"]]} for t in s["tables"]]} for s in src]}
    try:
        out = provider.chat([{"role": "system", "content": SUGGEST_PROMPT + ("\n" + MASK_NOTE if protected else "")},
                             {"role": "user", "content": json.dumps(sent, ensure_ascii=False)}], [],
                            response_format=SUGGEST_SCHEMA)
        reply = json.loads(out["message"].get("content") or "")
    except (ProviderError, ValueError, KeyError, TypeError) as exc:
        return {"status": "FAILED", "candidates": [], "mode": provider.mode, "model": provider.model, "usage": {},
                "error": type(exc).__name__}
    cands = []
    for x in reply.get("candidates") or []:
        if isinstance(x, dict) and x.get("source_id") in known:
            s, t, c = known[x["source_id"]]
            cands.append({"source_id": x["source_id"], "file_id": s["file_id"], "file": s["name"],
                          "sheet": t["sheet"], "column": x["source_id"].rsplit(":", 1)[1], "header": c["header"],
                          "reason": masker.unmask(str(x.get("reason", "")))[:300]})
    return {"status": "OK", "candidates": cands, "mode": provider.mode, "model": provider.model,
            "usage": out.get("usage") or {}, "dropped": len(reply.get("candidates") or []) - len(cands)}


# --- answers -------------------------------------------------------------------------------------------------
class AnswerIn(BaseModel):
    kind: str = Field(pattern="^(USER_ENTERED|SOURCE_CELL)$")
    value: float | None = None  # USER_ENTERED
    unit: str | None = Field(None, max_length=20)
    file_id: int | None = None  # SOURCE_CELL
    sheet: str | None = Field(None, max_length=120)
    cell: str | None = Field(None, pattern=r"^[A-Za-z]{1,3}[0-9]{1,7}$")


def read_cell(session: Session, case_id: str, r, body: AnswerIn, actor: Actor) -> dict:
    """The original cell again, with the LOT (and date) of its row from the table's own columns."""
    import openpyxl

    from app import inspection_layout as lay
    from app import inspection_xlsx as ix
    from app.db import IntakeCaseLink, IntakeFile
    from app.intake import XLSX

    f = session.get(IntakeFile, body.file_id or 0)
    links = {k.intake_id for k in session.scalars(select(IntakeCaseLink).where(IntakeCaseLink.case_id == case_id))}
    if f is None or f.intake_id not in links:
        raise HTTPException(403, "이 사건에 연결된 파일이 아닙니다")
    if f.media_type != XLSX:
        raise HTTPException(422, "셀 위치는 XLSX 파일에서만 읽습니다")
    wb = openpyxl.load_workbook(io.BytesIO(f.content), data_only=True, keep_links=False)
    if body.sheet not in wb.sheetnames:
        raise HTTPException(422, f"시트 {body.sheet!r}가 없습니다")
    ws = wb[body.sheet]
    ref = body.cell.upper()
    raw = ws[ref].value
    row = ws[ref].row
    col = re.match(r"[A-Z]+", ref).group(0)
    t = next((t for t in lay.tables(f.content) if t["sheet"] == body.sheet
              and t["first_data_row"] <= row <= t["last_row"]), None)
    mapping = ix.suggest(t["columns"]) if t else {}
    lot_col, date_col = mapping.get("lot"), mapping.get("inspected_on")
    day = ws[f"{date_col}{row}"].value if date_col else None
    return {"file_id": f.id, "intake_id": f.intake_id, "file": f.name, "file_sha256": f.sha256, "sheet": body.sheet,
            "cell": ref, "raw": raw, "row": row, "column": col,
            "column_header": t["columns"].get(col) if t else None,
            "column_field": next((k for k, v in mapping.items() if v == col), None),
            "lot_cell": f"{lot_col}{row}" if lot_col else None,
            "row_lot": None if not lot_col or ws[f"{lot_col}{row}"].value is None else str(ws[f"{lot_col}{row}"].value),
            "date_cell": f"{date_col}{row}" if date_col else None,
            "row_date": None if day is None else (day.isoformat() if hasattr(day, "isoformat") else str(day))[:10]}


def check_value(r, value, unit, recs) -> str | None:
    """Why this value cannot be the missing quantity, or None."""
    if unit is not None and unit.strip().lower() not in COUNT_UNITS:
        return f"단위 {unit!r}는 수량(개) 단위가 아닙니다"
    if not isinstance(value, int | float) or isinstance(value, bool):
        return f"숫자가 아닙니다: {value!r}"
    if float(value) != int(value):
        return "수량은 정수여야 합니다"
    if value <= 0 and r.missing_field == "inspected_qty":
        return "검사 수량이 0 이하입니다"
    if value < 0:
        return "수량이 음수입니다"
    num_f, den_f = ACTIONS[r.action]
    if r.missing_field == den_f:
        n = sum(qty(recs[i], num_f) for i in r.held["have"].get(num_f, []) if i in recs)
        if value < n:
            return f"{LABEL[den_f]} {int(value)}이 {LABEL[num_f]} {n}보다 작습니다"
    return None


def answer(session: Session, r, body: AnswerIn, actor: Actor) -> tuple[int, dict]:
    from app.db import Evidence, InputEvent, SourceAsset, SourceEvent
    from app.workflow import log

    st = request_out(session, r)
    if st["status"] == "RESUMED":
        return 200, {**st, "duplicate": True}
    recs = all_records(session, r.case_id)
    if body.kind == "USER_ENTERED":
        if body.value is None:
            raise HTTPException(422, "value가 필요합니다")
        value, loc = body.value, None
    else:
        if not (body.file_id and body.sheet and body.cell):
            raise HTTPException(422, "file_id, sheet, cell이 필요합니다")
        loc = read_cell(session, r.case_id, r, body, actor)
        value = loc["raw"]
    why = check_value(r, value, body.unit, recs)
    if not why and loc:
        if loc["row_lot"] is None:
            why = "이 행의 LOT을 확인할 수 없습니다 (LOT 열이 없는 위치)"
        elif loc["row_lot"].strip() != r.lot:
            why = f"범위 불일치: {loc['lot_cell']}의 LOT은 {loc['row_lot']}이고 요청은 {r.lot}입니다"
        elif r.period and loc["row_date"] is None:
            why = f"이 행의 검사일을 확인할 수 없어 기간 {r.period}과 대조할 수 없습니다 (검사일 열이 없는 위치)"
        elif r.period and not in_period(loc["row_date"], r.period):
            why = f"범위 불일치: {loc['date_cell']}의 검사일 {loc['row_date']}은 기간 {r.period} 밖입니다"
        elif loc["column_field"] not in (None, r.missing_field):
            why = f"범위 불일치: {loc['cell']}은 '{loc['column_header']}' 열입니다 ({LABEL[r.missing_field]} 아님)"
    content = {"kind": body.kind, "value": value if not isinstance(value, float) or not value.is_integer()
               else int(value), "unit": body.unit, "locator": loc}
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()
    accepted = [e for e in events(session, r.id) if e.kind == "ANSWER_ACCEPTED"]
    if why:
        session.add(InputEvent(request_id=r.id, kind="ANSWER_REJECTED", payload={**content, "reason": why},
                               actor_id=actor.id, created_at=now()))
        session.flush()
        return 200, {**request_out(session, r), "rejected": why}
    if same := next((e for e in accepted if e.payload.get("digest") == digest), None):
        return 200, {**request_out(session, r), "duplicate": True, "evidence_id": same.payload["evidence_id"]}
    if accepted:
        raise HTTPException(409, f"이미 확인된 답변이 있습니다 ({accepted[-1].payload['value']}): 다른 값은 새 요청으로 확인하세요")
    at = now()
    record = {"field": r.missing_field, "value": content["value"], "unit": body.unit or "EA", "lot": r.lot,
              "period": r.period, "answer_kind": body.kind, "answered_by": actor.id, "answered_at": at,
              "case_id": r.case_id, "input_request_id": r.id, "locator": loc,
              "original_row_id": f"input:{r.id}"}
    raw = json.dumps(record, sort_keys=True, ensure_ascii=False, default=str)
    sha = hashlib.sha256(raw.encode()).hexdigest()
    a = SourceAsset(case_id=r.case_id, asset_id=f"input:{r.id}:{digest[:12]}",
                    source_system="USER_INPUT" if body.kind == "USER_ENTERED" else "INTAKE_XLSX_CELL",
                    entity_type="INPUT_ANSWER", source_version=1, supersedes_asset_id=None, license_id="INTERNAL",
                    data_origin="USER" if body.kind == "USER_ENTERED" else "CUSTOMER", sensitivity="UNKNOWN",
                    captured_at=at, ingested_at=at, content_sha256=loc["file_sha256"] if loc else sha, raw_json=raw)
    session.add(a)
    session.flush()
    e = SourceEvent(case_id=r.case_id, source_asset_id=a.id, event_id=f"IR{r.id}", original_row_id=f"input:{r.id}",
                    entity_type="INPUT_ANSWER", entity_key=[r.lot, r.missing_field], event_time=at,
                    source_updated_at=None, ingested_at=at, data_origin=a.data_origin, sensitivity="UNKNOWN",
                    validation_status=body.kind, raw_json=raw)
    session.add(e)
    session.flush()
    eid = f"EV-IR{r.id}"
    session.add(Evidence(case_id=r.case_id, source_event_id=e.id, evidence_id=eid, classification=body.kind,
                         validity=body.kind, content_sha256=sha))  # not CHECKED: never promoted to document evidence
    session.add(InputEvent(request_id=r.id, kind="ANSWER_ACCEPTED",
                           payload={**content, "digest": digest, "evidence_id": eid}, actor_id=actor.id,
                           created_at=at))
    log(session, r.case_id, actor, "INPUT_ANSWERED", f"#{r.id} {r.missing_field}={content['value']} ({body.kind})")
    session.flush()
    return 201, {**request_out(session, r), "evidence_id": eid}


def resume(session: Session, r, actor: Actor) -> tuple[int, dict]:
    """ASK-RESUME-03: re-check, then run only the held action; the second time returns the first result."""
    from app.db import InputEvent, IntakeFile
    from app.workflow import log

    st = request_out(session, r)
    if st["status"] == "RESUMED":
        return 200, {**st, "duplicate": True}
    accepted = [e for e in events(session, r.id) if e.kind == "ANSWER_ACCEPTED"]
    if not accepted:
        raise HTTPException(409, "확인된 답변이 없습니다: 먼저 값을 답해 주세요")
    ans = accepted[-1].payload
    recs = all_records(session, r.case_id)

    def hold(why):
        session.add(InputEvent(request_id=r.id, kind="RESUME_HELD", payload={"reason": why}, actor_id=actor.id,
                               created_at=now()))
        session.flush()
        return 200, {**request_out(session, r), "held_reason": why}
    if loc := ans.get("locator"):  # the original again: the same file and the same cell value
        import openpyxl
        f = session.get(IntakeFile, loc["file_id"])
        if f is None or f.sha256 != loc["file_sha256"] or hashlib.sha256(f.content).hexdigest() != loc["file_sha256"]:
            return hold("원본 파일이 바뀌었습니다: 다시 답해 주세요")
        ws = openpyxl.load_workbook(io.BytesIO(f.content), data_only=True)[loc["sheet"]]
        if ws[loc["cell"]].value != loc["raw"]:
            return hold("원본 셀 값이 바뀌었습니다: 다시 답해 주세요")
    if why := check_value(r, ans["value"], ans.get("unit"), recs):
        return hold(why)
    num_f, den_f = ACTIONS[r.action]
    have = {f: [i for i in r.held["have"].get(f, []) if i in recs] for f in (num_f, den_f)}
    have[r.missing_field] = [ans["evidence_id"]]
    if not have[num_f] or not have[den_f]:
        return hold("다른 입력이 아직 없습니다")
    try:
        result = calculate(session, r.case_id, r.action, r.lot, have[num_f], have[den_f], recs)
    except HTTPException as exc:
        return hold(str(exc.detail))
    session.add(InputEvent(request_id=r.id, kind="RESUMED", payload=result, actor_id=actor.id, created_at=now()))
    log(session, r.case_id, actor, "INPUT_RESUMED", f"#{r.id} {r.action} LOT {r.lot}: "
        f"{result['calculation']['calculation_id']} = {result['rate_percent']}%")
    session.flush()
    return 201, request_out(session, r)
