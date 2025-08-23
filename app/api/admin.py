from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from app.core.database import pg_cursor
from app.core.security import require_admin

router = APIRouter(dependencies=[Depends(require_admin)])

class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: Optional[str]
    role: str
    is_active: bool

class UpdateRoleRequest(BaseModel):
    role: str  # 'admin' or 'user'

class UpdateActiveRequest(BaseModel):
    is_active: bool


@router.get("/users", response_model=List[UserOut])
async def list_users():
    with pg_cursor() as cur:
        cur.execute("SELECT id, email, full_name, role, is_active FROM users ORDER BY id ASC")
        rows = cur.fetchall()
        return [UserOut(id=r[0], email=r[1], full_name=r[2], role=r[3], is_active=r[4]) for r in rows]


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
