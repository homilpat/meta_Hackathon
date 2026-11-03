"""Repeatable answers (user 2026-11-02, spec §26.5): every call sends a fixed temperature and seed, and an identical
request gets the stored answer instead of a new, possibly different, one. Errors are never stored."""

import json

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app import limits
from app.db import Base
from app.main import create_app
from app.model_cache import Reusing
from app.model_provider import MetaProvider, ProviderError
from tests.test_meta_smoke import _Reply

OK = {"model": "muse-spark-1.3", "choices": [{"message": {"role": "assistant", "content": "a1"},
                                              "finish_reason": "stop"}], "usage": {"prompt_tokens": 5}}


def provider(sent: list, replies: list | None = None) -> MetaProvider:
    def opener(req, timeout):
        sent.append(json.loads(req.data))
        r = (replies or [OK]).pop(0) if replies else OK
        if isinstance(r, Exception):
            raise r
        return _Reply(json.dumps(r).encode())
    return MetaProvider("k" * 12, opener=opener)


def test_every_call_sends_the_fixed_temperature_and_seed(monkeypatch):
    sent = []
    provider(sent).chat([{"role": "user", "content": "x"}], [])
    assert sent[0]["temperature"] == 0.0 and sent[0]["seed"] == 1
    monkeypatch.setitem(limits.OVERRIDES, "MODEL_SEED", 0)  # 0: not sent (for a model that refuses seed)
    monkeypatch.setitem(limits.OVERRIDES, "MODEL_TEMPERATURE", 0.7)
    provider(sent).chat([{"role": "user", "content": "x"}], [])
    assert "seed" not in sent[1] and sent[1]["temperature"] == 0.7


@pytest.fixture
def sessions(tmp_path):
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{tmp_path / 'r.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(engine)


def test_the_same_request_gets_the_stored_answer_and_a_different_one_calls_the_model(sessions):
    sent = []
    second = {**OK, "choices": [{"message": {"role": "assistant", "content": "a2"}, "finish_reason": "stop"}]}
    p = Reusing(provider(sent, [OK, second]), sessions)
    first = p.chat([{"role": "user", "content": "x"}], [])
    again = p.chat([{"role": "user", "content": "x"}], [])
    other = p.chat([{"role": "user", "content": "y"}], [])
    assert len(sent) == 2 and again["message"] == first["message"] and again["usage"] == {} and again["reused"]
    assert other["message"]["content"] == "a2" and p.mode == "LIVE" and p.model == "muse-spark-1.3"


def test_a_changed_setting_is_a_different_request_and_off_always_calls(sessions, monkeypatch):
    sent = []
    p = Reusing(provider(sent), sessions)
    p.chat([{"role": "user", "content": "x"}], [])
    monkeypatch.setitem(limits.OVERRIDES, "MODEL_TEMPERATURE", 0.5)
    p.chat([{"role": "user", "content": "x"}], [])
    monkeypatch.setitem(limits.OVERRIDES, "MODEL_RESPONSE_REUSE", "OFF")
    p.chat([{"role": "user", "content": "x"}], [])
    assert len(sent) == 3


def test_an_error_is_not_stored_so_a_retry_calls_again(sessions):
    from urllib.error import URLError

    sent = []
    p = Reusing(provider(sent, [URLError("down"), OK]), sessions)
    with pytest.raises(ProviderError):
        p.chat([{"role": "user", "content": "x"}], [])
    assert p.chat([{"role": "user", "content": "x"}], [])["message"]["content"] == "a1" and len(sent) == 2


def test_only_a_real_provider_is_wrapped_and_the_switch_takes_on_or_off(tmp_path):
    from tests.test_s3_investigation import Scripted

    real = create_app(f"sqlite:///{tmp_path / 'a.db'}", provider([]))
    double = create_app(f"sqlite:///{tmp_path / 'b.db'}", Scripted())
    assert isinstance(real.state.provider, Reusing) and not isinstance(double.state.provider, Reusing)
    with pytest.raises(HTTPException):
        limits.cast("MODEL_RESPONSE_REUSE", "MAYBE")
    assert limits.cast("MODEL_TEMPERATURE", "0") == 0.0


def test_the_confidential_backstop_stays_on_unless_an_evaluation_turns_it_off_for_public_data():
    from app.model_provider import EgressBlocked

    sent = []
    p = provider(sent)
    with pytest.raises(EgressBlocked):
        p.chat([{"role": "user", "content": "CONFIDENTIAL TREATMENT REQUESTED"}], [])
    p.restricted_check = False  # what scripts/cuad_eval.py does for the public CUAD contracts only
    p.chat([{"role": "user", "content": "CONFIDENTIAL TREATMENT REQUESTED"}], [])
    with pytest.raises(EgressBlocked):  # the secret check never turns off
        p.chat([{"role": "user", "content": "Bearer abcdefghijklmnop"}], [])
    assert len(sent) == 1 and MetaProvider.restricted_check is True


def test_a_route_holding_the_write_lock_does_not_block_the_cache(tmp_path):
    """LIVE rehearsal 2026-11-04: an investigation calls the model inside its write transaction; the cache waited on
    that lock and the request failed with "database is locked"."""
    import time

    sent = []
    app = create_app(f"sqlite:///{tmp_path / 'lock.db'}", provider(sent))
    Base.metadata.create_all(app.state.engine)
    with sessionmaker(app.state.engine).begin() as s:  # BEGIN IMMEDIATE, as every route's transaction
        s.execute(Base.metadata.tables["model_responses"].select())
        t = time.monotonic()
        out = app.state.provider.chat([{"role": "user", "content": "x"}], [])
        assert out["message"]["content"] == "a1" and time.monotonic() - t < 5
    assert app.state.provider.chat([{"role": "user", "content": "x"}], [])["message"]["content"] == "a1"
    assert len(sent) == 2  # the locked call was not stored; the next one is a plain miss and is stored
