"""Server templates must pass their own validator: every number they state is recomputed from the cited rows.

Root cause guarded here: the NCR template stated the SPC centre line, LCL and UCL in one claim (one stored value)
and Cpk values the validator had no formula for, so the server published numbers it never checked.
"""

import pytest

from tests.v5_util import H, line_client, ok

UNCHECKED = {"TEXT_EXTRA_VALUE", "TEXT_VALUE_MISMATCH", "VALUE_MISMATCH"}


@pytest.fixture
def c(tmp_path):
    client = line_client(tmp_path)
    yield client
    client.app_ref.state.engine.dispose()


def test_every_number_in_every_template_is_recomputed(c):
    for kind in ("ncr", "containment", "rca"):  # drafts may be written ahead of approvals
        d = ok(c.post(f"/cases/L/{kind}", json={}, headers=H("alice")))
        v = ok(c.post(f"/cases/L/{kind}/1/validate", headers=H("alice")))
        assert not [i for i in v["issues"] if i["code"] in UNCHECKED or i["severity"] == "BLOCK"], (kind, v["issues"])
        numeric = {x["claim_id"]: x for x in d["claims"] if x["value"] is not None}
        unchecked = [k for k in numeric if v["predicates"][k]["op"] == "NOT_RECOMPUTED"]
        assert not unchecked, (kind, [numeric[k]["text"] for k in unchecked])
        for k, x in numeric.items():
            assert v["predicates"][k]["expected"] == pytest.approx(x["value"]), (kind, x["text"])


def spc_claims(d: dict) -> dict[str, dict]:
    ops = {"centre line": "cl", "LCL": "lcl", "UCL": "ucl"}
    return {ops[n]: x for x in d["claims"] for n in ops if f", {n} from reference lot" in x["text"]}


def test_spc_limits_and_cpk_are_one_statistic_per_claim_and_match_the_monitor(c):
    d = ok(c.post("/cases/L/ncr", json={}, headers=H("alice")))
    m = c.get("/cases/L/spc", headers=H("alice")).json()
    limits = spc_claims(d)
    assert set(limits) == {"cl", "lcl", "ucl"}
    assert all(x["value"] == m["limits"][k] for k, x in limits.items())
    v = ok(c.post("/cases/L/ncr/1/validate", headers=H("alice")))
    assert {v["predicates"][x["claim_id"]]["op"] for x in limits.values()} == {"spc_limit"}
    cpk = [x for x in d["claims"] if x["unit"] == "Cpk"]
    assert cpk and all(v["predicates"][x["claim_id"]]["op"] == "cpk" for x in cpk)
    assert {x["value"] for x in cpk} == {lot["cpk"] for lot in m["lots"].values()}


@pytest.mark.parametrize("pick", ["lcl", "cpk"])
def test_a_wrong_spc_statistic_is_refused(c, pick):
    d = ok(c.post("/cases/L/ncr", json={}, headers=H("alice")))
    x = spc_claims(d)["lcl"] if pick == "lcl" else next(x for x in d["claims"] if x["unit"] == "Cpk")
    wrong = round(x["value"] + (0.001 if pick == "lcl" else 0.5), 5)
    r = c.post("/cases/L/ncr/1/edits", headers=H("alice"), json={
        "expected_sha256": d["content_sha256"], "reason": "try a wrong statistic",
        "changes": [{"claim_id": x["claim_id"], "value": wrong, "text": x["text"].replace(f"{x['value']}", f"{wrong}")}]})
    assert r.status_code == 422 and "recomputation" in r.text, r.text
