import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SourceEvent
from app.model_provider import MetaProvider
from app.tools import EvidenceTools, ToolDenied
from scripts.token_budget import ids
from tests.test_s3_investigation import Opener
from tests.test_s6_followups import REPLY, create, env  # noqa: F401 - env: seeded case fixture


def test_summary_keeps_every_ncr_fact_and_passes_the_gateway(env):  # noqa: F811
    c = env
    cited = {e for cl in create(c, "ncr").json()["claims"] for e in cl["evidence_ids"]}
    with Session(c.app_ref.state.engine) as s:
        out = EvidenceTools(s, "C1").call("get_case_summary", {})
    assert cited <= ids(out)
    p02 = next(f for f in out["aoi_fail"] if f["board"] == "P02/B01")
    ncr = c.get("/cases/C1/ncr/1", headers={"X-User": "alice"}).json()["claims"]
    assert p02["spi"]["mean_mm3"] == next(cl["value"] for cl in ncr if "Mean SPI" in cl["text"] and "P02/B01" in cl["text"])
    opener = Opener(REPLY)
    MetaProvider("k-test-0000", opener=opener).chat([{"role": "tool", "content": json.dumps(out)}], [])
    assert len(opener.requests) == 1


def test_summary_fails_closed_on_restricted_rows(env):  # noqa: F811
    with Session(env.app_ref.state.engine) as s:
        s.scalars(select(SourceEvent)).first().sensitivity = "CONFIDENTIAL"
        s.flush()
        with pytest.raises(ToolDenied):
            EvidenceTools(s, "C1").call("get_case_summary", {})
