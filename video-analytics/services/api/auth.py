"""JWT auth and password hashing.

Auth is optional and controlled by AUTH_ENABLED. When disabled the API is
open (useful for local dev / demos). When enabled, mutating stream and rule
endpoints require an admin JWT.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from api_config import get_config

cfg = get_config()

AUTH_ENABLED = os.getenv("AUTH_ENABLED", "0") == "1"

try:
    from jose import jwt, JWTError
except ImportError:  # pragma: no cover
    jwt = None
    JWTError = Exception

try:
    from passlib.context import CryptContext
    _pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
except ImportError:  # pragma: no cover
    _pwd = None

bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    if _pwd:
        return _pwd.hash(password)
    import hashlib
    return "sha256$" + hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    if _pwd and not password_hash.startswith("sha256$"):
        return _pwd.verify(password, password_hash)
    import hashlib
    return password_hash == "sha256$" + hashlib.sha256(password.encode()).hexdigest()


def create_access_token(subject: str, role: str = "operator", expires_minutes: int = 60) -> str:
    if not jwt:
        raise RuntimeError("python-jose is not installed")
    payload = {
        "sub": subject,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, cfg.jwt_secret, algorithm=cfg.jwt_alg)


def decode_token(token: str) -> dict:
    if not jwt:
        raise HTTPException(status_code=500, detail="auth backend unavailable")
    try:
        return jwt.decode(token, cfg.jwt_secret, algorithms=[cfg.jwt_alg])
    except JWTError:
        raise HTTPException(status_code=401, detail="invalid or expired token")


def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> Optional[dict]:
    if not AUTH_ENABLED:
        return {"sub": "anonymous", "role": "admin"}
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing credentials")
    return decode_token(credentials.credentials)


def require_admin(user: Optional[dict] = Depends(get_current_user)) -> dict:
    if not AUTH_ENABLED:
        return user or {"sub": "anonymous", "role": "admin"}
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin role required")
    return user
