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

