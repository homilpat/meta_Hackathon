"""Search glossary: the same concept in Korean, Japanese, Chinese or other English wording ranks the same records."""

import pytest

from app.retrieval import tokens
from tests.v5_util import H, line_client


@pytest.mark.parametrize("text,expected", [
    ("Solder volume drifted low on worn stencil", ["solder", "volume", "drift", "low", "wear", "stencil"]),
    ("스텐실의 개구부가 막혔다", ["stencil", "aperture", "clog"]),  # particles and endings dropped
    ("솔더량 부족, 스텐실 마모", ["solder", "volume", "low", "stencil", "wear"]),  # compound word split
    ("ステンシルの目詰まり", ["stencil", "clog"]),  # written without spaces
    ("钢网堵塞", ["stencil", "clog"]),
    ("공정은 가나다라는", ["process", "가나다라"]),  # a word outside the glossary is kept as written
])
def test_tokens_map_any_wording_to_the_canonical_terms(text, expected):
    assert tokens(text) == expected


@pytest.fixture
def c(tmp_path):
    client = line_client(tmp_path)
    yield client
    client.app_ref.state.engine.dispose()


def top(c, path: str, **kw) -> list[str]:
    if path == "experience":
        r = c.post("/cases/L/experience/retrievals", json=kw, headers=H("alice")).json()
        return [x["entry_key"] for x in r["recommendations"]][:3]
    r = c.get("/cases/L/documents/search", params=kw, headers=H("alice")).json()
    return [x["ref"] for x in r["results"]][:3]


def test_same_past_cases_and_documents_whatever_the_language(c):
    en = top(c, "experience", q="solder volume drift stencil")
    assert en and all(top(c, "experience", q=q) == en for q in
                      ("솔더량 드리프트 스텐실", "はんだ量 ドリフト ステンシル", "锡量 漂移 钢网"))
    en = top(c, "documents", q="stencil cleaning interval")
    assert en[0] == "DOC:SOP-SMT-010:3"
    assert all(top(c, "documents", q=q) == en for q in ("스텐실 세정 주기", "ステンシル 洗浄 周期", "钢网 清洗 周期"))
