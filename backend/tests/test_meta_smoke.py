import io
import json
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db import Base, ModelRun, QualityCase, User
from app.main import create_app
from scripts import meta_smoke
from scripts.meta_smoke import parse_answer, read_key


def test_parse_answer_accepts_expected_contract() -> None:
    assert parse_answer('{"status":"ok"}') == "ok"


def test_parse_answer_rejects_wrong_contract() -> None:
    try:
        parse_answer('{"status":"maybe"}')
    except ValueError:
        pass
    else:
        raise AssertionError("Unrecognized model output was accepted")


def test_key_loads_from_local_env_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    (tmp_path / ".env").write_text("MODEL_API_KEY=test-only\n", encoding="utf-8")
    assert read_key() == "test-only"



class _Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _no_network(*a, **k):
    raise AssertionError("network must not be called")


def test_smoke_without_key_makes_no_call(monkeypatch, capsys) -> None:
    monkeypatch.setattr(meta_smoke, "read_key", lambda: "")
    monkeypatch.setattr(meta_smoke, "urlopen", _no_network)
    assert meta_smoke.main() == 2
    assert "LIVE NOT TESTED" in capsys.readouterr().out


def test_smoke_http_error_is_failure_and_never_echoes_key(monkeypatch, capsys) -> None:
    def deny(*a, **k):
        raise HTTPError("u", 401, "secret-sk-should-not-print", {}, io.BytesIO(b"key=test-key-123"))

    monkeypatch.setattr(meta_smoke, "read_key", lambda: "test-key-123")
    monkeypatch.setattr(meta_smoke, "urlopen", deny)
    assert meta_smoke.main() == 1
    out = capsys.readouterr().out
    assert out.strip() == "LIVE FAILED: HTTPError 401" and "test-key-123" not in out


def test_smoke_success_reports_latency_and_tokens(monkeypatch, capsys) -> None:
    body = {"model": meta_smoke.MODEL, "choices": [{"message": {"content": '{"status":"ok"}'}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3}}
    monkeypatch.setattr(meta_smoke, "read_key", lambda: "k" * 12)
    monkeypatch.setattr(meta_smoke, "urlopen", lambda *a, **k: _Reply(json.dumps(body).encode()))
    assert meta_smoke.main() == 0
    out = capsys.readouterr().out
    assert "LIVE SUCCESS" in out and "latency_ms=" in out and "prompt_tokens=12" in out


def test_smoke_wrong_model_id_is_failure(monkeypatch, capsys) -> None:
    body = {"model": "other", "choices": [{"message": {"content": '{"status":"ok"}'}}]}
    monkeypatch.setattr(meta_smoke, "read_key", lambda: "k" * 12)
    monkeypatch.setattr(meta_smoke, "urlopen", lambda *a, **k: _Reply(json.dumps(body).encode()))
    assert meta_smoke.main() == 1


class _Double:
    mode, model = "TEST_DOUBLE", "double"


class _Live:
    mode, model = "LIVE", meta_smoke.MODEL


@pytest.mark.parametrize("provider,status", [(None, "NOT_CONFIGURED"), (_Double(), "TEST_DOUBLE"),
                                             (_Live(), "CONFIGURED_NOT_VERIFIED")])
def test_provider_status_never_claims_live_without_a_validated_live_run(tmp_path, monkeypatch, provider, status):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    app = create_app(f"sqlite:///{tmp_path / 'p.db'}", provider=provider)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as client:
        assert client.get("/provider").json()["live_status"] == status
    app.state.engine.dispose()


def test_provider_status_verified_only_after_validated_live_run(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 'p.db'}", provider=_Live())
    Base.metadata.create_all(app.state.engine)
    sessions = sessionmaker(app.state.engine)
    with sessions.begin() as s:
        s.add_all([QualityCase(id="C", domain="PCB", data_origin="SYNTHETIC"), User(id="alice", name="a", role="AUTHOR")])
        s.flush()
        for mode, st in (("TEST_DOUBLE", "VALIDATED"), ("LIVE", "FAILED")):
            s.add(ModelRun(case_id="C", requested_by="alice", model="m", mode=mode, status=st, rounds=1,
                           prompt_tokens=0, completion_tokens=0, validation_errors=[], started_at="t", finished_at="t"))
    with TestClient(app) as client:
        assert client.get("/provider").json()["live_status"] == "CONFIGURED_NOT_VERIFIED"
        with sessions.begin() as s:
            s.add(ModelRun(case_id="C", requested_by="alice", model="m", mode="LIVE", status="VALIDATED", rounds=1,
                           prompt_tokens=0, completion_tokens=0, validation_errors=[], started_at="t", finished_at="t"))
        assert client.get("/provider").json()["live_status"] == "VERIFIED"
    app.state.engine.dispose()
