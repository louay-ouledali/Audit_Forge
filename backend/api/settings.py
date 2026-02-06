from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.app_settings import AppSettings
from backend.schemas.settings import SettingsResponse, SettingsUpdate, SingleSettingResponse

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse)
def get_all_settings(db: Session = Depends(get_db)) -> dict:
    rows = db.query(AppSettings).all()
    data = {row.key: row.value for row in rows}
    return {"data": data, "message": "success"}


@router.put("", response_model=SettingsResponse)
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc)
    for key, value in payload.settings.items():
        existing = db.query(AppSettings).filter(AppSettings.key == key).first()
        if existing:
            existing.value = value
            existing.updated_at = now
        else:
            db.add(AppSettings(key=key, value=value, updated_at=now))
    db.commit()

    rows = db.query(AppSettings).all()
    data = {row.key: row.value for row in rows}
    return {"data": data, "message": "Settings updated"}


@router.get("/{key}", response_model=SingleSettingResponse)
def get_setting(key: str, db: Session = Depends(get_db)) -> dict:
    row = db.query(AppSettings).filter(AppSettings.key == key).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")
    return {"data": {row.key: row.value}, "message": "success"}
