"""Phase A (G8 focused audit): counterexamples for the one claim validator.

Written before any fix. Each case is a sentence a person or a model could plausibly put into a draft; the
validator must refuse the wrong ones and must not over-block correct, rounded statements.
"""

import pytest

from tests.test_v5_5_g8 import codes, l02_aoi, ncr, rate_claim, true_rate
from tests.v5_util import H, evidence, line_client


@pytest.fixture
def c(tmp_path):
    client = line_client(tmp_path)
    yield client
    client.app_ref.state.engine.dispose()


def blocked(r, says):
    """422 whose detail contains the validator's message for that issue (detail carries messages, not codes)."""
    assert r.status_code == 422, r.text
    assert says in codes(r), codes(r)


def test_extra_percentage_next_to_the_correct_one_is_detected(c):
    # Not refused at storage (template sentences legitimately carry CL/UCL/LCL in one claim), but the validation
    # run flags the number the server did not recompute, so the reviewer sees it before approval.
    rate = true_rate(c)
    r = ncr(c, rate_claim(c, rate, text=f"AOI FAIL share in lot L02 is {rate}%, and 2.1% after rework."))
    assert r.status_code == 201, r.text
    v = c.post("/cases/L/ncr/1/validate", headers=H("bob")).json()
    assert v["result"] in ("WARN", "BLOCK")
    assert any(i["code"] == "TEXT_EXTRA_VALUE" and "2.1 %" in i["message"] for i in v["issues"]), v


def test_correct_value_written_bare_does_not_hide_a_wrong_percentage(c):
    # Same surface shape as the template's "centre 0.12046, LCL .., UCL 0.12906 mm3", so flagged rather than refused.
    rate = true_rate(c)
    assert ncr(c, rate_claim(c, rate, text=f"AOI FAIL share in lot L02 (server value {rate}) is 2.1%.")).status_code \
        == 201
    v = c.post("/cases/L/ncr/1/validate", headers=H("bob")).json()
    assert any(i["code"] == "TEXT_EXTRA_VALUE" and "2.1 %" in i["message"] for i in v["issues"]), v


def test_wrong_percentage_without_the_value_anywhere_is_still_blocked(c):
    rate = true_rate(c)
    blocked(ncr(c, rate_claim(c, rate, text="AOI FAIL share in lot L02 is 2.1%.")), "but the claim value is")


def test_rounded_correct_statements_still_pass(c):
    rate = true_rate(c)
    assert ncr(c, rate_claim(c, rate)).status_code == 201
    one = round(rate, 1)
    assert ncr(c, rate_claim(c, one, text=f"AOI FAIL share in lot L02 is {one}%.")).status_code == 201
    # the number only in the value field (validated model findings) stays allowed
    assert ncr(c, rate_claim(c, rate, text="AOI FAIL share in lot L02, see value.")).status_code == 201


def test_lot_named_but_not_cited_is_blocked(c):
    rate = true_rate(c)
    blocked(ncr(c, rate_claim(c, rate, text=f"AOI FAIL share in lots L02 and L03 is {rate}%.")), "text names lot ['L03']")


def test_unit_that_does_not_fit_the_cited_measurement_is_blocked(c):
    spi = evidence(c, "L", "spi_measurements", panel_id="L02-P02", board_id="B2")
    claim = {"classification": "CALCULATED", "unit": "mm", "evidence_ids": spi, "value": 0.1,
             "text": "Mean solder volume on L02-P02/B2 is 0.1 mm."}
    blocked(ncr(c, claim), "unit mm does not match")


def test_execution_stated_without_an_executed_action_is_blocked(c):
    claim = {"classification": "OBSERVED", "evidence_ids": l02_aoi(c)[:1], "text": "Lot L02 was held and quarantined."}
    blocked(ncr(c, claim), "cites no executed action")


def test_cause_stated_without_a_confirmed_hypothesis_is_blocked(c):
    claim = {"classification": "OBSERVED", "evidence_ids": l02_aoi(c)[:1],
             "text": "The defects in lot L02 were caused by stencil wear."}
    r = ncr(c, claim)
    assert r.status_code == 422, r.text  # CLAIM_RULE / TEXT_RULE / CAUSE_UNSUPPORTED all refuse it

# Superseded source rows: covered by test_v5_5_g8::test_source_supersession_makes_validation_stale_and_blocks.
