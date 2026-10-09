"""The Ollama the api asks (ADR-0050): CENTERLINE_OLLAMA_URL, from deploy/.env, over api.json's ai.url."""

import json

from centerline_api.settings import load_settings


def _settings(tmp_path, monkeypatch, env: str | None):
    cfg = tmp_path / "api.json"
    cfg.write_text(json.dumps({"timebase": {"base_url": "http://t"}, "ai": {"enabled": True, "url": "http://ollama:11434",
                                                                            "model": "qwen3.5:4b"}}))
    if env is None:
        monkeypatch.delenv("CENTERLINE_OLLAMA_URL", raising=False)
    else:
        monkeypatch.setenv("CENTERLINE_OLLAMA_URL", env)
    return load_settings(cfg).ai


def test_the_url_in_the_environment_wins_and_an_empty_one_leaves_api_json(tmp_path, monkeypatch):
    assert _settings(tmp_path, monkeypatch, "http://host.docker.internal:11434").url == "http://host.docker.internal:11434"
    assert _settings(tmp_path, monkeypatch, "  ").url == "http://ollama:11434"
    assert _settings(tmp_path, monkeypatch, None).url == "http://ollama:11434"
