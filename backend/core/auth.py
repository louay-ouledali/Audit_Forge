from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.hash import bcrypt
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models.user import User

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 8


class _OAuth2CookieOrBearer(OAuth2PasswordBearer):
    """Extract token from httpOnly cookie first, then fall back to Authorization header."""

    async def __call__(self, request: Request) -> str:  # type: ignore[override]
        # Try cookie first
        token = request.cookies.get("auditforge_token")
        if token:
            return token
        # Fall back to Bearer header (transition period + API clients)
        return await super().__call__(request)


oauth2_scheme = _OAuth2CookieOrBearer(tokenUrl="/api/auth/login")


def hash_password(plain: str) -> str:
    return bcrypt.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.verify(plain, hashed)


def create_access_token(user_id: int, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS))
    jti = str(uuid.uuid4())
    payload = {"sub": str(user_id), "exp": expire, "jti": jti}
    return jwt.encode(payload, settings.effective_jwt_key, algorithm=ALGORITHM)


def _is_token_blacklisted(jti: str, db: Session) -> bool:
    """Check if a token's jti is in the blacklist."""
    from backend.models.token_blacklist import TokenBlacklist
    return db.query(TokenBlacklist).filter(TokenBlacklist.jti == jti).first() is not None


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.effective_jwt_key, algorithms=[ALGORITHM])
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except (JWTError, ValueError):
        # Fallback: try legacy SECRET_KEY for tokens issued before key separation
        if settings.effective_jwt_key != settings.SECRET_KEY:
            try:
                payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
                user_id = payload.get("sub")
                if user_id is None:
                    raise credentials_exception
            except (JWTError, ValueError):
                raise credentials_exception
        else:
            raise credentials_exception

    # Check blacklist
    jti = payload.get("jti")
    if jti and _is_token_blacklisted(jti, db):
        raise credentials_exception

    try:
        uid = int(user_id)
    except (ValueError, TypeError):
        raise credentials_exception
    user = db.query(User).filter(User.id == uid).first()
    if user is None:
        raise credentials_exception
    return user
