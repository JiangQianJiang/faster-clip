import importlib
import json
from pathlib import Path

from fastapi.testclient import TestClient


def _client_with_settings_file(
    monkeypatch, tmp_path: Path, initial: dict
) -> tuple[TestClient, Path]:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps(initial), encoding="utf-8")
    monkeypatch.setenv("APP_SETTINGS_PATH", str(settings_path))

    import app.config
    import app.main

    importlib.reload(app.config)
    importlib.reload(app.main)
    return TestClient(app.main.app), settings_path


def test_get_api_settings_does_not_return_plaintext_keys(monkeypatch, tmp_path):
    client, _settings_path = _client_with_settings_file(
        monkeypatch,
        tmp_path,
        {
            "llm": {
                "api_key": "llm-secret",
                "base_url": "https://llm.example.com",
                "model": "llm-model",
            },
            "asr": {
                "api_key": "asr-secret",
                "provider": "qwen",
                "base_url": "https://asr.example.com",
                "model": "asr-model",
            },
        },
    )

    response = client.get("/api/settings/api")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "llm_base_url": "https://llm.example.com",
        "llm_model": "llm-model",
        "llm_api_key_configured": True,
        "asr_provider": "qwen",
        "asr_base_url": "https://asr.example.com",
        "asr_model": "asr-model",
        "asr_api_key_configured": True,
    }
    assert "llm-secret" not in response.text
    assert "asr-secret" not in response.text


def test_put_api_settings_preserves_existing_keys_and_unrelated_settings(monkeypatch, tmp_path):
    client, settings_path = _client_with_settings_file(
        monkeypatch,
        tmp_path,
        {
            "app_name": "custom-name",
            "runtime": {"retention_days": 3},
            "llm": {
                "api_key": "existing-llm-key",
                "base_url": "https://old-llm.example.com",
                "model": "old-llm",
            },
            "asr": {
                "api_key": "existing-asr-key",
                "provider": "qwen",
                "base_url": "https://old-asr.example.com",
                "model": "old-asr",
            },
        },
    )

    response = client.put(
        "/api/settings/api",
        json={
            "llm_base_url": "https://new-llm.example.com",
            "llm_model": "new-llm",
            "llm_api_key": "",
            "asr_provider": "whisper_api",
            "asr_base_url": "https://new-asr.example.com",
            "asr_model": "new-asr",
        },
    )

    assert response.status_code == 200
    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    assert saved["app_name"] == "custom-name"
    assert saved["runtime"] == {"retention_days": 3}
    assert saved["llm"] == {
        "api_key": "existing-llm-key",
        "base_url": "https://new-llm.example.com",
        "model": "new-llm",
    }
    assert saved["asr"] == {
        "api_key": "existing-asr-key",
        "provider": "whisper_api",
        "base_url": "https://new-asr.example.com",
        "model": "new-asr",
    }


def test_put_api_settings_updates_keys_and_refreshes_runtime_settings(monkeypatch, tmp_path):
    client, _settings_path = _client_with_settings_file(
        monkeypatch,
        tmp_path,
        {
            "llm": {
                "api_key": "old-llm-key",
                "base_url": "https://old-llm.example.com",
                "model": "old-llm",
            },
            "asr": {
                "api_key": "old-asr-key",
                "provider": "qwen",
                "base_url": "https://old-asr.example.com",
                "model": "old-asr",
            },
        },
    )

    response = client.put(
        "/api/settings/api",
        json={
            "llm_api_key": "new-llm-key",
            "llm_base_url": "https://new-llm.example.com",
            "llm_model": "new-llm",
            "asr_api_key": "new-asr-key",
            "asr_provider": "qwen",
            "asr_base_url": "https://new-asr.example.com",
            "asr_model": "new-asr",
        },
    )

    assert response.status_code == 200

    import app.config
    import app.api.tasks_crud

    assert app.config.settings.llm_api_key == "new-llm-key"
    assert app.config.settings.llm_base_url == "https://new-llm.example.com"
    assert app.config.settings.llm_model == "new-llm"
    assert app.config.settings.asr_api_key == "new-asr-key"
    assert app.config.settings.default_asr_provider == "qwen"
    assert app.config.settings.asr_base_url == "https://new-asr.example.com"
    assert app.config.settings.asr_model == "new-asr"
    assert app.api.tasks_crud.settings.llm_api_key == "new-llm-key"
    assert app.api.tasks_crud.settings.asr_api_key == "new-asr-key"


def test_put_api_settings_rejects_invalid_provider(monkeypatch, tmp_path):
    client, _settings_path = _client_with_settings_file(monkeypatch, tmp_path, {})

    response = client.put(
        "/api/settings/api",
        json={
            "llm_base_url": "https://llm.example.com",
            "llm_model": "llm-model",
            "asr_provider": "bad-provider",
            "asr_base_url": "https://asr.example.com",
            "asr_model": "asr-model",
        },
    )

    assert response.status_code == 422


def test_get_presets_returns_llm_and_asr_presets(monkeypatch, tmp_path):
    import os as _os

    presets_abs = _os.path.abspath(
        _os.path.join(
            _os.path.dirname(__file__), "..", "..", "data", "presets", "api_providers.json"
        )
    )
    monkeypatch.setenv("APP_PRESETS_PATH", presets_abs)
    client, _settings_path = _client_with_settings_file(monkeypatch, tmp_path, {})

    response = client.get("/api/settings/presets")

    assert response.status_code == 200
    body = response.json()
    assert "llm" in body
    assert "asr" in body
    assert isinstance(body["llm"], list)
    assert isinstance(body["asr"], list)
    assert len(body["llm"]) >= 1
    assert len(body["asr"]) >= 1
    deepseek = next((p for p in body["llm"] if p["id"] == "deepseek"), None)
    assert deepseek is not None
    assert deepseek["base_url"] == "https://api.deepseek.com/anthropic"
    assert deepseek["model"] == "deepseek-v4-pro"
    qwen = next((p for p in body["asr"] if p["id"] == "qwen"), None)
    assert qwen is not None
    assert qwen["provider"] == "qwen"
    assert qwen["base_url"] == "https://dashscope.aliyuncs.com"
    assert qwen["model"] == "qwen3-asr-flash-filetrans"
