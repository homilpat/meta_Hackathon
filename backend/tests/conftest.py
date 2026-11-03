import pytest

from app import model_provider


@pytest.fixture(autouse=True)
def no_real_model_key(monkeypatch, tmp_path_factory):
    """Tests never see a developer's real MODEL_API_KEY (repo-root .env or environment): no paid LIVE call, and
    create_app() without a provider stays offline exactly as in CI. Tests that need a key set one themselves."""
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setattr(model_provider, "REPO_ROOT", tmp_path_factory.mktemp("no_env_root"))


@pytest.fixture(autouse=True)
def no_repair_round_unless_a_test_asks(monkeypatch):
    """Scripted providers answer a fixed number of calls; the investigation's repair round (limits
    INVESTIGATION_MAX_REPAIRS, 2 in the product) is tested on its own in tests/test_repair_loop.py."""
    monkeypatch.setenv("QO_INVESTIGATION_MAX_REPAIRS", "0")  # env, not OVERRIDES: create_app reloads those
