"""Inspection-result XLSX (spec v5.12 §28, XLS-IN-01..05): preview, a rule-based column mapping a person confirms,
row checks, an idempotent versioned import into a case as internal inspection evidence, and reconciliation with
the customer's documents. One reference form (a synthetic one here); nothing claims real company forms.

Never: execute formulas, macros or links (cached values only; a formula without a cached value blocks the row),
fill a missing value with 0, drop a duplicate, guess a lost leading zero, or promote a customer's number to an
internal inspection fact. Every value keeps its file hash, sheet, cell, raw value, number format and the mapping
version it was read with.
"""

import hashlib
import io
import json
import re
from datetime import date, datetime

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.fields import FreeText

FORM = "inspection_results_v1"  # the one supported form: one row per LOT (and item), quantities per row
FIELDS = {  # field -> header words (lower case, spaces removed) of the reference form and its usual wordings
    "part_number": ("품번", "부품번호", "partno", "partnumber", "pn", "itemcode"),
    "lot": ("lot", "로트", "lotno", "lot번호", "로트번호"),
    "inspected_on": ("검사일", "검사일자", "inspectiondate", "date", "일자"),
    "inspected_qty": ("검사수량", "검사수", "inspectedqty", "inspected", "samplesize", "수량"),
    "defective_qty": ("불량수량", "불량수", "defectiveqty", "defective", "ngqty", "ng"),
    "item": ("측정항목", "항목", "item", "characteristic"),
    "value": ("측정값", "value", "measured"),
    "unit": ("단위", "unit"),
}
REQUIRED = ("lot", "inspected_qty", "defective_qty")  # the built-in form's contract
BUILTIN = {"name": FORM, "version": 1, "fields": {k: list(v) for k, v in FIELDS.items()}, "required": list(REQUIRED),
           "header_search_rows": 20, "builtin": True}


def form_version(form: dict) -> str:
    """The id of a form definition: its name, version, header words and required fields (stored on each import)."""
    return hashlib.sha256(json.dumps([form["name"], form["version"], form["fields"], form["required"]],
                                     ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]


MAPPING_VERSION = form_version(BUILTIN)


def forms(session: Session) -> list[dict]:
    """The built-in synthetic form and, per name, the latest version a person registered (append-only)."""
    from app.db import InspectionForm

    latest: dict[str, dict] = {}
    for f in session.scalars(select(InspectionForm).order_by(InspectionForm.id)):
        latest[f.name] = {"name": f.name, "version": f.version, "fields": f.fields, "required": f.required,
                          "header_search_rows": f.header_search_rows, "builtin": False, "reason": f.reason,
                          "created_by": f.created_by, "created_at": f.created_at, "source": f.source,
                          "structure": f.structure, "structure_sha": f.structure_sha, "mapping": f.mapping,
                          "edits": f.edits, "proposal_id": f.proposal_id}
    return [BUILTIN, *latest.values()]


class FormIn(BaseModel):
    """A company form: header words per field (blank fields are simply not used), required fields, reason."""
    name: str = Field(min_length=1, max_length=80)
    fields: dict[str, list[str]]
    required: list[str]
    header_search_rows: int = Field(20, ge=1, le=200)
    reason: FreeText


def register(session: Session, body: FormIn, actor) -> dict:
    from app.db import InspectionForm
    from app.workflow import now

    if unknown := sorted(set(body.fields) - set(FIELDS)):
        raise HTTPException(422, f"모르는 필드: {unknown} (가능: {sorted(FIELDS)})")
    words = {k: [_key(w) for w in v if _key(w)] for k, v in body.fields.items()}
    words = {k: v for k, v in words.items() if v}  # a blank field is left out, not an error
    if missing := [f for f in body.required if f not in words]:
        raise HTTPException(422, f"필수 필드에 헤더 단어가 없습니다: {missing}")
    if "lot" not in body.required:
        raise HTTPException(422, "LOT는 필수여야 합니다 (대조·근거 연결의 기준)")
    if body.name == FORM:
        raise HTTPException(409, "기본 합성 양식 이름은 쓸 수 없습니다")
    prev = session.scalar(select(InspectionForm).where(InspectionForm.name == body.name)
                          .order_by(InspectionForm.version.desc()).limit(1))
    row = InspectionForm(name=body.name, version=(prev.version + 1) if prev else 1, fields=words,
                         required=list(dict.fromkeys(body.required)), header_search_rows=body.header_search_rows,
                         reason=body.reason, created_by=actor.id, created_at=now())
    session.add(row)
    session.flush()
    out = next(f for f in forms(session) if f["name"] == body.name)
    return {**out, "form_version": form_version(out)}
AMBIGUOUS_DATE = re.compile(r"^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$")  # 03/04/2026: day or month first?
THOUSANDS = re.compile(r"^\d{1,3}(,\d{3})+$")


def _key(text) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _workbook(data: bytes):
    import openpyxl

    try:
        values = openpyxl.load_workbook(io.BytesIO(data), data_only=True, keep_links=False)
        formulas = openpyxl.load_workbook(io.BytesIO(data), data_only=False, keep_links=False)
    except Exception as exc:  # noqa: BLE001 (any broken or encrypted file: say why and stop)
        raise HTTPException(422, f"XLSX를 읽을 수 없습니다 (손상·암호화·미지원 형식: {type(exc).__name__})") from None
    return values, formulas


def suggest(headers: dict[str, str], fields: dict | None = None) -> dict[str, str | None]:
    """field -> column letter by the form's header words; a suggestion until a person confirms it."""
    out: dict[str, str | None] = {}
    taken: set[str] = set()
    for field, words in (fields or FIELDS).items():
        out[field] = next((col for col, h in headers.items() if col not in taken and _key(h) in words), None)
        if out[field]:
            taken.add(out[field])
    return out


def header_row(ws, limit: int = 20, fields: dict | None = None) -> int | None:
    """The first row (within the first `limit`) that names at least two of the form's fields."""
    for r in range(1, min(ws.max_row, limit) + 1):
        heads = {c.column_letter: c.value for c in ws[r] if c.value is not None}
        if sum(1 for v in suggest(heads, fields).values() if v) >= 2:
            return r
    return None


def best_form(ws, candidates: list[dict]) -> tuple[dict, int | None]:
    """The form whose header words name the most columns of this sheet (the built-in form on a tie)."""
    scored = []
    for f in candidates:
        r = header_row(ws, f["header_search_rows"], f["fields"])
        heads = {c.column_letter: c.value for c in ws[r] if c.value is not None} if r else {}
        scored.append((sum(1 for v in suggest(heads, f["fields"]).values() if v), not f["builtin"], f, r))
    _, _, f, r = max(scored, key=lambda x: (x[0], not x[1]))
    return f, r


def _cell(ws_v, ws_f, ref: str) -> dict:
    cv, cf = ws_v[ref], ws_f[ref]
    formula = isinstance(cf.value, str) and cf.value.startswith("=")
    return {"cell": ref, "raw": cv.value if not isinstance(cv.value, (datetime, date)) else cv.value.isoformat(),
            "type": cv.data_type, "format": cv.number_format, "formula": formula}


def _normalize(field: str, c: dict, required=REQUIRED) -> tuple[object, list[dict]]:
    """(normalized value, issues) for one cell; the raw value stays beside it, never overwritten."""
    raw, issues = c["raw"], []

    def issue(level: str, code: str, msg: str):
        issues.append({"level": level, "code": code, "field": field, "cell": c["cell"], "message": msg})

    if c["formula"]:
        if raw is None:
            issue("BLOCK", "FORMULA_NO_CACHE", "수식 칸에 저장된 값이 없습니다 (재계산하지 않음): 파일을 저장해 다시 올리세요")
            return None, issues
        issue("INFO", "FORMULA_CACHED", "수식의 저장된 값입니다 (재계산하지 않음, 최신 여부 미확인)")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if field in required:
            issue("BLOCK", "MISSING", "필수 값이 비어 있습니다 (0으로 채우지 않음)")
        return None, issues
    if field in ("lot", "part_number"):
        if isinstance(raw, str):
            return raw.strip(), issues
        if isinstance(raw, float) and not raw.is_integer():
            issue("BLOCK", "ID_NOT_TEXT", "식별자가 소수로 저장돼 있습니다")
            return None, issues
        text = str(int(raw))
        if len(text) > 15:
            issue("BLOCK", "PRECISION_LOST", "숫자로 저장된 긴 식별자: 자릿수가 이미 손실됐을 수 있습니다")
            return None, issues
        fmt = c["format"] or ""
        if re.fullmatch(r"0+", fmt):  # the cell shows the zeros itself ("00042"): the format says how many
            issue("INFO", "LEADING_ZERO_FROM_FORMAT", f"표시 형식 {fmt}의 자릿수로 읽었습니다")
            return text.zfill(len(fmt)), issues
        issue("WARN", "LEADING_ZERO_UNKNOWN", f"숫자로 저장된 식별자 {text}: 앞자리 0이 있었는지 알 수 없습니다 (복원하지 않음)")
        return text, issues
    if field == "inspected_on":
        if c["type"] == "d" or isinstance(raw, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}(T.*)?", raw):
            return str(raw)[:10], issues
        if isinstance(raw, str) and AMBIGUOUS_DATE.match(raw.strip()):
            issue("WARN", "DATE_AMBIGUOUS", f"날짜 {raw}: 일·월 순서가 불명확합니다 (사람 확인 필요)")
            return None, issues
        issue("WARN", "INVALID_DATE", f"날짜로 읽을 수 없습니다: {raw!r}")
        return None, issues
    if field in ("inspected_qty", "defective_qty", "value"):
        v = raw
        if isinstance(raw, str):
            s = raw.strip()
            if THOUSANDS.match(s):
                issue("WARN", "NUMBER_AS_TEXT", f"글자로 저장된 숫자 {s} (쉼표를 천 단위로 읽음)")
                s = s.replace(",", "")
            try:
                v = float(s)
            except ValueError:
                issue("BLOCK" if field != "value" else "WARN", "NOT_A_NUMBER", f"숫자가 아닙니다: {raw!r}")
                return None, issues
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            issue("BLOCK", "NOT_A_NUMBER", f"숫자가 아닙니다: {raw!r}")
            return None, issues
        if field != "value":
            if v < 0:
                issue("BLOCK", "NEGATIVE", "수량이 음수입니다")
                return None, issues
            if float(v) != int(v):
                issue("BLOCK", "NON_INTEGER", "수량이 정수가 아닙니다")
                return None, issues
            return int(v), issues
        return float(v), issues
    return str(raw).strip(), issues


def read(data: bytes, file_sha256: str, sheet: str | None = None, header: int | None = None,
         mapping: dict[str, str | None] | None = None, candidates: list[dict] | None = None,
         form_name: str | None = None, last_row: int | None = None) -> dict:
    """Preview and row checks: sheets, the header row, columns, a suggested mapping and every data row with its
    cells, normalized values and issues. Hidden rows are excluded by default and listed."""
    from app import docparse

    wb_v, wb_f = _workbook(data)
    budget = docparse.Budget()
    sheets = [{"name": ws.title, "hidden": ws.sheet_state != "visible", "rows": ws.max_row, "cols": ws.max_column}
              for ws in wb_v.worksheets]
    names = [s["name"] for s in sheets]
    if not names:
        raise HTTPException(422, "시트가 없는 파일입니다")
    chosen = next((f for f in candidates or [] if f["name"] == form_name), None) if form_name else None
    if chosen and chosen.get("structure_sha"):  # a confirmed mapping holds only for the structure it was made on
        from app.inspection_layout import tables

        match = next((t for t in tables(data) if t["structure_sha"] == chosen["structure_sha"]), None)
        if match is None:
            raise HTTPException(422, f"저장된 매핑 {form_name}과 표 구조가 다릅니다: 다시 검토하세요")
        sheet, last_row = match["sheet"], last_row or match["last_row"]
    sheet = sheet or next((s["name"] for s in sheets if not s["hidden"]), names[0])
    if sheet not in names:
        raise HTTPException(422, f"시트 {sheet!r}가 없습니다")
    ws_v, ws_f = wb_v[sheet], wb_f[sheet]
    candidates = candidates or [BUILTIN]
    if form_name:
        form = next((f for f in candidates if f["name"] == form_name), None)
        if form is None:
            raise HTTPException(422, f"등록되지 않은 양식: {form_name}")
        # a confirmed mapping (§29) knows its header row; a word form searches for it
        header = header or (form["header_search_rows"] if form.get("mapping") else
                            header_row(ws_v, form["header_search_rows"], form["fields"]))
    else:
        form, found = best_form(ws_v, candidates)
        header = header or found
    fields, required = form["fields"], tuple(form["required"])
    form_info = {"name": form["name"], "version": form["version"], "form_version": form_version(form),
                 "builtin": form["builtin"], "required": list(required),
                 "candidates": [f["name"] for f in candidates]}
    if header is None:
        return {"form": form_info, "sheets": sheets, "sheet": sheet, "header_row": None, "columns": {}, "rows": [],
                "suggested_mapping": {}, "mapping": {}, "issues": [{"level": "BLOCK", "code": "NO_HEADER",
                                                                     "message": "양식의 헤더 행을 찾지 못했습니다"}]}
    columns = {c.column_letter: c.value for c in ws_v[header] if c.value is not None}
    suggested = form.get("mapping") or suggest(columns, fields)
    mapping = mapping or suggested
    rows, stopped = [], None
    for r in range(header + 1, (last_row or ws_v.max_row) + 1):  # last_row: the table's end (§29 candidates)
        if budget.spent(f"row {r}"):
            stopped = r
            break
        cells, values, issues = {}, {}, []
        for field, col in mapping.items():
            if not col:
                continue
            c = _cell(ws_v, ws_f, f"{col}{r}")
            v, iss = _normalize(field, c, required)
            cells[field], values[field] = c, v
            issues += iss
        if all(c["raw"] is None for c in cells.values()):
            continue  # an empty row is not data
        hidden = bool(ws_v.row_dimensions[r].hidden)
        if values.get("inspected_qty") is not None and values.get("defective_qty") is not None \
                and values["defective_qty"] > values["inspected_qty"]:
            issues.append({"level": "BLOCK", "code": "DEFECTIVE_EXCEEDS_INSPECTED", "field": "defective_qty",
                           "cell": cells["defective_qty"]["cell"], "message": "불량 수량이 검사 수량보다 많습니다"})
        rows.append({"row": r, "hidden": hidden, "cells": cells, "values": values, "issues": issues})
    seen: dict[tuple, int] = {}
    for x in rows:  # possible re-measurements: shown, never dropped
        k = (x["values"].get("lot"), x["values"].get("inspected_on"), x["values"].get("item"))
        if k[0] is not None and k in seen:
            x["issues"].append({"level": "WARN", "code": "DUPLICATE_CANDIDATE", "field": "lot",
                                "cell": x["cells"]["lot"]["cell"], "message": f"{seen[k]}행과 같은 LOT·검사일·항목"})
        seen.setdefault(k, x["row"])
    units = {x["values"].get("unit") for x in rows if x["values"].get("unit")}
    if len(units) > 1:
        for x in rows:
            if x["values"].get("unit"):
                x["issues"].append({"level": "WARN", "code": "UNIT_MIXED", "field": "unit", "cell": x["cells"]["unit"]["cell"],
                                    "message": f"파일 안에 단위가 섞여 있습니다: {', '.join(sorted(units))}"})
    missing = [f for f in required if not mapping.get(f)]
    return {"form": form_info, "mapping_version": form_info["form_version"], "file_sha256": file_sha256,
            "sheets": sheets,
            "sheet": sheet, "header_row": header, "columns": columns, "suggested_mapping": suggested,
            "mapping": mapping, "rows": rows, "stopped_at_row": stopped,
            "issues": [{"level": "BLOCK", "code": "REQUIRED_NOT_MAPPED", "message": f"필수 열 미연결: {', '.join(missing)}"}]
            if missing else [],
            "note": "AI·규칙 추천은 제안입니다. 사람이 열 연결과 포함 행을 확인해야 사건에 연결됩니다."}


class ImportIn(BaseModel):
    intake_id: int
    file_id: int
    file_sha256: str = Field(min_length=64, max_length=64)  # the file the person looked at
    sheet: str = Field(max_length=120)
    header_row: int = Field(ge=1)
    mapping: dict[str, str | None]
    include_rows: list[int]
    exclude: dict[str, str] = {}  # row -> reason; every data row is included or excluded with a reason
    form: str | None = None  # the form the person confirmed (None: the best match, as the preview showed)


def confirm(session: Session, case_id: str, body: ImportIn, f, actor) -> tuple[int, dict]:
    """A person's confirmation: re-read on the server, refuse BLOCK rows and unexplained rows, and store the import
    as a new version (the same file, mapping and rows again returns the existing one)."""
    from app import egress
    from app.db import Evidence, InspectionImport, SourceAsset, SourceEvent
    from app.workflow import log, now

    data = f.content
    origin = f.data_origin  # the file's own origin and egress tier, as customer documents (intake_case) do
    sensitivity = "APPROVED_FOR_EXTERNAL" if egress.tier_of(session, f) == "RAW" else "UNKNOWN"

    if set(body.mapping) - set(FIELDS):
        raise HTTPException(422, f"모르는 필드: {sorted(set(body.mapping) - set(FIELDS))}")
    view = read(data, body.file_sha256, body.sheet, body.header_row, body.mapping, forms(session), body.form)
    version_of_form = view["mapping_version"]
    if view["issues"]:
        raise HTTPException(422, view["issues"][0]["message"])
    rows = {x["row"]: x for x in view["rows"]}
    inc, exc = set(body.include_rows), {int(k): v for k, v in body.exclude.items() if str(v).strip()}
    if unknown := sorted((inc | set(exc)) - set(rows)):
        raise HTTPException(422, f"데이터 행이 아닙니다: {unknown[:10]}")
    if both := sorted(inc & set(exc)):
        raise HTTPException(422, f"포함과 제외에 모두 있는 행: {both[:10]}")
    if unexplained := sorted(set(rows) - inc - set(exc)):
        raise HTTPException(422, f"포함도 제외(사유)도 아닌 행: {unexplained[:10]} (분모가 불명확해집니다)")
    if blocked := sorted(r for r in inc if any(i["level"] == "BLOCK" for i in rows[r]["issues"])):
        raise HTTPException(422, f"BLOCK 오류가 있는 행은 포함할 수 없습니다: {blocked[:10]}")
    sig = hashlib.sha256(json.dumps([case_id, body.file_sha256, body.sheet, body.header_row, body.mapping,
                                     sorted(inc), sorted(exc.items()), version_of_form], sort_keys=True).encode()
                         ).hexdigest()
    if (same := session.scalar(select(InspectionImport).where(InspectionImport.case_id == case_id,
                                                              InspectionImport.signature == sig))):
        return 200, import_out(same)
    prev = session.scalar(select(InspectionImport).where(InspectionImport.case_id == case_id,
                                                         InspectionImport.file_id == body.file_id)
                          .order_by(InspectionImport.version.desc()).limit(1))
    version = (prev.version + 1) if prev else 1
    imp = InspectionImport(case_id=case_id, intake_id=body.intake_id, file_id=body.file_id,
                           file_sha256=body.file_sha256, sheet=body.sheet, header_row=body.header_row,
                           mapping=body.mapping, mapping_version=version_of_form, form=view["form"]["name"],
                           included_rows=sorted(inc),
                           excluded={str(k): v for k, v in sorted(exc.items())},
                           rows=[rows[r] for r in sorted(inc)], version=version,
                           supersedes_id=prev.id if prev else None, signature=sig, created_by=actor.id,
                           created_at=now())
    session.add(imp)
    session.flush()
    asset = SourceAsset(case_id=case_id, asset_id=f"inspection-xlsx:{imp.id}", source_system="INSPECTION_XLSX",
                        entity_type="INSPECTION_RESULTS", source_version=version,
                        supersedes_asset_id=f"inspection-xlsx:{prev.id}" if prev else None,
                        license_id="INTERNAL", data_origin=origin, sensitivity=sensitivity,
                        captured_at=now(), ingested_at=now(), content_sha256=body.file_sha256,
                        raw_json=json.dumps({"import_id": imp.id, "file_id": body.file_id, "sheet": body.sheet}))
    session.add(asset)
    session.flush()
    ids = []
    for r in sorted(inc):
        x = rows[r]
        record = {**x["values"], "row": r, "sheet": body.sheet, "original_row_id": f"{body.sheet}!{r}", "cells": {f: c["cell"] for f, c in x["cells"].items()},
                  "raw": {f: c["raw"] for f, c in x["cells"].items()}, "file_sha256": body.file_sha256,
                  "mapping_version": version_of_form, "form": view["form"]["name"], "import_id": imp.id,
                  "import_version": version}
        raw = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
        ev = SourceEvent(case_id=case_id, source_asset_id=asset.id, event_id=f"XL{imp.id}-{r}",
                         original_row_id=f"{body.sheet}!{r}", entity_type="inspection_results",
                         entity_key=[x["values"].get("lot")], event_time=now(), source_updated_at=None,
                         ingested_at=now(), data_origin=origin, sensitivity=sensitivity,
                         validation_status="HUMAN_CONFIRMED_IMPORT", raw_json=raw)
        session.add(ev)
        session.flush()
        session.add(Evidence(case_id=case_id, source_event_id=ev.id, evidence_id=f"EV-XL{imp.id}-{r}",
                             classification="OBSERVED", validity="CHECKED",  # a person confirmed the row
                             content_sha256=hashlib.sha256(raw.encode()).hexdigest()))
        ids.append(f"EV-XL{imp.id}-{r}")
    imp.evidence_ids = ids
    log(session, case_id, actor, "INSPECTION_IMPORTED", f"import{imp.id} v{version} rows={len(inc)} "
        f"excluded={len(exc)} file={body.file_sha256[:12]} form={view['form']['name']} mapping={version_of_form}")
    return 201, import_out(imp)


def import_out(imp) -> dict:
    return {"import_id": imp.id, "case_id": imp.case_id, "version": imp.version, "supersedes_id": imp.supersedes_id,
            "file_id": imp.file_id, "file_sha256": imp.file_sha256, "sheet": imp.sheet, "header_row": imp.header_row,
            "mapping": imp.mapping, "mapping_version": imp.mapping_version, "form": imp.form,
            "included_rows": imp.included_rows,
            "excluded": imp.excluded, "denominator": {"included": len(imp.included_rows),
                                                      "excluded": len(imp.excluded)},
            "evidence_ids": imp.evidence_ids, "created_by": imp.created_by, "created_at": imp.created_at}


def reconcile(session: Session, case_id: str, imp, comparable: set[str]) -> dict:
    """Customer document values vs this import, by LOT (and part number). Quantities are compared only when a person
    confirmed they mean the same thing over the same scope (`comparable`); otherwise NOT_COMPARABLE. Server sums."""
    from app.calculations import compute
    from app.db import Evidence, SourceEvent

    customer: dict[str, list[dict]] = {}
    for ev, se in session.execute(select(Evidence, SourceEvent).join(SourceEvent, Evidence.source_event_id == SourceEvent.id)
                                  .where(Evidence.case_id == case_id, SourceEvent.entity_type == "CUSTOMER_REPORT")):
        rec = json.loads(se.raw_json)
        customer.setdefault(rec["field"], []).append({"value": rec["value"], "evidence_id": ev.evidence_id,
                                                      "file": rec.get("file"), "element_id": rec.get("element_id"),
                                                      "page": rec.get("page")})
    rows = imp.rows
    by_lot: dict[str, list[dict]] = {}
    for x, ev in zip(rows, imp.evidence_ids, strict=True):
        by_lot.setdefault(str(x["values"].get("lot")), []).append({**x, "evidence_id": ev})

    def side(x):
        return {"evidence_id": x["evidence_id"], "sheet": imp.sheet, "row": x["row"],
                "cells": {f: c["cell"] for f, c in x["cells"].items()}}

    out = []
    lots = customer.get("lot", [])
    if not lots:
        out.append({"field": "lot", "status": "MISSING", "reason": "고객 문서에 LOT 확정값이 없습니다", "customer": [],
                    "inspection": [side(x) for xs in by_lot.values() for x in xs]})
    for c in lots:
        hits = by_lot.get(str(c["value"]), [])
        out.append({"field": "lot", "status": "MATCH" if hits else "MISMATCH", "customer": [c],
                    "inspection": [side(x) for x in hits],
                    "reason": None if hits else f"검사 파일에 LOT {c['value']}이(가) 없습니다 (있는 LOT: {', '.join(sorted(by_lot))})"})
        for field in ("inspected_qty", "defective_qty"):
            cust = customer.get(field, [])
            if not hits or not cust:
                out.append({"field": field, "lot": c["value"], "status": "MISSING" if hits else "NOT_COMPARABLE",
                            "reason": "고객 값 없음" if hits else "LOT가 맞지 않아 비교하지 않습니다", "customer": cust,
                            "inspection": [side(x) for x in hits]})
                continue
            if field not in comparable:
                out.append({"field": field, "lot": c["value"], "status": "NOT_COMPARABLE", "customer": cust,
                            "inspection": [side(x) for x in hits],
                            "reason": "같은 의미·검사 범위·기간인지 사람이 확인하기 전에는 비교하지 않습니다"})
                continue
            if len(hits) > 1 and len({x["values"].get("inspected_on") for x in hits}) > 1:
                out.append({"field": field, "lot": c["value"], "status": "AMBIGUOUS", "customer": cust,
                            "inspection": [side(x) for x in hits], "reason": "같은 LOT에 검사일이 다른 행이 여러 개입니다"})
                continue
            calc = compute(session, case_id, "sum", [x["evidence_id"] for x in hits], field)
            values = {str(v["value"]).strip() for v in cust}
            status = "AMBIGUOUS" if len(values) > 1 else "MATCH" if float(next(iter(values))) == calc["value"] \
                else "MISMATCH"
            out.append({"field": field, "lot": c["value"], "status": status, "customer": cust,
                        "inspection": [side(x) for x in hits], "calculation_id": calc["calculation_id"],
                        "inspection_value": calc["value"],
                        "reason": "고객 값이 여러 개입니다" if status == "AMBIGUOUS" else None,
                        "note": "고객 보고 수량은 내부 검사 사실로 바뀌지 않으며, 불일치는 자동으로 고치지 않습니다"})
    return {"import_id": imp.id, "import_version": imp.version, "comparable": sorted(comparable), "items": out}
