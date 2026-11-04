"""English record text gets a Korean rendering on screen; a translation that changes a number or code is not shown."""

import json

from app.translate import MEMO, kept, translate


class Fake:
    def __init__(self, items):
        self.items, self.sent = items, []

    def chat(self, messages, tools, response_format=None, reasoning_effort=None):
        self.sent.append(json.loads(messages[1]["content"]))
        return {"message": {"content": json.dumps({"items": self.items})}}


def test_only_english_is_sent_and_a_translation_must_keep_numbers_and_codes():
    texts = ["Clogged apertures found on affected pads of STN-2", "이미 한국어", "L02", "Defect rate fell to 0.12 after cleaning"]
    p = Fake([{"n": 1, "ko": "STN-2의 해당 패드에서 막힌 개구부 발견"}, {"n": 2, "ko": "세척 후 불량률이 0.2로 감소"}])
    out = translate(p, texts)
    assert [t["text"] for t in p.sent[0]["texts"]] == [texts[0], texts[3]]  # Korean and bare codes are not sent
    assert out == {texts[0]: "STN-2의 해당 패드에서 막힌 개구부 발견"}  # 0.12 -> 0.2: not shown, the original stays
    assert kept("Run 3 on L02", "L02에서 3회 실행") and not kept("Run 3 on L02", "L02에서 실행")
    again = Fake([])
    assert translate(again, [texts[0]]) == out and again.sent == []  # a sentence is translated once
    MEMO.clear()


def test_without_a_model_nothing_is_translated():
    assert translate(None, ["Clogged apertures found on affected pads"]) == {}


def test_a_translation_is_stored_and_survives_a_restart(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import Base

    engine = create_engine(f"sqlite:///{tmp_path / 't.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    p = Fake([{"n": 1, "ko": "해당 패드에서 막힌 개구부 발견"}])
    p.model, p.mode = "m", "LIVE"
    text = "Clogged apertures found on affected pads"
    assert translate(p, [text], sessions) == {text: "해당 패드에서 막힌 개구부 발견"}
    MEMO.clear()  # a restart
    again = Fake([])
    assert translate(again, [text], sessions) == {text: "해당 패드에서 막힌 개구부 발견"} and again.sent == []
    MEMO.clear()


def test_the_admin_picks_the_language_and_off_shows_originals(monkeypatch):
    from app import limits

    text = "Clogged apertures found on affected pads of STN-2"
    monkeypatch.setitem(limits.OVERRIDES, "TRANSLATE_LANGUAGE", "ja")
    p = Fake([{"n": 1, "ko": "STN-2の該当パッドで目詰まりした開口部を発見"}])
    asked = []
    chat = p.chat
    p.chat = lambda messages, tools, **kw: asked.append(messages[0]["content"]) or chat(messages, tools, **kw)
    assert translate(p, [text]) == {text: "STN-2の該当パッドで目詰まりした開口部を発見"}
    assert len(asked) == 1 and "into natural Japanese" in asked[0]
    monkeypatch.setitem(limits.OVERRIDES, "TRANSLATE_LANGUAGE", "OFF")
    off = Fake([])
    assert translate(off, [text]) == {} and off.sent == []
    with __import__("pytest").raises(Exception):
        limits.cast("TRANSLATE_LANGUAGE", "fr")  # only the offered languages
    MEMO.clear()
