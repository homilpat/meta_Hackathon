"""Egress tiers (spec §23.5): an unapproved file leaves only masked and without images, an approved one as is, and
with an in-house model configured nothing leaves at all."""

import io
import json

from app import intake
from app.egress import Masker
from app.model_provider import LocalProvider
from tests.test_intake_in1 import PDF_FIXTURE, own_pdf, upload
from tests.test_intake_in2 import Scripted, analyze, client
from tests.v5_util import H

SECRET = "a customer file that is not a shipped fixture"


class Echo(Scripted):
    """Answers with the masked text it was shown for the protected file, as a model copying tokens would."""

    def chat(self, messages, tools, response_format=None, reasoning_effort=None):
        self.seen.append({"messages": messages, "response_format": response_format})
        parts = messages[1]["content"]
        shown = [json.loads(x["text"]) for x in parts if x["type"] == "text" and x["text"].startswith("{")]
        line = next(e for f in shown for e in f["elements"] if e["kind"] == "text")
        out = {"documents": [], "links": [], "questions": [], "transcriptions": [],
               "fields": [{"field": "phenomenon", "value": line["text"],
                           "sources": [{"element_id": line["id"], "excerpt": line["text"]}]}]}
        return {"message": {"role": "assistant", "content": json.dumps(out)}, "usage": {}}


def test_masking_keeps_form_words_and_maps_every_token_back():
    m = Masker()
    text = "Customer: Hanbit Motors  LOT: L02  Defective qty 12 on 2026-10-28, open solder joint on U7"
    masked = m.mask(text)
    for word in ("Hanbit", "Motors", "L02", "12", "2026-10-28", "open", "solder", "joint", "U7"):
        assert word not in masked, word
    assert masked.startswith("Customer: [T1] [T2]") and "LOT: [T3]" in masked and "[D1]" in masked
    assert m.mask("Hanbit") == "[T1]" and m.unmask(masked) == text  # same word, same token; exact round trip


def test_an_unapproved_file_goes_masked_without_images_and_its_values_come_back_checked(tmp_path):
    p = Echo()
    c = client(tmp_path, p)
    iid = upload(c, [("mine.pdf", own_pdf())]).json()["intake_id"]
    d = analyze(c, iid).json()["draft"]
    sent = json.dumps(p.seen[0]["messages"], ensure_ascii=False)
    assert SECRET not in sent and "mine.pdf" not in sent and "image_url" not in sent
    assert "Copy tokens exactly" in p.seen[0]["messages"][0]["content"]
    assert d["egress"]["files"] == [{"file_id": d["egress"]["files"][0]["file_id"], "name": "mine.pdf",
                                     "sent": "MASKED"}]
    assert SECRET not in d["egress"]["masked_payload"]["text"] and len(d["egress"]["masked_payload"]["sha256"]) == 64
    assert d["fields"]["phenomenon"]["status"] == "FOUND" and d["fields"]["phenomenon"]["value"] == SECRET


def test_a_quality_manager_approves_external_processing_and_then_the_file_goes_as_is(tmp_path):
    p = Echo()
    c = client(tmp_path, p)
    data = own_pdf()
    body = upload(c, [("mine.pdf", data)]).json()
    iid, fid = body["intake_id"], body["files"][0]["file_id"]
    ask = c.post(f"/intakes/{iid}/files/{fid}/egress-request", json={"reason": "고객 동의서 확인"}, headers=H("alice"))
    assert ask.status_code == 201 and ask.json()["tier"] == "PROTECTED"
    assert c.post(f"/intakes/{iid}/files/{fid}/egress-request", json={"reason": "x"},
                  headers=H("alice")).status_code == 409  # already waiting
    assert c.get("/egress-approvals", headers=H("bob")).status_code == 403  # only the quality manager role
    pending = c.get("/egress-approvals", headers=H("erin")).json()
    assert [(x["file_id"], x["requested_by"], x["reason"]) for x in pending] == [(fid, "alice", "고객 동의서 확인")]
    assert c.get(f"/egress-approvals/{fid}/content", headers=H("erin")).content == data
    ok = c.post(f"/egress-approvals/{fid}", json={"decision": "APPROVED", "reason": "기밀 아님 확인"}, headers=H("erin"))
    assert ok.json()["tier"] == "RAW" and [e["event"] for e in ok.json()["events"]] == ["REQUESTED", "APPROVED"]
    assert c.get(f"/egress-approvals/{fid}/content", headers=H("erin")).status_code == 404  # not pending any more
    d = analyze(c, iid).json()["draft"]
    assert d["egress"]["files"][0]["sent"] == "RAW" and d["egress"]["masked_payload"] is None
    assert SECRET in json.dumps(p.seen[-1]["messages"], ensure_ascii=False)  # approved: the original text went
    assert c.get(f"/intakes/{iid}/draft", headers=H("alice")).json()["files"][0]["egress"]["approved"] is True


def test_a_rejected_request_keeps_the_file_masked(tmp_path):
    c = client(tmp_path, Echo())
    body = upload(c, [("mine.pdf", own_pdf())]).json()
    iid, fid = body["intake_id"], body["files"][0]["file_id"]
    c.post(f"/intakes/{iid}/files/{fid}/egress-request", json={"reason": "급함"}, headers=H("alice"))
    r = c.post(f"/egress-approvals/{fid}", json={"decision": "REJECTED", "reason": "고객 기밀"}, headers=H("erin"))
    assert r.json()["tier"] == "PROTECTED"
    d = analyze(c, iid).json()["draft"]
    assert d["egress"]["files"][0]["sent"] == "MASKED"
    assert c.post(f"/intakes/{iid}/files/{fid}/egress-request", json={"reason": "x"}, headers=H("dave")).status_code == 404


def test_with_an_in_house_model_protected_files_go_to_it_as_they_are_and_nothing_leaves(tmp_path, monkeypatch):
    calls = []

    def opener(request, timeout):
        calls.append(json.loads(request.data))
        reply = {"model": "llama-local", "choices": [{"finish_reason": "stop", "message": {"role": "assistant",
                 "content": json.dumps({"documents": [], "links": [], "questions": [], "transcriptions": [],
                                        "fields": []})}}]}
        return io.BytesIO(json.dumps(reply).encode())

    local = LocalProvider("http://intranet-llm/v1/chat/completions", "llama-local", opener=opener)
    external = Scripted()
    files = [{"file_id": 1, "name": "mine.pdf", "tier": "PROTECTED", "data_origin": "UNKNOWN",
              "elements": [{"id": "pdf:p1:l1", "kind": "text", "page": 1, "text": SECRET}], "images": {"x": b"\x89PNG"}}]
    mode, status, _raw, _withheld, error, info = intake.analysis(external, files, local)
    assert mode == "LOCAL" and status == "OK" and error is None and external.seen == []  # the external model: unused
    assert SECRET in json.dumps(calls[0]) and "image_url" in json.dumps(calls[0])  # as is, images included
    assert info["files"][0]["sent"] == "RAW" and info["masked_payload"] is None


def test_protected_files_can_be_withheld_entirely(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "MASKED_EGRESS", False)
    p = Scripted()
    c = client(tmp_path, p)
    body = upload(c, [("complaint.pdf", PDF_FIXTURE.read_bytes()), ("mine.pdf", own_pdf())]).json()
    p.replies.append({"documents": [], "links": [], "questions": [], "fields": []})
    d = analyze(c, body["intake_id"]).json()["draft"]
    assert [w["name"] for w in d["withheld"]] == ["mine.pdf"] and d["status"] == "PARTIAL"
    assert SECRET not in json.dumps(p.seen[0]["messages"], ensure_ascii=False)


def test_model_input_is_capped_by_cost_and_the_rest_is_reported(tmp_path, monkeypatch):
    from app import intake_extract, limits

    monkeypatch.setitem(limits.OVERRIDES, "MAX_COST_PER_MODEL_CALL_USD", 0.0001)  # = 80 input tokens
    els = [{"id": f"pdf:p1:l{i}", "kind": "text", "page": 1, "text": f"line {i} of a long document"} for i in range(50)]
    parts, _, sent = intake_extract.model_input([{"file_id": 1, "name": "big.pdf", "tier": "RAW",
                                                  "elements": els, "images": {}}])
    shown = json.loads(parts[0]["text"])["elements"]
    assert 0 < len(shown) < 50 and sent[0]["not_sent_from"] == f"pdf:p1:l{len(shown)}"
    assert sent[0]["not_sent"] == 50 - len(shown)
    assert limits.max_input_tokens() == 80


def test_every_extraction_records_the_tokens_it_used(tmp_path):
    class Counted(Scripted):
        def chat(self, messages, tools, response_format=None, reasoning_effort=None):
            out = super().chat(messages, tools, response_format, reasoning_effort)
            return {**out, "usage": {"prompt_tokens": 812, "completion_tokens": 240}}

    p = Counted({"documents": [], "links": [], "questions": [], "fields": []})
    c = client(tmp_path, p)
    iid = upload(c, [("c.pdf", PDF_FIXTURE.read_bytes())]).json()["intake_id"]
    eg = analyze(c, iid).json()["draft"]["egress"]
    assert eg["usage"] == {"prompt_tokens": 812, "completion_tokens": 240}
    assert eg["estimated_input_tokens"] > 0 and eg["max_input_tokens"] >= eg["estimated_input_tokens"]
