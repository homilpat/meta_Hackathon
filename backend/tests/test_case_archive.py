"""보관 (user 2026-11-05): any case, at any stage, leaves every list; nothing is deleted; who and when is kept."""

from tests.v5_util import H, line_client


def test_archive_hides_the_case_for_everyone_and_keeps_the_record(tmp_path):
    c = line_client(tmp_path)
    assert "L" in [x["case_id"] for x in c.get("/cases", headers=H("bob")).json()]
    assert c.post("/cases/L/archive", headers=H("alice")).status_code == 200
    assert c.post("/cases/L/archive", headers=H("alice")).status_code == 200  # twice is harmless
    for u in ("alice", "bob"):
        assert "L" not in [x["case_id"] for x in c.get("/cases", headers=H(u)).json()]
    assert c.post("/cases/NOPE/archive", headers=H("alice")).status_code == 404
