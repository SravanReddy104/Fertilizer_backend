from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Body
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from jose import JWTError
from uuid import uuid4

from app.core.database import pg_cursor
from app.core.config import settings
from app.core.security import get_password_hash, verify_password, create_access_token, create_refresh_token, decode_token, get_current_user

router = APIRouter()

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: str
    expires_in: int

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    role: Optional[str] = None  # admin can set role later; default user

class MeResponse(BaseModel):
    id: int
    email: EmailStr
    full_name: Optional[str]
    role: str
    is_active: bool


@router.post("/register", response_model=MeResponse)
async def register(payload: RegisterRequest):
    # If first user, make admin; else default 'user'
    with pg_cursor(commit=True) as cur:
        cur.execute("SELECT COUNT(*) FROM users")
        total_users = cur.fetchone()[0]
        role = "admin" if total_users == 0 else "user"
        hashed = get_password_hash(payload.password)
        cur.execute(
            """
            INSERT INTO users (email, hashed_password, full_name, role)
            VALUES (%s, %s, %s, %s)
            RETURNING id, email, full_name, role, is_active
            """,
            (payload.email, hashed, payload.full_name, role),
        )
        row = cur.fetchone()
        return MeResponse(id=row[0], email=row[1], full_name=row[2], role=row[3], is_active=row[4])


@router.post("/login", response_model=TokenResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    # OAuth2PasswordRequestForm has username=, password=
    with pg_cursor() as cur:
        cur.execute("SELECT id, email, hashed_password, role, is_active FROM users WHERE email = %s", (form_data.username,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect email or password")
    user_id, email, hashed_password, role, is_active = row
    if not is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is blocked")
    if not verify_password(form_data.password, hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect email or password")

    jti = str(uuid4())
    access = create_access_token(subject=str(user_id), role=role, jti=jti)
    refresh = create_refresh_token(subject=str(user_id), role=role, jti=jti)

    # store refresh token metadata
    with pg_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO refresh_tokens (user_id, jti, revoked, expires_at)
            VALUES (%s, %s, false, %s)
            """,
            (user_id, jti, datetime.now(timezone.utc) + timedelta(days=14)),
        )

    return TokenResponse(access_token=access, refresh_token=refresh, expires_in=60 *  settings.access_token_expire_minutes)


class RefreshRequest(BaseModel):
    refresh_token: str

@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(payload: RefreshRequest):
    try:
        td = decode_token(payload.refresh_token)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    if not td.jti:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token jti")

    with pg_cursor() as cur:
        cur.execute("SELECT user_id, revoked, expires_at FROM refresh_tokens WHERE jti = %s", (td.jti,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh session not found")
        user_id, revoked, expires_at = row
        if revoked or (expires_at and expires_at < datetime.now(timezone.utc)):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired or revoked")

    new_jti = str(uuid4())
    access = create_access_token(subject=str(user_id), role=td.role, jti=new_jti)
    refresh = create_refresh_token(subject=str(user_id), role=td.role, jti=new_jti)

    with pg_cursor(commit=True) as cur:
        # revoke old and add new
        cur.execute("UPDATE refresh_tokens SET revoked = true WHERE jti = %s", (td.jti,))
        cur.execute(
            "INSERT INTO refresh_tokens (user_id, jti, revoked, expires_at) VALUES (%s, %s, false, %s)",
            (user_id, new_jti, datetime.now(timezone.utc) + timedelta(days=14)),
        )

    return TokenResponse(access_token=access, refresh_token=refresh, expires_in=60 * settings.access_token_expire_minutes)


@router.post("/logout")
async def logout(token: str = Body(..., embed=True)):
    # revoke by jti
    td = decode_token(token)
    if td.jti:
        with pg_cursor(commit=True) as cur:
            cur.execute("UPDATE refresh_tokens SET revoked = true WHERE jti = %s", (td.jti,))
    return {"success": True}


@router.get("/me", response_model=MeResponse)
async def me(identity = Depends(get_current_user)):
    user_id, role = identity
    with pg_cursor() as cur:
        cur.execute("SELECT id, email, full_name, role, is_active FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        return MeResponse(id=row[0], email=row[1], full_name=row[2], role=row[3], is_active=row[4])
