"""Unregistered inspection XLSX (spec v5.14 §29 AI-CFG-01/02): the server finds the table candidates (sheets, merged
cells, multi-row headers), routes the file (a mapping a person confirmed for the same structure, a registered form's
header words, or an AI proposal), asks the model only about the headers and structure it found, checks the reply
against those candidates, and keeps a person's confirmed mapping on the inspection form store for the next file of
the same structure.

The model sees header texts and column types, never cell values; it may choose only a candidate id, a column of that
candidate and a known field. Its reply is data (JSON under a strict schema), never code. Every value is then read
again from the file by the server with the usual row checks (inspection_xlsx.read).
"""

import hashlib
import json
import re
from datetime import date, datetime

from fastapi import HTTPException
from openpyxl.utils import get_column_letter
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import inspection_xlsx as ix
from app.fields import FreeText

MAX_HEADER_ROWS = 3  # DECISION: two-row headers (a merged parent over child labels) are common; three is the most
MAX_TYPE_ROWS = 50  # DEFAULT: data rows sampled per column for its type profile (types only, no values)
SAMPLE_CELLS = 3  # DEFAULT: original cells shown beside an uncertain field
NUMBER = re.compile(r"^-?\d[\d,]*(\.\d+)?$")


def _is_number(v) -> bool:
    return (isinstance(v, (int, float)) and not isinstance(v, bool)) or isinstance(v, (datetime, date))


def _is_text(v) -> bool:
    return isinstance(v, str) and bool(v.strip()) and not NUMBER.match(v.strip())


def _grid(ws) -> dict[tuple[int, int], object]:
    """Non-empty cells, with a merged range's value on every cell it covers (a merged header names each column)."""
    g = {(c.row, c.column): c.value for row in ws.iter_rows() for c in row
         if c.value is not None and not (isinstance(c.value, str) and not c.value.strip())}
    for rng in ws.merged_cells.ranges:
        v = ws.cell(rng.min_row, rng.min_col).value
        if v is None:
            continue
        for r in range(rng.min_row, rng.max_row + 1):
            for col in range(rng.min_col, rng.max_col + 1):
                g[(r, col)] = v
    return g


def _profile(values: list) -> dict:
    t = {"number": 0, "date": 0, "text": 0, "code_with_leading_zero": 0, "empty": 0}
    for v in values:
        if v is None:
            t["empty"] += 1
        elif isinstance(v, (datetime, date)):
            t["date"] += 1
        elif _is_number(v):
            t["number"] += 1
        elif isinstance(v, str) and re.fullmatch(r"0\d+", v.strip()):
            t["code_with_leading_zero"] += 1
        else:
            t["text"] += 1
    return {k: n for k, n in t.items() if n}


def structure_sha(c: dict) -> str:
    """The identity of a table structure: sheet, header rows and each column's header words (not the data)."""
    return hashlib.sha256(json.dumps([c["sheet"], c["header_rows"], {k: ix._key(v) for k, v in c["columns"].items()}],
                                     ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def tables(data: bytes) -> list[dict]:
    """Table candidates on the visible sheets: a block of rows between blank rows whose leading all-text rows (up to
    MAX_HEADER_ROWS, each covering at least half of the data columns) sit right above rows holding numbers."""
    wb, _ = ix._workbook(data)
    out = []
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            continue
        g = _grid(ws)
        rows = sorted({r for r, _ in g})
        blocks, cur = [], []
        for r in rows:
            if cur and r != cur[-1] + 1:
                blocks.append(cur)
                cur = []
            cur.append(r)
        if cur:
            blocks.append(cur)
        for block in blocks:
            cells = {r: {col: g[(r, col)] for (rr, col) in g if rr == r} for r in block}
            first = next((i for i, r in enumerate(block) if any(_is_number(v) for v in cells[r].values())), None)
            if first is None or first == 0:
                continue  # no data rows, or no header above them: nothing a mapping could name
            data_cols = set(cells[block[first]])
            heads = []
            for r in reversed(block[max(0, first - MAX_HEADER_ROWS):first]):
                vals = cells[r]
                # the row right above the data names at least half its columns; a row above that joins the header
                # only as a merged parent or when it names nearly all columns (not "Supplier: ACME" lines)
                need = 0.5 if not heads else 0.8
                parent = any(m.min_row <= r <= m.max_row and m.max_col > m.min_col for m in ws.merged_cells.ranges)
                if not all(_is_text(v) for v in vals.values()) or (len(vals) < need * len(data_cols) and not parent):
                    break
                heads.insert(0, r)
            if not heads:
                continue
            body = block[first:]
            cols = sorted(set().union(*(cells[r] for r in heads + body)))
            columns = {}
            for col in cols:
                parts = [str(cells[r][col]).strip() for r in heads if col in cells[r]]
                columns[get_column_letter(col)] = " / ".join(dict.fromkeys(parts))
            c = {"sheet": ws.title, "header_rows": heads, "first_data_row": body[0], "last_row": body[-1],
                 "data_rows": len(body), "columns": columns,
                 "types": {get_column_letter(col): _profile([cells[r].get(col) for r in body[:MAX_TYPE_ROWS]])
                           for col in cols},
                 "merged_header": any((r, col) in g and ws.cell(r, col).coordinate in ws.merged_cells
                                      for r in heads for col in cols)}
            out.append({"id": f"T{len(out) + 1}", "range": f"{ws.title}!{get_column_letter(cols[0])}{heads[0]}:"
                        f"{get_column_letter(cols[-1])}{body[-1]}", **c, "structure_sha": structure_sha(c)})
    return out


def _word_match(c: dict, form: dict) -> dict:
    return ix.suggest(c["columns"], form["fields"])


def route(cands: list[dict], forms: list[dict]) -> dict:
    """REUSED (a confirmed mapping for exactly this structure), FORM (one table a form's header words fully name), or
    NEEDS_AI with the reasons; a conflict or a changed structure also goes to review, never silently reused."""
    learned = [f for f in forms if f.get("structure_sha")]
    by_sha = {}
    for f in learned:
        by_sha.setdefault(f["structure_sha"], []).append(f)
    hits = [(c, f) for c in cands for f in by_sha.get(c["structure_sha"], [])]
    reasons = []
    if len({f["name"] for _, f in hits}) == 1:
        c, f = hits[0]
        return {"route": "REUSED", "table": c["id"], "form": f["name"], "reasons": []}
    if hits:
        reasons.append({"code": "REUSE_CONFLICT", "message": "같은 구조에 저장된 매핑이 여럿입니다: "
                        + ", ".join(sorted({f["name"] for _, f in hits})) + " (다시 검토)"})
    for f in learned:  # a confirmed form whose sheet is here but whose structure changed
        for c in cands:
            if c["sheet"] == f["structure"]["sheet"] and c["structure_sha"] != f["structure_sha"] and \
                    sum(1 for v in _word_match(c, f).values() if v) >= 2:
                reasons.append({"code": "STRUCTURE_CHANGED", "message": f"저장된 매핑 {f['name']}와 헤더 구조가 "
                                f"다릅니다 ({c['range']}): 다시 검토"})
    words = [f for f in forms if not f.get("structure_sha")]
    full = [(c, f) for c in cands for f in words if all(_word_match(c, f).get(k) for k in f["required"])]
    if not cands:
        reasons.append({"code": "NO_HEADER", "message": "헤더와 데이터가 있는 표를 찾지 못했습니다"})
    elif len(cands) > 1:
        reasons.append({"code": "MULTIPLE_TABLES", "message": f"표 후보가 {len(cands)}개입니다: "
                        + ", ".join(c["range"] for c in cands)})
    elif not full:
        reasons.append({"code": "REQUIRED_NOT_MAPPED", "message": "등록 양식의 헤더 단어로 필수 열(LOT·검사 수량·"
                        "불량 수량)을 모두 찾지 못했습니다"})
    if not reasons and full:
        c, f = full[0]
        return {"route": "FORM", "table": c["id"], "form": f["name"], "reasons": []}
    return {"route": "NEEDS_AI", "table": cands[0]["id"] if len(cands) == 1 else None, "form": None,
            "reasons": reasons}


# --- meaning checks: quantities a count alone cannot tell apart (Accepted vs Rejected) ------------------------
REJECT = re.compile(r"(?i)reject|fail|\bng\b|^ng|defect|불합격|불량|부적합|不良|不合格")
ACCEPT = re.compile(r"(?i)accept|pass|\bok\b|good|합격|양품|적합|良品|合格")
TOTAL = re.compile(r"(?i)inspect|total|sample|검사|총|수량|検査|检验|數|数")


def meaning(header: str) -> str | None:
    h = header or ""
    return "REJECT" if REJECT.search(h) else "ACCEPT" if ACCEPT.search(h) else "TOTAL" if TOTAL.search(h) else None


def check_mapping(c: dict, mapping: dict, required=ix.REQUIRED) -> list[dict]:
    """Server checks on a proposed or edited mapping: known fields, the candidate's own columns, no column used
    twice, required fields present."""
    issues = []
    for k, col in mapping.items():
        if k not in ix.FIELDS:
            issues.append({"level": "BLOCK", "code": "UNKNOWN_FIELD", "field": k, "message": f"모르는 필드 {k}"})
        elif col and col not in c["columns"]:
            issues.append({"level": "BLOCK", "code": "OUT_OF_RANGE", "field": k,
                           "message": f"{col}열은 표 후보 {c['id']} ({c['range']})에 없습니다"})
    used: dict[str, list[str]] = {}
    for k, col in mapping.items():
        if col:
            used.setdefault(col, []).append(k)
    for col, ks in used.items():
        if len(ks) > 1:
            issues.append({"level": "BLOCK", "code": "DUPLICATE_MAPPING", "field": ks[0],
                           "message": f"{col}열이 {', '.join(ks)}에 함께 연결됐습니다"})
    for k in required:
        if not mapping.get(k):
            issues.append({"level": "BLOCK", "code": "REQUIRED_NOT_MAPPED", "field": k, "message": f"필수 {k} 미연결"})
    return issues


def uncertain(c: dict, mapping: dict, data: bytes, unresolved: list[str] = ()) -> list[dict]:
    """Fields a person must confirm, each with its header context and original cells next to the other quantity
    columns: a count check cannot tell Accepted from Rejected, so the header's meaning decides what is asked."""
    wb, _ = ix._workbook(data)
    ws = wb[c["sheet"]]
    rows = list(range(c["first_data_row"], min(c["last_row"], c["first_data_row"] + SAMPLE_CELLS - 1) + 1))

    def cells(col):
        return [{"cell": f"{col}{r}", "raw": ws[f"{col}{r}"].value if not isinstance(ws[f"{col}{r}"].value,
                (datetime, date)) else ws[f"{col}{r}"].value.isoformat()} for r in rows]

    qty_cols = [col for col, h in c["columns"].items()  # count columns: numbers under a quantity-like header
                if c["types"].get(col, {}).get("number") and meaning(h) in ("ACCEPT", "REJECT", "TOTAL")]
    context = [{"column": col, "header": c["columns"][col], "meaning": meaning(c["columns"][col]),
                "cells": cells(col)} for col in qty_cols]
    out = []

    def ask(field, why):
        col = mapping.get(field)
        out.append({"field": field, "column": col, "header": c["columns"].get(col) if col else None, "why": why,
                    "cells": cells(col) if col else [], "context": context})

    d, i = mapping.get("defective_qty"), mapping.get("inspected_qty")
    if d:
        m = meaning(c["columns"].get(d, ""))
        if m == "ACCEPT":
            ask("defective_qty", "합격(양품) 수량으로 보이는 열이 불량 수량에 연결됐습니다")
        elif m != "REJECT":
            ask("defective_qty", "열 이름만으로 불량 수량인지 알 수 없습니다")
    if i and meaning(c["columns"].get(i, "")) in ("ACCEPT", "REJECT"):
        ask("inspected_qty", "합격·불합격 수량은 검사 수량(전체)과 다를 수 있습니다")
    for f in unresolved:
        if f not in {x["field"] for x in out}:
            ask(f, "AI가 확정하지 못한 항목입니다")
    return out


# --- the model's proposal ------------------------------------------------------------------------------------
PROMPT = """You map the columns of an inspection-result spreadsheet to known fields.
The server found the table candidates below: header texts per column (merged and multi-row headers joined with " / ")
and each column's value types. You do not see cell values.
Fields: part_number, lot (LOT number), inspected_on (inspection date), inspected_qty (the number inspected, the
total), defective_qty (the number found defective or rejected), item (measured characteristic), value (measured
value), unit.
Choose one candidate_id (the table holding one row per LOT with its quantities) and, for every field, one column of
that candidate or "NONE". Never map an accepted/passed/good count to defective_qty, and never map an accepted or a
rejected count to inspected_qty unless it is clearly the total. Use each column at most once. Give a short reason per
field. List in unresolved every field you are not sure about. Required: lot, inspected_qty, defective_qty."""


def schema(cands: list[dict]) -> dict:
    cols = sorted({col for c in cands for col in c["columns"]}) + ["NONE"]
    return {"type": "json_schema", "json_schema": {"name": "xlsx_mapping", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["candidate_id", "fields", "unresolved"],
        "properties": {
            "candidate_id": {"type": "string", "enum": [c["id"] for c in cands]},
            "fields": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["field", "column", "reason"],
                "properties": {"field": {"type": "string", "enum": list(ix.FIELDS)},
                               "column": {"type": "string", "enum": cols}, "reason": {"type": "string"}}}},
            "unresolved": {"type": "array", "items": {"type": "string", "enum": list(ix.FIELDS)}}}}}}


def sent_view(cands: list[dict], protected: bool, masker) -> list[dict]:
    """What may leave: header texts (masked when the file is protected) and column types, never values."""
    def m(t):
        return masker.mask(t) if protected else t
    return [{"id": c["id"], "range": m(c["range"]), "sheet": m(c["sheet"]), "header_rows": c["header_rows"],
             "data_rows": c["data_rows"], "merged_header": c["merged_header"],
             "columns": [{"column": col, "header": m(h), "types": c["types"].get(col, {})}
                         for col, h in c["columns"].items()]} for c in cands]


def propose(provider, cands: list[dict], protected: bool) -> dict:
    """One structured call; the reply is checked against the candidates. Never raises for model problems."""
    from app.egress import MASK_NOTE, Masker
    from app.model_provider import ProviderError

    masker = Masker()
    sent = sent_view(cands, protected, masker)
    if provider is None:
        return {"status": "OFFLINE", "mode": "OFFLINE", "model": None, "sent": {"candidates": sent}, "reply": None,
                "proposal": None, "issues": [{"code": "OFFLINE", "message": "Meta 미연결: 열을 직접 연결하세요"}],
                "usage": {}}
    system = PROMPT + ("\n" + MASK_NOTE if protected else "")
    try:
        r = provider.chat([{"role": "system", "content": system},
                           {"role": "user", "content": json.dumps({"candidates": sent}, ensure_ascii=False)}],
                          [], response_format=schema(cands))
        reply = json.loads(r["message"].get("content") or "")
    except (ProviderError, ValueError, KeyError, TypeError) as exc:
        return {"status": "FAILED", "mode": provider.mode, "model": provider.model, "sent": {"candidates": sent},
                "reply": None, "proposal": None, "usage": {},
                "issues": [{"code": "MODEL_FAILED", "message": f"AI 제안 실패 ({type(exc).__name__}): 열을 직접 연결하세요"}]}
    reply = masker.unmask_obj(reply)
    out = {"mode": provider.mode, "model": provider.model, "sent": {"candidates": sent}, "reply": reply,
           "usage": r.get("usage") or {}}
    c = next((x for x in cands if isinstance(reply, dict) and x["id"] == reply.get("candidate_id")), None)
    if c is None:
        return {**out, "status": "INVALID", "proposal": None,
                "issues": [{"code": "OUT_OF_RANGE", "message": "서버가 찾은 표 후보가 아닌 값을 골랐습니다"}]}
    mapping, reasons, issues = {}, {}, []
    for x in reply.get("fields") or []:
        if not isinstance(x, dict) or x.get("field") not in ix.FIELDS or x["field"] in mapping:
            continue
        col = x.get("column")
        if col and col != "NONE" and col not in c["columns"]:
            issues.append({"code": "OUT_OF_RANGE", "field": x["field"], "message": f"{col}열은 후보 {c['id']}에 없음"})
            col = None
        mapping[x["field"]], reasons[x["field"]] = (col if col and col != "NONE" else None), str(x.get("reason", ""))[:300]
    unresolved = [f for f in reply.get("unresolved") or [] if f in ix.FIELDS]
    dup = [i for i in check_mapping(c, mapping) if i["code"] == "DUPLICATE_MAPPING"]
    used: dict[str, list[str]] = {}
    for f, col in mapping.items():
        if col:
            used.setdefault(col, []).append(f)
    for fs in used.values():
        if len(fs) > 1:  # a column given to two fields: neither is trusted
            for f in fs:
                mapping[f] = None
                unresolved.append(f)
    issues += dup + [i for i in check_mapping(c, mapping) if i["code"] == "REQUIRED_NOT_MAPPED"]
    return {**out, "status": "OK", "issues": issues,
            "proposal": {"table": c["id"], "mapping": {k: mapping.get(k) for k in ix.FIELDS}, "reasons": reasons,
                         "unresolved": sorted(set(unresolved))}}


# --- a person's confirmation, saved for the next file of the same structure -------------------------------------
class MappingIn(BaseModel):
    table: str = Field(min_length=1, max_length=10)
    mapping: dict[str, str | None]
    confirmed: list[str] = []  # the uncertain fields the person checked
    proposal_id: int | None = None
    name: str | None = Field(None, max_length=80)
    reason: FreeText


def save(session: Session, body: MappingIn, data: bytes, f, actor) -> dict:
    from app.db import InspectionForm, InspectionMappingProposal
    from app.workflow import now

    cands = tables(data)
    c = next((x for x in cands if x["id"] == body.table), None)
    if c is None:
        raise HTTPException(422, f"표 후보 {body.table}가 이 파일에 없습니다")
    mapping = {k: body.mapping.get(k) or None for k in ix.FIELDS}
    if bad := [i for i in check_mapping(c, {**body.mapping, **mapping})]:
        raise HTTPException(422, bad[0]["message"])
    prop = session.get(InspectionMappingProposal, body.proposal_id) if body.proposal_id else None
    if body.proposal_id and (prop is None or prop.file_id != f.id):
        raise HTTPException(422, "이 파일의 제안이 아닙니다")
    asked = uncertain(c, mapping, data, (prop.proposal or {}).get("unresolved", []) if prop else [])
    if missing := [x["field"] for x in asked if x["field"] not in body.confirmed]:
        raise HTTPException(422, f"확인이 필요한 항목을 확인하지 않았습니다: {', '.join(missing)}")
    name = body.name or f"{c['sheet']} 확인 매핑 {c['structure_sha'][:6]}"
    if name == ix.FORM:
        raise HTTPException(409, "기본 합성 양식 이름은 쓸 수 없습니다")
    prev = session.scalar(select(InspectionForm).where(InspectionForm.name == name)
                          .order_by(InspectionForm.version.desc()).limit(1))
    edits = sum(1 for k in ix.FIELDS if (prop.proposal or {}).get("mapping", {}).get(k) != mapping[k]) \
        if prop and prop.proposal else None
    words = {k: [ix._key(c["columns"][col])] for k, col in mapping.items() if col}
    row = InspectionForm(name=name, version=(prev.version + 1) if prev else 1, fields=words,
                         required=list(ix.REQUIRED), header_search_rows=c["header_rows"][-1], reason=body.reason,
                         created_by=actor.id, created_at=now(), source="CONFIRMED",
                         structure={k: c[k] for k in ("sheet", "header_rows", "columns")},
                         structure_sha=c["structure_sha"], mapping=mapping, proposal_id=prop.id if prop else None,
                         edits=edits)
    session.add(row)
    session.flush()
    out = next(x for x in ix.forms(session) if x["name"] == name)
    return {**out, "form_version": ix.form_version(out), "edits": edits, "table": c["id"]}
