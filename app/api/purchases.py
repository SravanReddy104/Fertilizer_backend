from fastapi import APIRouter, Query, Depends
from typing import List, Optional, Any, Dict
from datetime import datetime, date, timedelta
from app.models.models import Purchase, PurchaseCreate, PaymentStatus
from app.core.database import pg_cursor
from app.core.logging import logger
from app.core.exceptions import NotFoundError, BadRequestError, DatabaseError
from app.core.security import get_current_user, require_admin


def _rows_to_dicts(cur) -> List[Dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

router = APIRouter(dependencies=[Depends(get_current_user)])

@router.get("/", response_model=List[Purchase])
async def get_purchases(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    payment_status: Optional[PaymentStatus] = None,
    supplier_name: Optional[str] = None
):
    """Get all purchases with optional filtering and include items with product info."""
    logger.info(
        "GET /api/purchases | skip=%s limit=%s start=%s end=%s status=%s supplier=%s",
        skip,
        limit,
        start_date,
        end_date,
        payment_status.value if payment_status else None,
        supplier_name,
    )
    where = []
    params: List[Any] = []
    if start_date:
        where.append("purchase_date >= %s")
        params.append(start_date)
    if end_date:
        where.append("purchase_date <= %s")
        params.append(end_date)
    if payment_status:
        where.append("payment_status = %s")
        params.append(payment_status.value)
    if supplier_name:
        where.append("supplier_name ILIKE %s")
        params.append(f"%{supplier_name}%")

    sql = "SELECT * FROM purchases"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY purchase_date DESC, id DESC LIMIT %s OFFSET %s"
    params.extend([limit, skip])

    try:
        with pg_cursor() as cur:
            cur.execute(sql, params)
            purchases = _rows_to_dicts(cur)
    except Exception as e:
        logger.error("Failed to fetch purchases: %s", e)
        raise DatabaseError("Failed to fetch purchases")

    if not purchases:
        return []

    purchase_ids = [p["id"] for p in purchases]
    placeholders = ",".join(["%s"] * len(purchase_ids))
    items_sql = (
        "SELECT pi.*, pr.name AS product_name, pr.unit AS product_unit "
        "FROM purchase_items pi JOIN products pr ON pr.id = pi.product_id "
        f"WHERE pi.purchase_id IN ({placeholders}) ORDER BY pi.purchase_id, pi.id"
    )
    try:
        with pg_cursor() as cur:
            cur.execute(items_sql, purchase_ids)
            items = _rows_to_dicts(cur)
    except Exception as e:
        logger.error("Failed to load purchase items: %s", e)
        raise DatabaseError("Failed to fetch purchase items")

    by_purchase: Dict[int, List[Dict[str, Any]]] = {}
    for it in items:
        by_purchase.setdefault(it["purchase_id"], []).append(it)

    for p in purchases:
        p["items"] = by_purchase.get(p["id"], [])
    return purchases

@router.get("/{purchase_id}", response_model=Purchase)
async def get_purchase(purchase_id: int):
    """Get a specific purchase by ID with items and product info"""
    logger.info("GET /api/purchases/%s", purchase_id)
    try:
        with pg_cursor() as cur:
            cur.execute("SELECT * FROM purchases WHERE id = %s", (purchase_id,))
            rows = _rows_to_dicts(cur)
            if not rows:
                raise NotFoundError("Purchase not found")
            purchase = rows[0]

        with pg_cursor() as cur:
            cur.execute(
                """
                SELECT pi.*, pr.name AS product_name, pr.unit AS product_unit
                FROM purchase_items pi JOIN products pr ON pr.id = pi.product_id
                WHERE pi.purchase_id = %s ORDER BY pi.id
                """,
                (purchase_id,),
            )
            purchase["items"] = _rows_to_dicts(cur)
        return purchase
    except NotFoundError:
        logger.error("Purchase %s not found", purchase_id)
        raise
    except Exception as e:
        logger.error("Failed to load purchase %s: %s", purchase_id, e)
        raise DatabaseError("Failed to load purchase")

@router.post("/", response_model=Purchase)
async def create_purchase(purchase: PurchaseCreate, _: int = Depends(require_admin)):
    """Create a new purchase and increase product stock"""
    logger.info("POST /api/purchases - creating purchase for %s", purchase.supplier_name)
    total_amount = sum(item.total_price for item in purchase.items)
    paid_amount = 0.0
    status_val = PaymentStatus.PENDING.value

    try:
        with pg_cursor(commit=True) as cur:
            cur.execute(
            """
            INSERT INTO purchases (supplier_name, supplier_phone, supplier_address, total_amount, paid_amount, payment_status, notes, purchase_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                purchase.supplier_name,
                purchase.supplier_phone,
                purchase.supplier_address,
                total_amount,
                paid_amount,
                status_val,
                purchase.notes,
                datetime.now(),
            ),
            )
            row = cur.fetchone()
            if not row:
                raise BadRequestError("Failed to create purchase")
            (purchase_id,) = row

            for item in purchase.items:
                cur.execute(
                """
                INSERT INTO purchase_items (purchase_id, product_id, quantity, unit_price, total_price)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (purchase_id, item.product_id, item.quantity, item.unit_price, item.total_price),
                )
                # Increase stock
                cur.execute(
                "UPDATE products SET stock_quantity = stock_quantity + %s WHERE id = %s",
                (item.quantity, item.product_id),
                )
        logger.info("Purchase %s created successfully", purchase_id)
        return await get_purchase(purchase_id)
    except BadRequestError:
        logger.error("Failed to create purchase - validation or insert error")
        raise
    except Exception as e:
        logger.error("Failed to create purchase: %s", e)
        raise DatabaseError("Failed to create purchase")

@router.put("/{purchase_id}/payment")
async def update_payment(purchase_id: int, paid_amount: float = Query(...), _: int = Depends(require_admin)):
    """Update payment for a purchase"""
    logger.info("PUT /api/purchases/%s/payment | paid_amount=%s", purchase_id, paid_amount)
    try:
        with pg_cursor(commit=True) as cur:
            cur.execute("SELECT total_amount, paid_amount FROM purchases WHERE id = %s", (purchase_id,))
            row = cur.fetchone()
            if not row:
                raise NotFoundError("Purchase not found")
            total_amount, current_paid = row
            new_paid = current_paid + paid_amount

            if new_paid >= total_amount:
                status_val = PaymentStatus.PAID.value
                new_paid = total_amount
            elif new_paid > 0:
                status_val = PaymentStatus.PARTIAL.value
            else:
                status_val = PaymentStatus.PENDING.value

            cur.execute(
                "UPDATE purchases SET paid_amount = %s, payment_status = %s WHERE id = %s",
                (new_paid, status_val, purchase_id),
            )
        logger.info("Payment updated for purchase %s | paid=%s/%s", purchase_id, new_paid, total_amount)
        return {"message": f"Payment updated. Paid: {new_paid}/{total_amount}"}
    except NotFoundError:
        logger.error("Purchase %s not found for payment update", purchase_id)
        raise
    except Exception as e:
        logger.error("Failed to update purchase payment %s: %s", purchase_id, e)
        raise DatabaseError("Failed to update purchase payment")

@router.delete("/{purchase_id}")
async def delete_purchase(purchase_id: int, _: int = Depends(require_admin)):
    """Delete a purchase and adjust stock"""
    logger.info("DELETE /api/purchases/%s", purchase_id)
    try:
        with pg_cursor(commit=True) as cur:
            cur.execute("SELECT product_id, quantity FROM purchase_items WHERE purchase_id = %s", (purchase_id,))
            items = cur.fetchall()

            # Reduce stock for each item that was added by this purchase
            for product_id, qty in items:
                cur.execute(
                    "UPDATE products SET stock_quantity = GREATEST(0, stock_quantity - %s) WHERE id = %s",
                    (qty, product_id),
                )

            cur.execute("DELETE FROM purchase_items WHERE purchase_id = %s", (purchase_id,))
            cur.execute("DELETE FROM purchases WHERE id = %s RETURNING id", (purchase_id,))
            deleted = cur.fetchone()
            if not deleted:
                raise NotFoundError("Purchase not found")
        logger.info("Purchase %s deleted", purchase_id)
        return {"message": "Purchase deleted successfully"}
    except NotFoundError:
        logger.error("Purchase %s not found for deletion", purchase_id)
        raise
    except Exception as e:
        logger.error("Failed to delete purchase %s: %s", purchase_id, e)
        raise DatabaseError("Failed to delete purchase")

@router.get("/stats/daily")
async def get_daily_purchase_stats(date_filter: Optional[date] = None):
    """Get daily purchase statistics"""
    if not date_filter:
        date_filter = date.today()
    next_day = date_filter + timedelta(days=1)
    logger.info("GET /api/purchases/stats/daily | date=%s", date_filter)
    try:
        with pg_cursor() as cur:
            cur.execute(
                "SELECT total_amount, payment_status FROM purchases WHERE purchase_date >= %s AND purchase_date < %s",
                (date_filter, next_day),
            )
            rows = cur.fetchall()

        total_purchases = sum(r[0] for r in rows)
        paid_purchases = sum(r[0] for r in rows if r[1] == PaymentStatus.PAID.value)
        pending_purchases = sum(r[0] for r in rows if r[1] in (PaymentStatus.PENDING.value, PaymentStatus.PARTIAL.value))

        payload = {
            "date": date_filter,
            "total_purchases": total_purchases,
            "paid_purchases": paid_purchases,
            "pending_purchases": pending_purchases,
            "total_transactions": len(rows),
        }
        logger.info("Daily purchase stats computed | date=%s", date_filter)
        return payload
    except Exception as e:
        logger.error("Failed to compute daily purchase stats: %s", e)
        raise DatabaseError("Failed to compute daily purchase stats")

