"""How documents reach the model: HYBRID (table of contents + server selection + the model asks for what is
missing, the default) and WHOLE (every element, in pieces when it does not fit)."""

import json

import pytest

from app import docparse, intake_extract, limits
from scripts.select_eval import TRUTH, caught, dossier
from tests.test_intake_in2 import Scripted

EMPTY = {"documents": [], "links": [], "questions": [], "transcriptions": [], "fields": [], "need": []}


def files_of(els, cov=None):
    return [{"file_id": 1, "name": "d.pdf", "tier": "RAW", "elements": els, "coverage": cov or {}, "images": {}}]


def sent_ids(call) -> set[str]:
    blocks = [json.loads(x["text"]) for x in call["messages"][1]["content"] if x["type"] == "text"
              and x["text"].startswith("{")]
    return {e["id"] for b in blocks if "maps" not in b for e in b["elements"]}


def test_round_one_is_small_and_already_holds_most_values():
    from app.doc_select import select

    els, _, _ = docparse.parse("application/pdf", dossier(), docparse.Budget(10_000))
    ids, rep = select(els, list(TRUTH))
    assert sum(caught(els, set(ids)).values()) >= 5 and rep["selected"] < rep["total"] / 20


def test_the_model_sees_the_map_and_gets_only_the_parts_it_asks_for(monkeypatch):
    monkeypatch.setitem(limits.OVERRIDES, "EXTRACT_MODE", "HYBRID")
    els, cov, _ = docparse.parse("application/pdf", dossier(), docparse.Budget(10_000))

    class Counted(Scripted):
        def chat(self, messages, tools, response_format=None, reasoning_effort=None):
            out = super().chat(messages, tools, response_format, reasoning_effort)
            return {**out, "usage": {"prompt_tokens": 100, "completion_tokens": 10}}

    ask = {**EMPTY, "need": [{"file_id": 1, "part": "p115", "why": "deadline"},
                             {"file_id": 1, "part": "p999", "why": "not in the map"}]}
    p = Counted(ask, EMPTY)
    _raw, _, info = intake_extract.extract(p, files_of(els, cov))
    first, second = sent_ids(p.seen[0]), sent_ids(p.seen[1])
    assert '"maps"' in p.seen[0]["messages"][1]["content"][-1]["text"]  # round 1 carries the map
    assert "map of each document" in p.seen[0]["messages"][0]["content"]  # the model is told it may ask
    from app import doc_map

    cont = {e["id"] for e in doc_map.continuation(els, "p115")}  # p116 up to its first heading candidate
    assert second and all(i.startswith("pdf:p115:") or i in cont for i in second) and not first & second
    assert cont <= first | second  # a clause running onto the next page comes with the asked page
    assert caught(els, first | second)["reply_deadline"]
    assert info["rounds"][1]["asked"] == ["1:p115"] and info["usage"]["prompt_tokens"] == 200
    assert "Only these fields are still needed" in p.seen[1]["messages"][0]["content"]


def test_a_protected_files_map_is_masked_but_its_part_names_stay(monkeypatch):
    monkeypatch.setitem(limits.OVERRIDES, "EXTRACT_MODE", "HYBRID")
    els = [{"id": "pdf:p1:l1", "kind": "text", "page": 1, "text": "Customer reference: QX-2026-5512"}]
    p = Scripted(EMPTY)
    intake_extract.extract(p, [{**files_of(els)[0], "tier": "PROTECTED"}])
    sent = json.dumps(p.seen[0]["messages"], ensure_ascii=False)
    shown = json.loads(p.seen[0]["messages"][1]["content"][-1]["text"])["maps"]["1"]
    assert "QX-2026-5512" not in sent and shown["parts"][0]["part"] == "p1"  # askable, but its words are tokens


def test_whole_mode_reads_everything_in_pieces_when_it_does_not_fit(monkeypatch):
    monkeypatch.setitem(limits.OVERRIDES, "EXTRACT_MODE", "WHOLE")
    els, cov, _ = docparse.parse("application/pdf", dossier(), docparse.Budget(10_000))
    p = Scripted(*[EMPTY] * 50)
    _, _, info = intake_extract.extract(p, files_of(els, cov))
    assert info["pieces"] == 1 and len(sent_ids(p.seen[0])) == len(els)  # fits: one call with every element
    monkeypatch.setitem(limits.OVERRIDES, "MODEL_CONTEXT_TOKENS",  # a small model: must split
                        limits.get("MODEL_MAX_OUTPUT_TOKENS") + 20000)
    p = Scripted(*[EMPTY] * 50)
    _, _, info = intake_extract.extract(p, files_of(els, cov))
    got = set().union(*(sent_ids(c) for c in p.seen))
    assert info["pieces"] > 1 and got == {e["id"] for e in els}  # every element, none twice
    assert sum(len(sent_ids(c)) for c in p.seen) == len(els)


def test_hybrid_reports_what_it_left_unread_and_a_person_can_have_it_all_read(tmp_path):
    from tests.test_intake_in1 import PDF_FIXTURE, upload
    from tests.test_intake_in2 import analyze, client
    from tests.v5_util import H

    els, cov, _ = docparse.parse("application/pdf", dossier(), docparse.Budget(10_000))
    _, _, info = intake_extract.extract(Scripted(EMPTY), files_of(els, cov), mode="HYBRID")
    assert info["unread"]["elements"] > 0 and info["unread"]["of"] == len(els) and info["unread"]["missing"]
    p = Scripted(*[EMPTY] * 6)
    c = client(tmp_path, p)
    iid = upload(c, [("c.pdf", PDF_FIXTURE.read_bytes())]).json()["intake_id"]
    first = analyze(c, iid).json()["draft"]["egress"]
    assert first["mode"] == "WHOLE" and first["auto"]["chosen"] == "WHOLE"  # the default WHOLE_FIRST: it fits
    again = c.post(f"/intakes/{iid}/analyze", params={"read": "HYBRID"}, headers=H("alice")).json()["draft"]
    assert again["egress"]["mode"] == "HYBRID" and again["version"] == 2  # a person's choice, a new version


def test_auto_reads_a_short_document_whole_and_a_long_one_by_hybrid_and_records_why(monkeypatch):
    short = [{"id": f"pdf:p1:l{i}", "kind": "text", "page": 1, "text": t} for i, t in
             enumerate(["Customer: Hanbit Motors", "LOT L02, 12 defective boards", "Please reply by 2026-11-07"])]
    mode, why = intake_extract.auto_mode(files_of(short))
    assert mode == "WHOLE" and why["whole"]["usd"] <= why["hybrid_at_most"]["usd"]
    els, cov, _ = docparse.parse("application/pdf", dossier(), docparse.Budget(10_000))  # 120 pages
    mode, why = intake_extract.auto_mode(files_of(els, cov))
    assert mode == "HYBRID" and why["hybrid_at_most"]["usd"] < why["whole"]["usd"]
    monkeypatch.setitem(limits.OVERRIDES, "EXTRACT_MODE", "AUTO")
    p = Scripted(*[EMPTY] * 3)
    _, _, info = intake_extract.extract(p, files_of(short))
    assert info["mode"] == "WHOLE" and info["auto"]["chosen"] == "WHOLE" and len(p.seen) == 1


def test_extract_mode_takes_only_known_values():
    from fastapi import HTTPException

    assert limits.cast("EXTRACT_MODE", "AUTO") == "AUTO"
    with pytest.raises(HTTPException):
        limits.cast("EXTRACT_MODE", "SOMETIMES")


def test_whole_first_reads_all_when_it_fits_one_call_and_hybrid_beyond_the_owners_cap(monkeypatch):
    els, cov, _ = docparse.parse("application/pdf", dossier(), docparse.Budget(10_000))  # 120 pages
    p = Scripted(*[EMPTY] * 3)
    _, _, info = intake_extract.extract(p, files_of(els, cov))  # default WHOLE_FIRST, no cap: fits
    assert info["mode"] == "WHOLE" and len(p.seen) == 1 and info["auto"]["chosen"] == "WHOLE"
    monkeypatch.setitem(limits.OVERRIDES, "MAX_COST_PER_MODEL_CALL_USD", 0.01)  # the owner caps a call at 1 cent
    p = Scripted(*[EMPTY] * 3)
    _, _, info = intake_extract.extract(p, files_of(els, cov))
    assert info["mode"] == "HYBRID" and info["auto"]["whole_input_tokens"] > info["auto"]["max_input_tokens"]


def test_a_contents_page_spelled_with_no_break_spaces_is_found():
    assert docparse.TOC.match("TABLE OF CONTENTS") and docparse.TOC.match("Table of Contents")


def test_the_map_skips_page_numbers_and_running_headers_and_a_page_brings_its_continuation():
    from app import doc_map

    els = [{"id": f"pdf:p{p}:l{i}", "kind": "text", "page": p, "text": t} for p, i, t in [
        (1, 1, "-1-"), (1, 2, "ACME SUPPLY AGREEMENT"), (1, 3, "Confidential draft"),
        (2, 1, "-2-"), (2, 2, "12. Governing Law. This Agreement is governed by the laws of the"), (2, 3, "Confidential draft"),
        (3, 1, "-3-"), (3, 2, "State of New York, without regard to its conflict rules."), (3, 3, "13. Notices"),
        (3, 4, "All notices are given in writing to the addresses below."), (3, 5, "Confidential draft")]]
    m = doc_map.build(els, {})
    assert [x["first"] for x in m["parts"]] == ["ACME SUPPLY AGREEMENT", ("12. Governing Law. This Agreement is governed "
                                                "by the laws of the"), ("State of New York, without regard to its "
                                                "conflict rules.")]
    assert [e["id"] for e in doc_map.continuation(els, "p2")] == ["pdf:p3:l1", "pdf:p3:l2"]  # stops at "13. Notices"
    assert doc_map.continuation(els, "s0") == [] and doc_map.continuation(els, "p3") == []


def test_ai_choice_asks_only_between_feasible_methods_and_records_why(monkeypatch):  # v5.14 AI-CFG-03
    short = [{"id": f"pdf:p1:l{i}", "kind": "text", "page": 1, "text": t} for i, t in
             enumerate(["Customer: Hanbit Motors", "LOT L02, 12 defective boards", "Please reply by 2026-11-07"])]
    monkeypatch.setitem(limits.OVERRIDES, "EXTRACT_MODE", "AI_CHOICE")
    p = Scripted({"method": "HYBRID", "reason": "long appendix tables"}, *[EMPTY] * 3)
    _, _, info = intake_extract.extract(p, files_of(short))
    choose = json.loads(p.seen[0]["messages"][-1]["content"])
    assert choose["candidates"] == ["WHOLE", "HYBRID"] and "Hanbit" not in json.dumps(choose)  # structure, no text
    assert info["mode"] == "HYBRID" and info["auto"]["proposed_by"] == "AI" and info["auto"]["reason"]
    assert all(s["read_method"]["method"] == "HYBRID" for s in info["files"])  # recorded on each file

    p = Scripted({"method": "SKIM", "reason": "x"}, *[EMPTY] * 3)  # outside the candidates: the server's rule
    _, _, info = intake_extract.extract(p, files_of(short))
    assert info["mode"] == "WHOLE" and info["auto"]["proposed_by"] == "SERVER_RULE"

    monkeypatch.setitem(limits.OVERRIDES, "MAX_COST_PER_MODEL_CALL_USD", 1e-7)  # nothing fits the cost cap
    p = Scripted(*[EMPTY] * 3)
    _, _, info = intake_extract.extract(p, files_of(short))
    assert info["mode"] == "HYBRID" and info["auto"]["candidates"] == ["HYBRID"]
    assert not any(s["response_format"]["json_schema"]["name"] == "read_method" for s in p.seen)  # not asked
    assert limits.cast("EXTRACT_MODE", "AI_CHOICE") == "AI_CHOICE"
