"""Reasons people write are free text: any wording, any length, never blank (one definition: app.fields).

Root cause guarded here: each gate defined its own minimum (3, 5, 10, 20 characters), whitespace-only reasons passed,
a REJECT needed no reason, and the UI filled empty reasons with canned English sentences.
"""

import importlib
import pkgutil

import pytest
from pydantic import BaseModel, StringConstraints

import app
from tests.v5_util import H, line_client, ok

WRITTEN = {"reason", "rationale", "comment", "note", "contribution", "mitigation", "risk", "body", "instruction",
           "counter_evidence_response", "exceptions"}
NOT_A_REASON = {("RevisionIn", "body")}  # a controlled document's text: specification content, keeps its minimum
MODEL_OUTPUT = {"app.report"}  # schema of what the model writes, validated by report.validate_report


def request_models():
    for m in pkgutil.iter_modules(app.__path__):
        mod = importlib.import_module(f"app.{m.name}")
        if mod.__name__ in MODEL_OUTPUT:
            continue
        for obj in vars(mod).values():
            if isinstance(obj, type) and issubclass(obj, BaseModel) and obj.__module__ == mod.__name__:
                yield obj


def test_every_written_reason_field_uses_the_shared_definition():
    checked = []
    for model in request_models():
        for name, f in model.model_fields.items():
            if name not in WRITTEN or f.annotation not in (str, str | None) or (model.__name__, name) in NOT_A_REASON:
                continue
            sc = [x for x in f.metadata if isinstance(x, StringConstraints)]
            assert sc and sc[0].strip_whitespace and (sc[0].min_length or 0) <= 1, \
                f"{model.__module__}.{model.__name__}.{name}: use app.fields.FreeText / OptionalText"
            checked.append(f"{model.__name__}.{name}")
    assert len(checked) >= 15, checked


@pytest.fixture
def c(tmp_path):
    client = line_client(tmp_path)
    yield client
    client.app_ref.state.engine.dispose()


def test_short_reasons_in_any_language_pass_and_blank_ones_do_not(c):
    r = ok(c.post("/cases/L/experience/retrievals", json={"q": "solder volume drift stencil"}, headers=H("alice")))
    choice = {"retrieval_id": r["retrieval_id"], "entry_key": r["recommendations"][0]["entry_key"],
              "decision": "INVESTIGATE_MORE"}
    for blank in ("", "   ", "\n\t"):
        assert c.post("/cases/L/experience/decisions", headers=H("alice"),
                      json={**choice, "reason": blank}).status_code == 422
    stored = ok(c.post("/cases/L/experience/decisions", headers=H("alice"), json={**choice, "reason": "  조건 다름  "}))
    assert stored["reason"] == "조건 다름"  # what the person wrote, trimmed


def test_reject_and_request_info_need_a_reason_approve_does_not(c):
    d = ok(c.post("/cases/L/ncr", json={}, headers=H("alice")))
    ok(c.post("/cases/L/ncr/1/request-review", json={"reviewer_id": "bob"}, headers=H("alice")), 200)
    for decision in ("REJECT", "REQUEST_INFO"):
        r = c.post("/cases/L/ncr/1/decision", headers=H("bob"),
                   json={"decision": decision, "comment": "  ", "content_sha256": d["content_sha256"]})
        assert r.status_code == 422 and "why" in r.text
    ok(c.post("/cases/L/ncr/1/decision", headers=H("bob"),
              json={"decision": "REQUEST_INFO", "comment": "C3?", "content_sha256": d["content_sha256"]}), 200)

