from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from app.core.database import pg_cursor
from app.core.security import require_admin, get_password_hash

router = APIRouter(dependencies=[Depends(require_admin)])

class UserOut(BaseModel):
    id: int
    username: str
    email: Optional[EmailStr] = None
    full_name: Optional[str]
    role: str
    is_active: bool

class CreateUserRequest(BaseModel):
    username: str
    password: str
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    role: str

class UpdateRoleRequest(BaseModel):
    role: str  # 'admin' or 'user'

class UpdateActiveRequest(BaseModel):
    is_active: bool


@router.get("/users", response_model=List[UserOut])
async def list_users():
    with pg_cursor() as cur:
        cur.execute("SELECT id, username, email, full_name, role, is_active FROM users ORDER BY id ASC")
        rows = cur.fetchall()
        return [UserOut(id=r[0], username=r[1], email=r[2], full_name=r[3], role=r[4], is_active=r[5]) for r in rows]


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(payload: CreateUserRequest):
    if payload.role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="Invalid role")
    with pg_cursor(commit=True) as cur:
        # Check uniqueness
        cur.execute("SELECT 1 FROM users WHERE username = %s", (payload.username,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Username already exists")
        if payload.email:
            cur.execute("SELECT 1 FROM users WHERE email = %s", (payload.email,))
            if cur.fetchone():
                raise HTTPException(status_code=400, detail="Email already exists")

        hashed = get_password_hash(payload.password)
        cur.execute(
            """
            INSERT INTO users (username, email, hashed_password, full_name, role)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, username, email, full_name, role, is_active
            """,
            (payload.username, payload.email, hashed, payload.full_name, payload.role),
        )
        row = cur.fetchone()
        return UserOut(id=row[0], username=row[1], email=row[2], full_name=row[3], role=row[4], is_active=row[5])


@router.patch("/users/{user_id}/role")
async def update_role(user_id: int, payload: UpdateRoleRequest):
    if payload.role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="Invalid role")
    with pg_cursor(commit=True) as cur:
        cur.execute("UPDATE users SET role = %s WHERE id = %s RETURNING id", (payload.role, user_id))
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="User not found")
    return {"success": True}


@router.patch("/users/{user_id}/active")
async def update_active(user_id: int, payload: UpdateActiveRequest):
    with pg_cursor(commit=True) as cur:
        cur.execute("UPDATE users SET is_active = %s WHERE id = %s RETURNING id", (payload.is_active, user_id))
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="User not found")
    return {"success": True}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int):
    with pg_cursor(commit=True) as cur:
        # Revoke existing refresh tokens
        cur.execute("UPDATE refresh_tokens SET revoked = true WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM users WHERE id = %s RETURNING id", (user_id,))
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="User not found")
    return {"success": True}
