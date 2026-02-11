from __future__ import annotations

from pydantic import BaseModel


class SettingsResponse(BaseModel):
    data: dict[str, str]
    message: str = "success"


class SettingsUpdate(BaseModel):
    settings: dict[str, str]


class SingleSettingResponse(BaseModel):
    data: dict[str, str]
    message: str = "success"


class BackupResponse(BaseModel):
    message: str
    filename: str
    size_bytes: int


class RestoreResponse(BaseModel):
    message: str
    tables_restored: int
