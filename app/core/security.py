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

def get_current_user(token: str = Depends(oauth2_scheme)) -> Tuple[int, str]:
    # returns (user_id, role)
    td = decode_token(token)
    if not td.sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    # Check token revocation/blacklist by jti or session
    if td.jti:
        with pg_cursor() as cur:
            cur.execute("SELECT revoked FROM refresh_tokens WHERE jti = %s", (td.jti,))
            row = cur.fetchone()
            if row and row[0]:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")

    # Ensure user exists and active
    with pg_cursor() as cur:
        cur.execute("SELECT id, role, is_active FROM users WHERE id = %s", (int(td.sub),))
        user_row = cur.fetchone()
        if not user_row:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        if not user_row[2]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is blocked")
        return user_row[0], user_row[1]


def require_admin(identity: Tuple[int, str] = Depends(get_current_user)) -> int:
    user_id, role = identity
    if role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return user_id
