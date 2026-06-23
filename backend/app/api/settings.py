import json
import os
import sys
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.services.settings_file import load_settings_file, nested_get, save_settings_file

router = APIRouter(prefix="/api/settings", tags=["settings"])

AsrProvider = Literal["qwen", "whisper_api"]


class ApiSettingsResponse(BaseModel):
    llm_base_url: str
    llm_model: str
    llm_api_key_configured: bool
    asr_provider: AsrProvider
    asr_base_url: str
    asr_model: str
    asr_api_key_configured: bool


class ApiSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm_api_key: str | None = None
    llm_base_url: HttpUrl
    llm_model: str = Field(min_length=1)
    asr_api_key: str | None = None
    asr_provider: AsrProvider
    asr_base_url: HttpUrl
    asr_model: str = Field(min_length=1)


def _api_settings_response(file_settings: dict) -> ApiSettingsResponse:
    from app.config import settings

    llm_api_key = str(nested_get(file_settings, "llm.api_key", settings.llm_api_key) or "")
    asr_api_key = str(nested_get(file_settings, "asr.api_key", settings.asr_api_key) or "")
    return ApiSettingsResponse(
        llm_base_url=str(nested_get(file_settings, "llm.base_url", settings.llm_base_url) or ""),
        llm_model=str(nested_get(file_settings, "llm.model", settings.llm_model) or ""),
        llm_api_key_configured=bool(llm_api_key.strip()),
        asr_provider=str(
            nested_get(file_settings, "asr.provider", settings.default_asr_provider) or "qwen"
        ),
        asr_base_url=str(nested_get(file_settings, "asr.base_url", settings.asr_base_url) or ""),
        asr_model=str(nested_get(file_settings, "asr.model", settings.asr_model) or ""),
        asr_api_key_configured=bool(asr_api_key.strip()),
    )


def _refresh_runtime_settings() -> None:
    import app.config

    refreshed = app.config.Settings()
    app.config.settings = refreshed
    for module_name, module in list(sys.modules.items()):
        if not module_name.startswith("app."):
            continue
        cached = getattr(module, "settings", None)
        if hasattr(cached, "llm_api_key") and hasattr(cached, "asr_api_key"):
            module.settings = refreshed


def _merge_api_settings(file_settings: dict, update: ApiSettingsUpdate) -> dict:
    merged = dict(file_settings)
    llm = dict(merged.get("llm") if isinstance(merged.get("llm"), dict) else {})
    asr = dict(merged.get("asr") if isinstance(merged.get("asr"), dict) else {})

    llm["base_url"] = str(update.llm_base_url).rstrip("/")
    llm["model"] = update.llm_model.strip()
    if update.llm_api_key and update.llm_api_key.strip():
        llm["api_key"] = update.llm_api_key.strip()

    asr["provider"] = update.asr_provider
    asr["base_url"] = str(update.asr_base_url).rstrip("/")
    asr["model"] = update.asr_model.strip()
    if update.asr_api_key and update.asr_api_key.strip():
        asr["api_key"] = update.asr_api_key.strip()

    merged["llm"] = llm
    merged["asr"] = asr
    return merged


@router.get("/api", response_model=ApiSettingsResponse)
def get_api_settings():
    return _api_settings_response(load_settings_file())


@router.put("/api", response_model=ApiSettingsResponse)
def update_api_settings(update: ApiSettingsUpdate):
    file_settings = load_settings_file()
    merged = _merge_api_settings(file_settings, update)
    try:
        save_settings_file(merged)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="保存设置失败") from exc
    _refresh_runtime_settings()
    return _api_settings_response(merged)


def _load_presets() -> dict:
    path = Path(os.getenv("APP_PRESETS_PATH", "data/presets/api_providers.json"))
    if not path.is_file():
        return {"llm": [], "asr": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"llm": [], "asr": []}


@router.get("/presets")
def get_presets():
    return _load_presets()
