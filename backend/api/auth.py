from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from backend.core.auth import (
    ACCESS_TOKEN_EXPIRE_HOURS,
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from backend.core.trail import log_action
from backend.database import get_db
from backend.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger("auditforge.api.auth")


# ── Schemas ──────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


# ── Endpoints ────────────────────────────────────────────────────────
@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
def login(request: Request, body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        log_action(db, action="login_failed", details={"username": body.username})
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    user.last_login = datetime.now(timezone.utc)
    log_action(db, user=user, action="login_success", entity_type="user", entity_id=user.id, entity_label=user.username)
    db.commit()

    token = create_access_token(user.id)

    # Set httpOnly cookie
    response.set_cookie(
        key="auditforge_token",
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=ACCESS_TOKEN_EXPIRE_HOURS * 3600,
    )

    return LoginResponse(
        access_token=token,
        user={"id": user.id, "username": user.username, "full_name": user.full_name},
    )


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """Clear the auth cookie and blacklist the token if it has a jti."""
    token = request.cookies.get("auditforge_token")
    if token:
        try:
            from jose import jwt as _jwt
            from backend.config import settings
            payload = _jwt.decode(token, settings.effective_jwt_key, algorithms=["HS256"])
            jti = payload.get("jti")
            exp = payload.get("exp")
            if jti and exp:
                from backend.models.token_blacklist import TokenBlacklist
                if not db.query(TokenBlacklist).filter(TokenBlacklist.jti == jti).first():
                    db.add(TokenBlacklist(
                        jti=jti,
                        expires_at=datetime.fromtimestamp(exp, tz=timezone.utc),
                    ))
                    db.commit()
        except Exception as _exc:
            logger.debug("Token blacklisting skipped: %s", _exc)  # Best-effort

    response.delete_cookie("auditforge_token", path="/")
    return {"message": "Logged out"}


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "full_name": current_user.full_name,
    }


@router.post("/ws-token")
def ws_token(current_user: User = Depends(get_current_user)):
    """Issue a short-lived token for WebSocket authentication."""
    from datetime import timedelta
    token = create_access_token(current_user.id, expires_delta=timedelta(seconds=60))
    return {"token": token}


@router.put("/change-password")
def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(body.old_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    current_user.password_hash = hash_password(body.new_password)
    log_action(db, user=current_user, action="password_changed", entity_type="user", entity_id=current_user.id, entity_label=current_user.username)
    db.commit()
    return {"message": "Password changed successfully"}
