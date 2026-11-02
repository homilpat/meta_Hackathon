"""EV0-EV3 (spec §26, §26.7): the local evaluation itself is checked. Scoring is offline (no network, no model), a
new LIVE call needs an explicit opt-in and a confirmed budget, a saved trace replays without calling the model,
the matchers reject wrong trajectories, and every agent pair changes its next action as written in EXPECT."""

import json

import pytest

from app import docparse, intake_extract
from scripts import agent_eval, cuad_eval, evalkit, fixture_eval


# ---- EV0: gates and guards ----
def test_new_live_calls_need_the_flag_and_a_confirmed_budget(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "a-key-is-not-consent")
    monkeypatch.delenv(evalkit.BUDGET_ENV, raising=False)
    assert evalkit.live_gate([])[0] is None and "--live" in evalkit.live_gate([])[2]
    assert evalkit.live_gate(["--live"])[0] is None and "budget" in evalkit.live_gate(["--live"])[2]
    monkeypatch.setenv(evalkit.BUDGET_ENV, "0")
    assert evalkit.live_gate(["--live"])[0] is None


def test_scoring_refuses_the_network_but_not_loopback():
    import socket

    with evalkit.no_network() as attempts:
        with pytest.raises(ConnectionRefusedError):
            socket.create_connection(("example.com", 443), timeout=1)
        a, b = socket.socketpair()  # what an in-process test client's event loop uses
        a.close(), b.close()
    assert len(attempts) == 1


# ---- EV1: CUAD scoring (the official matching rule, our own reading) ----
def test_official_matching_rule_counts_tp_fp_fn_like_evaluate_py():
    assert cuad_eval.jaccard("Governing law: New York.", "governing law new york") == 1.0
    assert cuad_eval.tp_fp_fn(["the laws of the State of New York"], ["laws of the State of New York"],
                              "Governing Law") == (1, 0, 0)
    assert cuad_eval.tp_fp_fn(["Acme Corp."], ["between Acme Corp. and Beta LLC"], "Parties") == (1, 0, 0)  # substring
    assert cuad_eval.tp_fp_fn(["Acme Corp."], ["between Acme Corp. and Beta LLC"], "Agreement Date") == (0, 1, 1)
    assert cuad_eval.tp_fp_fn([], ["anything"], "Expiration Date") == (0, 1, 0)  # no answer, one given
    assert cuad_eval.tp_fp_fn([], [], "Expiration Date") == (0, 0, 0)
    assert cuad_eval.token_f1("", "") == 1.0 and cuad_eval.token_f1("a b c", "") == 0.0
    nbsp = "the laws of the State of New York"  # how our PDF parser spaces some files
    assert cuad_eval.tp_fp_fn(["the laws of the State of New York"], [nbsp], "Governing Law") == (1, 0, 0)


def test_merging_rounds_never_changes_a_recorded_reply():
    t = cuad_eval.task(QUESTIONS)

    class TwoRounds(cuad_eval.Bm25Double):
        n = 0

        def chat(self, messages, tools, response_format=None, reasoning_effort=None):
            out = super().chat(messages, tools, response_format, reasoning_effort)
            self.n += 1
            body = json.loads(out["message"]["content"])
            if self.n == 1:  # ask for page 2 and answer nothing yet
                body = {"answers": [], "need": [{"file_id": 1, "part": "p3", "why": "schedule"}]}
            return {"message": {"content": json.dumps(body)}, "usage": {"prompt_tokens": 100, "completion_tokens": 10}}

    rec = cuad_eval.Recorder(TwoRounds(t))
    _, _, info = intake_extract.extract(rec, contract(), "RAW", "HYBRID", t)
    assert len(rec.calls) == 2 and info["usage"]["prompt_tokens"] == 200
    assert [c["usage"]["prompt_tokens"] for c in rec.calls] == [100, 100]  # each call keeps its own usage


def contract() -> list[dict]:
    files = [{"file_id": 1, "name": "k.pdf", "tier": "RAW", "images": {}, "coverage": {}, "elements": [
        {"id": f"pdf:p{p}:l{i}", "kind": "text", "page": p, "text": t} for p, i, t in [
            (1, 1, "MASTER SUPPLY AGREEMENT"), (1, 2, "This Agreement is made between Acme Corp. and Beta LLC."),
            (2, 1, "12. Governing Law. This Agreement shall be governed by the laws of the State of New York."),
            (2, 2, "13. Term. The initial term expires on December 31, 2030."),
            (3, 1, "Schedule A lists the delivery addresses.")]]}]
    return files


QUESTIONS = {"Parties": "The two or more parties who signed the contract",
             "Governing Law": "Which state/country's law governs the interpretation of the contract?"}


def test_a_trace_replays_without_the_model_and_a_changed_request_is_stale(monkeypatch):
    t = cuad_eval.task(QUESTIONS)
    rec = cuad_eval.Recorder(cuad_eval.Bm25Double(t))
    raw, _, _ = intake_extract.extract(rec, contract(), "RAW", "HYBRID", t)
    again, _, _ = intake_extract.extract(cuad_eval.Replay(rec.calls), contract(), "RAW", "HYBRID", t)
    assert again == raw and cuad_eval.valid_spans(raw, contract(), "governing_law")[0]
    changed = contract()
    changed[0]["elements"][2]["text"] += " (amended)"  # the input changed since the trace was recorded
    with pytest.raises(cuad_eval.StaleTrace):
        intake_extract.extract(cuad_eval.Replay(rec.calls), changed, "RAW", "HYBRID", t)


def test_quotes_not_in_the_cited_element_are_not_evidence_and_adjacent_lines_are_one_passage():
    files = contract()
    raw = {"answers": [{"category": "parties", "no_answer": False, "uncertain": False, "spans": [
        {"element_id": "pdf:p1:l2", "excerpt": "Acme Corp. and Beta LLC"},
        {"element_id": "pdf:p1:l2", "excerpt": "Gamma Inc."}]}]}  # the second is not in the contract
    good, total = cuad_eval.valid_spans(raw, files, "parties")
    assert (len(good), total) == (1, 2)
    els = {e["id"]: e for e in files[0]["elements"]}
    order = {e["id"]: i for i, e in enumerate(files[0]["elements"])}
    spans = [{"element_id": "pdf:p2:l1", "excerpt": "governed by"}, {"element_id": "pdf:p2:l2", "excerpt": "Term"},
             {"element_id": "pdf:p1:l1", "excerpt": "MASTER"}]
    assert cuad_eval.groups(spans, order, els) == ["MASTER", "governed by Term"]
    assert cuad_eval.Locator(files[0]["elements"]).page("laws of the State of New York") == 2
    assert cuad_eval.Locator(files[0]["elements"]).page("not in this contract") is False


def test_the_cuad_task_reuses_the_products_reading_and_the_ablation_strips_only_the_contents():
    t, b = cuad_eval.task(QUESTIONS), cuad_eval.task(QUESTIONS, "no_contents")
    m = {"toc": [{"title": "x"}], "toc_pages": [1], "heading_candidates": [{"id": "a"}], "parts": [{"part": "p1"}]}
    assert t["map"] is None and b["map"](m) == {**m, "toc": [], "toc_pages": [], "heading_candidates": []}
    assert t["version"] != b["version"] and "Acme" not in json.dumps([t["prompt"], t["labels"]])  # questions only, never an answer
    assert intake_extract.intake_task()["fields"] == intake_extract.FIELDS  # the product's task is unchanged


# ---- EV1: synthetic manufacturing fixtures ----
def test_parser_truths_hold_on_the_synthetic_fixtures():
    rows = fixture_eval.parse_rows()
    assert rows and all(not r["failed"] for r in rows), [r["failed"] for r in rows]


def test_the_vision_tool_answers_not_configured_with_no_detection(tmp_path):
    (r,) = fixture_eval.vision_rows(tmp_path)
    assert not r["failed"] and r["of"] == 5


def test_extraction_scoring_catches_a_wrong_confirmation_and_reports_not_run_without_traces(tmp_path, monkeypatch):
    files = fixture_eval.files_of(fixture_eval.CASES["complaint"]["files"])
    raw = {"documents": [], "links": [], "questions": [], "transcriptions": [], "need": [], "fields": [
        {"field": "lot", "value": "L02", "sources": [{"element_id": "pdf:p1:t1:r2:c1", "excerpt": "L02"}]},
        {"field": "defective_qty", "value": "S-0201", "sources": [{"element_id": "pdf:p1:l13",
                                                                    "excerpt": "S-0201"}]}]}  # wrong cell
    s = fixture_eval.score_extraction("complaint", raw, files)
    assert s["checks"]["lot value"] and s["checks"]["lot locator"]
    assert not s["checks"]["defective_qty value"] and s["wrong_confirmations"] == 1
    monkeypatch.setattr(fixture_eval, "TRACES", tmp_path / "none")
    assert {r["run_mode"] for r in fixture_eval.extraction_rows()} == {"NOT_RUN"}


# ---- EV2: AgentEvals matchers and the paired scenarios ----
def test_the_matchers_accept_a_legal_reorder_and_reject_a_missing_read_or_a_wrong_write():
    steps = [{"tool": t, "kind": k, "args": a, "status": "OK"} for t, k, a in [
        ("stages", "READ", {}), ("case_summary", "READ", {}), ("create_draft", "WRITE", {"kind": "ncr"}),
        ("validate_document", "WRITE", {"kind": "ncr", "version": 1})]]
    good = agent_eval.judge(steps, ["case_summary", "stages"], [("create_draft", {"kind": "ncr"}),
                                                                 ("validate_document", {"kind": "ncr", "version": 1})],
                            ["request_review"])
    assert all(good.values())
    assert not agent_eval.judge(steps, ["case_summary", "spc"], [], [])["reads_superset"]
    assert not agent_eval.judge(steps, [], [("create_draft", {"kind": "ncr"}),
                                            ("validate_document", {"kind": "ncr", "version": 2})], [])["writes_strict"]
    assert not agent_eval.judge(steps, [], [("validate_document", {"kind": "ncr", "version": 1}),
                                            ("create_draft", {"kind": "ncr"})], [])["writes_strict"]  # order
    assert not agent_eval.judge(steps, [], [], ["create_draft"])["forbidden_absent"]


@pytest.mark.parametrize("scenario", agent_eval.SCENARIOS, ids=lambda s: s.__name__)
def test_each_pair_changes_the_next_action_as_expected(scenario, tmp_path):
    with evalkit.no_network() as attempts:
        rows = scenario(tmp_path)
    assert rows and all(r["pass"] for r in rows), [(r["variant"], r["checks"]) for r in rows if not r["pass"]]
    assert not attempts


def test_parser_version_is_recorded_with_every_run():
    info = evalkit.run_info("scripts.cuad_eval")
    assert info["parser_version"] == docparse.PARSER_VERSION and info["evaluator_sha256"] and info["code_sha"]


def test_a_run_beyond_the_fixed_repeat_plan_is_refused_before_any_call(capsys):
    assert cuad_eval.collect(["--split", "heldout_long", "--condition", "A", "--live", "--run", "3"]) == 2
    assert cuad_eval.collect(["--split", "heldout", "--condition", "A", "--live", "--run", "2"]) == 2
    assert "repeat plan" in capsys.readouterr().out and cuad_eval.REPEATS["heldout_long"] == {"A": 2, "C": 2}
