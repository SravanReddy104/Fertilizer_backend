from fastapi import APIRouter, Query, Depends
from typing import List, Optional, Any, Dict
from datetime import datetime, date
from app.models.models import Debt, DebtCreate, DebtUpdate, PaymentStatus
from app.core.database import pg_cursor
from app.core.logging import logger
from app.core.exceptions import NotFoundError, BadRequestError, DatabaseError
from app.core.security import get_current_user, require_admin


def _rows_to_dicts(cur) -> List[Dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

router = APIRouter(dependencies=[Depends(get_current_user)])

@router.get("/", response_model=List[Debt])
async def get_debts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status: Optional[PaymentStatus] = None,
    customer_name: Optional[str] = None,
    overdue_only: bool = False
):
    """Get all debts with optional filtering"""
    logger.info(
        "GET /api/debts | skip=%s limit=%s status=%s customer=%s overdue_only=%s",
        skip,
        limit,
        status.value if status else None,
        customer_name,
        overdue_only,
    )
    where = []
    params: List[Any] = []
    if status:
        where.append("status = %s")
        params.append(status.value)
    if customer_name:
        where.append("customer_name ILIKE %s")
        params.append(f"%{customer_name}%")
    if overdue_only:
        where.append("status = %s")
        params.append(PaymentStatus.OVERDUE.value)

    sql = "SELECT * FROM debts"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s"
    params.extend([limit, skip])
    try:
        with pg_cursor() as cur:
            cur.execute(sql, params)
            rows = _rows_to_dicts(cur)
            return rows
    except Exception as e:
        logger.error("Failed to fetch debts: %s", e)
        raise DatabaseError("Failed to fetch debts")

@router.get("/{debt_id}", response_model=Debt)
async def get_debt(debt_id: int):
    """Get a specific debt by ID"""
    logger.info("GET /api/debts/%s", debt_id)
    try:
        with pg_cursor() as cur:
            cur.execute("SELECT * FROM debts WHERE id = %s", (debt_id,))
            rows = _rows_to_dicts(cur)
        if not rows:
            raise NotFoundError("Debt not found")
        return rows[0]
    except NotFoundError:
        logger.error("Debt %s not found", debt_id)
        raise
    except Exception as e:
        logger.error("Failed to fetch debt %s: %s", debt_id, e)
        raise DatabaseError("Failed to fetch debt")

@router.post("/", response_model=Debt)
async def create_debt(debt: DebtCreate, _: int = Depends(require_admin)):
    """Create a new debt record"""
    logger.info("POST /api/debts - creating debt for %s", debt.customer_name)
    try:
        with pg_cursor(commit=True) as cur:
            cur.execute(
            """
            INSERT INTO debts (customer_name, amount, status, due_date, notes, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                debt.customer_name,
                debt.amount,
                debt.status.value if debt.status else PaymentStatus.PENDING.value,
                debt.due_date,
                debt.notes,
                datetime.now(),
            ),
            )
            row = cur.fetchone()
            if not row:
                raise BadRequestError("Failed to create debt")
            (debt_id,) = row
        logger.info("Debt %s created successfully", debt_id)
        return await get_debt(debt_id)
    except BadRequestError:
        logger.error("Failed to create debt - bad request or insert error")
        raise
    except Exception as e:
        logger.error("Failed to create debt: %s", e)
        raise DatabaseError("Failed to create debt")

@router.put("/{debt_id}", response_model=Debt)
async def update_debt(debt_id: int, debt: DebtUpdate, _: int = Depends(require_admin)):
    """Update a debt record"""
    logger.info("PUT /api/debts/%s", debt_id)
    # Build dynamic update
    data = {k: v for k, v in debt.dict().items() if v is not None}
    if not data:
        logger.info("No fields to update for debt %s", debt_id)
        return await get_debt(debt_id)
    set_parts = []
    params: List[Any] = []
    for k, v in data.items():
        if k == "status" and isinstance(v, PaymentStatus):
            v = v.value
        set_parts.append(f"{k} = %s")
        params.append(v)
    set_parts.append("updated_at = %s")
    params.append(datetime.now())
    params.append(debt_id)

    try:
        with pg_cursor(commit=True) as cur:
            cur.execute(
                f"UPDATE debts SET {', '.join(set_parts)} WHERE id = %s RETURNING id",
                params,
            )
            updated = cur.fetchone()
            if not updated:
                raise NotFoundError("Debt not found")
        logger.info("Debt %s updated", debt_id)
        return await get_debt(debt_id)
    except NotFoundError:
        logger.error("Debt %s not found for update", debt_id)
        raise
    except Exception as e:
        logger.error("Failed to update debt %s: %s", debt_id, e)
        raise DatabaseError("Failed to update debt")

@router.put("/{debt_id}/pay")
async def pay_debt(debt_id: int, amount: float = Query(...), _: int = Depends(require_admin)):
    """Make a payment towards a debt"""
    logger.info("PUT /api/debts/%s/pay | amount=%s", debt_id, amount)
    try:
        with pg_cursor(commit=True) as cur:
            cur.execute("SELECT amount, status FROM debts WHERE id = %s", (debt_id,))
            row = cur.fetchone()
            if not row:
                raise NotFoundError("Debt not found")
            current_amount, current_status = row
            new_amount = max(0.0, float(current_amount) - float(amount))

            if new_amount == 0:
                new_status = PaymentStatus.PAID.value
            elif new_amount < current_amount:
                new_status = PaymentStatus.PARTIAL.value
            else:
                new_status = current_status

            cur.execute(
                "UPDATE debts SET amount = %s, status = %s, updated_at = %s WHERE id = %s RETURNING id",
                (new_amount, new_status, datetime.now(), debt_id),
            )
            updated = cur.fetchone()
            if not updated:
                raise BadRequestError("Failed to update debt payment")
        logger.info("Debt %s payment updated | remaining=%s", debt_id, new_amount)
        return {"message": f"Payment recorded. Remaining debt: {new_amount}"}
    except NotFoundError:
        logger.error("Debt %s not found for payment", debt_id)
        raise
    except BadRequestError:
        logger.error("Failed to update payment for debt %s - bad request", debt_id)
        raise
    except Exception as e:
        logger.error("Failed to update debt payment %s: %s", debt_id, e)
        raise DatabaseError("Failed to update debt payment")

@router.delete("/{debt_id}")
async def delete_debt(debt_id: int, _: int = Depends(require_admin)):
    """Delete a debt record"""
    logger.info("DELETE /api/debts/%s", debt_id)
    try:
        with pg_cursor(commit=True) as cur:
            cur.execute("DELETE FROM debts WHERE id = %s RETURNING id", (debt_id,))
            deleted = cur.fetchone()
            if not deleted:
                raise NotFoundError("Debt not found")
        logger.info("Debt %s deleted", debt_id)
        return {"message": "Debt deleted successfully"}
    except NotFoundError:
        logger.error("Debt %s not found for deletion", debt_id)
        raise
    except Exception as e:
        logger.error("Failed to delete debt %s: %s", debt_id, e)
        raise DatabaseError("Failed to delete debt")

@router.get("/stats/summary")
async def get_debt_summary():
    """Get debt summary statistics"""
    logger.info("GET /api/debts/stats/summary")
    try:
        with pg_cursor() as cur:
            cur.execute(
            """
            SELECT 
                COALESCE(SUM(amount),0) AS total_debt,
                COALESCE(SUM(CASE WHEN status='paid' THEN amount ELSE 0 END),0) AS paid_debt,
                COALESCE(SUM(CASE WHEN status IN ('pending','partial') THEN amount ELSE 0 END),0) AS pending_debt,
                COALESCE(SUM(CASE WHEN status='overdue' THEN amount ELSE 0 END),0) AS overdue_debt,
                COUNT(*) AS total_records
            FROM debts
            """
            )
            row = cur.fetchone()
            total_debt, paid_debt, pending_debt, overdue_debt, total_records = row
        payload = {
            "total_debt": total_debt,
            "paid_debt": paid_debt,
            "pending_debt": pending_debt,
            "overdue_debt": overdue_debt,
            "total_records": total_records,
        }
        logger.info("Debt summary computed")
        return payload
    except Exception as e:
        logger.error("Failed to compute debt summary: %s", e)
        raise DatabaseError("Failed to compute debt summary")

@router.post("/mark-overdue")
async def mark_overdue_debts(_: int = Depends(require_admin)):
    """Mark debts as overdue based on due date"""
    current_date = date.today()
    logger.info("POST /api/debts/mark-overdue | date=%s", current_date)
    try:
        with pg_cursor(commit=True) as cur:
            cur.execute(
            """
            UPDATE debts
            SET status = %s, updated_at = %s
            WHERE due_date < %s AND status IN ('pending','partial')
            RETURNING id
            """,
            (PaymentStatus.OVERDUE.value, datetime.now(), current_date),
            )
            updated_rows = cur.fetchall()
        logger.info("Marked %s debts as overdue", len(updated_rows))
        return {"message": f"Marked {len(updated_rows)} debts as overdue"}
    except Exception as e:
        logger.error("Failed to mark overdue debts: %s", e)
        raise DatabaseError("Failed to mark overdue debts")

