"""Server-side selection of what goes to the model (app/doc_select.py) and the second round for missing fields."""

import json

from app import docparse, intake_extract
from scripts.select_eval import TRUTH, caught, dossier
from tests.test_intake_in2 import Scripted


def test_a_long_document_is_cut_to_the_parts_that_hold_the_values():
    from app.doc_select import select

    els, _, _ = docparse.parse("application/pdf", dossier(), docparse.Budget(10_000))
    ids, rep = select(els, list(TRUTH))
    assert all(caught(els, set(ids)).values())  # every planted value is in round 1
    assert rep["selected"] < rep["total"] / 20  # and far less than the whole document


def test_round_two_asks_only_for_missing_fields_with_parts_not_sent_before():
    els, _, _ = docparse.parse("application/pdf", dossier(), docparse.Budget(10_000))
    files = [{"file_id": 1, "name": "d.pdf", "tier": "RAW", "elements": els, "images": {}}]
    empty = {"documents": [], "links": [], "questions": [], "transcriptions": [], "fields": []}

    class Counted(Scripted):
        def chat(self, messages, tools, response_format=None, reasoning_effort=None):
            out = super().chat(messages, tools, response_format, reasoning_effort)
            return {**out, "usage": {"prompt_tokens": 100, "completion_tokens": 10}}

    p = Counted(empty, empty)
    _, _, info = intake_extract.extract(p, files)
    first, second = ({e["id"] for part in call["messages"][1]["content"] if part["type"] == "text"
                      for e in json.loads(part["text"])["elements"]} for call in p.seen)
    assert len(p.seen) == 2 and info["rounds"] == 2 and not first & second  # nothing sent twice
    assert "Only these fields are still needed" in p.seen[1]["messages"][0]["content"]
    assert "Only these" not in p.seen[0]["messages"][0]["content"]
    assert info["usage"] == {"prompt_tokens": 200, "completion_tokens": 20}


def test_the_number_of_rounds_is_a_setting(monkeypatch):
    from app import limits

    monkeypatch.setitem(limits.OVERRIDES, "EXTRACT_MAX_ROUNDS", 1)
    els, _, _ = docparse.parse("application/pdf", dossier(), docparse.Budget(10_000))
    p = Scripted({"documents": [], "links": [], "questions": [], "fields": []})
    intake_extract.extract(p, [{"file_id": 1, "name": "d.pdf", "tier": "RAW", "elements": els, "images": {}}])
    assert len(p.seen) == 1
