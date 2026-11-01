"""Pick the parts of a document worth sending to the model (spec v5.8 §24). No model is involved in choosing.

A whole 400-page file costs as much as its pages, while the values an intake needs sit next to their labels. The
server chooses, and records what it chose and why:
  head      PDF page 1, or for files without pages everything up to the end of the first table: where forms put
            the customer, the reference and the dates
  context   captions and chart data: small, and they tie pictures to text
  field     for each field still needed, the element BM25 ranks best for that field's labels (app/retrieval.py,
            with the multilingual glossary; ties go to the earliest element), with its neighbours: the element
            before and after (a value often sits on the next line), and for a table cell its whole row and the
            table's header row
Round 1 takes the best hit per field; a later round (intake_extract) takes the next hit for fields still missing.
Elements are only ever left out, never altered; what was sent is listed by id.
"""

import hashlib
import json
import re

from app.retrieval import bm25

# Label words per field, in the languages customer documents use. Matching goes through the search glossary, so a
# concept's other wordings match too. Source: the field list of spec §23.3 and the labels of customer complaint,
# 8D and inspection forms. To support a new wording, add it here (the version changes and is recorded).
FIELD_LABELS: dict[str, str] = {
    "customer": "customer client company 고객 고객사 업체 顧客 客户",
    "customer_contact": "contact person name attention 담당자 연락처 担当 联系人",
    "customer_ref": "reference ref number complaint claim no 참조번호 관리번호 클레임 번호 参照 编号",
    "part_number": "part number pn item product model 품번 품명 제품 모델 品番 零件号",
    "lot": "lot batch lot no 로트 LOT 배치 ロット 批次",
    "serial_range": "serial number range sn 일련번호 시리얼 シリアル 序列号",
    "issued_date": "issued date issue 발행일 작성일 発行日 日期",
    "delivery_date": "delivery delivered shipped shipment date 납품 납품일 출하 출하일 納品 交货",
    "found_date": "found detected discovered occurrence date 발견 발견일 발생일 発見 发现",
    "phenomenon": "phenomenon defect symptom failure problem description 현상 불량 증상 내용 現象 不良 现象",
    "found_condition": "found at inspection condition process stage 발견 공정 검사 조건 検査 检验",
    "inspected_qty": "inspected quantity sample size checked total qty 검사 수량 검사수량 모수 検査数 检验数量",
    "defective_qty": "defective quantity ng reject failed qty 불량 수량 불량수 NG 不良数 不良数量",
    "qty_unit": "unit units pcs ea boards 단위 개 대 単位 单位",
    "request": "request requested action required please 요청 요청사항 조치 要求 请求",
    "reply_deadline": "reply by deadline due respond until 회신 기한 마감 까지 回答期限 截止",
    "customer_cause_claim": "cause caused likely suspect think root 원인 추정 의심 原因 推定",
}
# The shape a field's value takes. An element with the label words AND a value of that shape ranks first: the label
# alone also matches sentences that only mention the word ("please reply soon"). Standard in document extraction.
DATE = (r"\d{4}[-./]\d{1,2}[-./]\d{1,2}|\d{1,2}[-./]\d{1,2}[-./]\d{2,4}|\d{1,2}\s*(?:월|月)|"
        r"(?i:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}|"
        r"(?i:mon|tues|wednes|thurs|fri|satur|sun)day|[월화수목금토일]요일")
NUMBER = r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w.])"
CODE = (r"\b(?=[A-Za-z0-9-]*\d)(?=[A-Za-z0-9-]*[A-Za-z])[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+\b"
        r"|\b[A-Z]{1,3}\d{2,}\b")
SHAPE = {"issued_date": DATE, "delivery_date": DATE, "found_date": DATE, "reply_deadline": DATE,
         "inspected_qty": NUMBER, "defective_qty": NUMBER, "customer_ref": CODE, "part_number": CODE, "lot": CODE,
         "serial_range": CODE}
LABELS_VERSION = hashlib.sha256(json.dumps([FIELD_LABELS, SHAPE], ensure_ascii=False, sort_keys=True).encode()
                                ).hexdigest()[:10]


def head(elements: list[dict]) -> list[str]:
    if any("page" in e for e in elements):
        return [e["id"] for e in elements if e.get("page") == 1]
    out, in_table = [], False
    for e in elements:
        if e["kind"] == "cell":
            in_table = True
        elif in_table:  # the first table has ended
            break
        out.append(e["id"])
    return out


def around(elements: list[dict], i: int) -> list[str]:
    """The element, the one before and after, and for a table cell its row, the table's first row and its column
    (a label in a header cell has its values below it)."""
    e = elements[i]
    ids = [x["id"] for x in elements[max(0, i - 1):i + 2]]
    if e["kind"] == "cell":
        same = [x for x in elements if x["kind"] == "cell" and x.get("table") == e.get("table")
                and x.get("sheet") == e.get("sheet") and x.get("page") == e.get("page")]
        first = min((x["row"] for x in same), default=e["row"])
        ids += [x["id"] for x in same if x["row"] in (e["row"], first) or x.get("col") == e.get("col")]
    return ids


def ranked(elements: list[dict], field: str) -> list[int]:
    """Indexes of the elements that share a label term with the field: those whose neighbourhood also holds a value
    of the field's shape first, then by BM25 score, a table cell before a plain line, the earliest on a tie."""
    scores = bm25(FIELD_LABELS[field], [e.get("text", "") for e in elements])
    shape = SHAPE.get(field)

    def shaped(i: int) -> bool:
        if shape is None:
            return False
        near = [elements[k].get("text", "") for k in range(max(0, i - 1), min(len(elements), i + 2))]
        if elements[i]["kind"] == "cell":  # the column below a header label
            near += [x.get("text", "") for x in elements if x["kind"] == "cell" and x.get("col") == elements[i].get("col")
                     and x.get("table") == elements[i].get("table") and x.get("page") == elements[i].get("page")]
        return any(re.search(shape, t) for t in near)
    hits = [(s, i) for i, (s, _) in enumerate(scores) if s > 0]
    return [i for _, i in sorted(hits, key=lambda h: (not shaped(h[1]), -h[0], elements[h[1]]["kind"] != "cell",
                                                      h[1]))]


def select(elements: list[dict], fields: list[str], skip_hits: dict[str, int] | None = None,
           base: bool = True) -> tuple[list[str], dict]:
    """(element ids to send, in document order; report). skip_hits[field] = how many of its best hits earlier
    rounds already used, so this round takes the next one."""
    skip_hits = skip_hits or {}
    why: dict[str, str] = {}
    if base:
        for eid in head(elements):
            why.setdefault(eid, "head")
        for e in elements:
            if e["kind"] in ("chart", "scan_page") or e.get("caption_id") or (e["kind"] == "text" and any(
                    x.get("caption_id") == e["id"] for x in elements)):
                why.setdefault(e["id"], "context")
    used: dict[str, str | None] = {}
    for f in fields:
        order = ranked(elements, f)
        k = skip_hits.get(f, 0)
        used[f] = elements[order[k]]["id"] if k < len(order) else None
        if k < len(order):
            for eid in around(elements, order[k]):
                why.setdefault(eid, f"field:{f}")
    chosen = [e["id"] for e in elements if e["id"] in why]
    return chosen, {"labels_version": LABELS_VERSION, "selected": len(chosen), "total": len(elements),
                    "hits": used, "reasons": {r: sum(v == r for v in why.values()) for r in set(why.values())}}
