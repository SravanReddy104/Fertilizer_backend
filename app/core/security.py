from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from app.core.config import settings
from app.core.database import pg_cursor
from pydantic import BaseModel

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

class TokenData(BaseModel):
    sub: str
    role: str
    jti: Optional[str] = None

# Password hashing

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


# JWT helpers

def create_access_token(subject: str, role: str, expires_minutes: int = settings.access_token_expire_minutes, jti: Optional[str] = None) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=expires_minutes)
    payload = {"sub": subject, "role": role, "exp": expire, "iat": now, "jti": jti}
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    return token


def create_refresh_token(subject: str, role: str, expires_days: int = 14, jti: Optional[str] = None) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=expires_days)
    payload = {"sub": subject, "role": role, "exp": expire, "iat": now, "jti": jti, "type": "refresh"}
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    return token


def decode_token(token: str) -> TokenData:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return TokenData(sub=payload.get("sub"), role=payload.get("role"), jti=payload.get("jti"))
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")


# Dependencies

def get_current_user() -> Tuple[int, str]:
    """TEMP: Auth disabled. Allow all requests as an 'admin' user.
    Returns a dummy identity tuple (user_id, role).
    """
    return 0, "admin"


def require_admin(identity: Tuple[int, str] = Depends(get_current_user)) -> int:
    """TEMP: Auth disabled. Everyone is treated as admin."""
    return 0
