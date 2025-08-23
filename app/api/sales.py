from fastapi import APIRouter, Query, Depends
from typing import List, Optional, Any, Dict
from datetime import datetime, date, timedelta
from app.models.models import Sale, SaleCreate, PaymentStatus
from app.core.database import pg_cursor
from app.core.logging import logger
from app.core.exceptions import NotFoundError, BadRequestError, DatabaseError
from app.core.security import get_current_user, require_admin


def _rows_to_dicts(cur) -> List[Dict[str, Any]]:
    columns = [d[0] for d in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]

router = APIRouter(dependencies=[Depends(get_current_user)])

@router.get("/", response_model=List[Sale])
async def get_sales(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    payment_status: Optional[PaymentStatus] = None,
    customer_name: Optional[str] = None
):
    """Get all sales with optional filtering, including sale items and product info."""
    logger.info(
        "GET /api/sales | skip=%s limit=%s start=%s end=%s status=%s customer=%s",
        skip,
        limit,
        start_date,
        end_date,
        payment_status.value if payment_status else None,
        customer_name,
    )
    where = []
    params: List[Any] = []
    if start_date:
        where.append("sale_date >= %s")
        params.append(start_date)
    if end_date:
        where.append("sale_date <= %s")
        params.append(end_date)
    if payment_status:
        where.append("payment_status = %s")
        params.append(payment_status.value)
    if customer_name:
        where.append("customer_name ILIKE %s")
        params.append(f"%{customer_name}%")

    sql = "SELECT * FROM sales"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY sale_date DESC, id DESC LIMIT %s OFFSET %s"
    params.extend([limit, skip])

    try:
        with pg_cursor() as cur:
            cur.execute(sql, params)
            sales = _rows_to_dicts(cur)
    except Exception as e:
        logger.error("Failed to fetch sales: %s", e)
        raise DatabaseError("Failed to fetch sales")

    if not sales:
        return []

    sale_ids = [s["id"] for s in sales]
    # Fetch items joined with products
    placeholders = ",".join(["%s"] * len(sale_ids))
    items_sql = (
        "SELECT si.*, p.name AS product_name, p.unit AS product_unit "
        "FROM sale_items si JOIN products p ON p.id = si.product_id "
        f"WHERE si.sale_id IN ({placeholders}) ORDER BY si.sale_id, si.id"
    )
    try:
        with pg_cursor() as cur:
            cur.execute(items_sql, sale_ids)
            items = _rows_to_dicts(cur)
    except Exception as e:
        logger.error("Failed to fetch sale items: %s", e)
        raise DatabaseError("Failed to fetch sale items")

    # Group items by sale_id
    by_sale: Dict[int, List[Dict[str, Any]]] = {}
    for it in items:
        by_sale.setdefault(it["sale_id"], []).append(it)

    for s in sales:
        s["items"] = by_sale.get(s["id"], [])
    return sales

@router.get("/{sale_id}", response_model=Sale)
async def get_sale(sale_id: int):
    """Get a specific sale by ID with items and product info."""
    logger.info("GET /api/sales/%s", sale_id)
    try:
        with pg_cursor() as cur:
            cur.execute("SELECT * FROM sales WHERE id = %s", (sale_id,))
            sale_rows = _rows_to_dicts(cur)
            if not sale_rows:
                raise NotFoundError("Sale not found")
            sale = sale_rows[0]

        with pg_cursor() as cur:
            cur.execute(
                """
                SELECT si.*, p.name AS product_name, p.unit AS product_unit
                FROM sale_items si JOIN products p ON p.id = si.product_id
                WHERE si.sale_id = %s ORDER BY si.id
                """,
                (sale_id,),
            )
            sale["items"] = _rows_to_dicts(cur)
        return sale
    except NotFoundError:
        logger.error("Sale %s not found", sale_id)
        raise
    except Exception as e:
        logger.error("Failed to fetch sale %s: %s", sale_id, e)
        raise DatabaseError("Failed to fetch sale")

@router.post("/", response_model=Sale)
async def create_sale(sale: SaleCreate, _: int = Depends(require_admin)):
    """Create a new sale with items and update product stock."""
    logger.info("POST /api/sales - creating sale for %s", sale.customer_name)
    total_amount = sum(item.total_price for item in sale.items)
    paid_amount = 0.0
    payment_status = PaymentStatus.PENDING.value

    try:
        with pg_cursor(commit=True) as cur:
            # Insert sale
            cur.execute(
            """
            INSERT INTO sales (customer_name, customer_phone, customer_address, total_amount, paid_amount, payment_status, notes, sale_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                sale.customer_name,
                sale.customer_phone,
                sale.customer_address,
                total_amount,
                paid_amount,
                payment_status,
                sale.notes,
                datetime.now(),
            ),
            )
            row = cur.fetchone()
            if not row:
                raise BadRequestError("Failed to create sale")
            (sale_id,) = row

            # Insert items and update stock
            for item in sale.items:
                cur.execute(
                """
                INSERT INTO sale_items (sale_id, product_id, quantity, unit_price, total_price)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (sale_id, item.product_id, item.quantity, item.unit_price, item.total_price),
                )
                # Decrement stock
                cur.execute(
                "UPDATE products SET stock_quantity = GREATEST(0, stock_quantity - %s) WHERE id = %s",
                (item.quantity, item.product_id),
                )
        logger.info("Sale %s created successfully", sale_id)
        return await get_sale(sale_id)
    except BadRequestError:
        logger.error("Failed to create sale - bad request")
        raise
    except Exception as e:
        logger.error("Failed to create sale: %s", e)
        raise DatabaseError("Failed to create sale")

@router.put("/{sale_id}/payment")
async def update_payment(sale_id: int, paid_amount: float, _: int = Depends(require_admin)):
    """Update payment for a sale"""
    logger.info("PUT /api/sales/%s/payment | paid_amount=%s", sale_id, paid_amount)
    try:
        with pg_cursor(commit=True) as cur:
            cur.execute("SELECT total_amount, paid_amount FROM sales WHERE id = %s", (sale_id,))
            row = cur.fetchone()
            if not row:
                raise NotFoundError("Sale not found")
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
                "UPDATE sales SET paid_amount = %s, payment_status = %s WHERE id = %s",
                (new_paid, status_val, sale_id),
            )

        logger.info("Payment updated for sale %s | paid=%s/%s", sale_id, new_paid, total_amount)
        return {"message": f"Payment updated. Paid: {new_paid}/{total_amount}"}
    except NotFoundError:
        logger.error("Sale %s not found for payment update", sale_id)
        raise
    except Exception as e:
        logger.error("Failed to update sale payment %s: %s", sale_id, e)
        raise DatabaseError("Failed to update sale payment")

@router.delete("/{sale_id}")
async def delete_sale(sale_id: int, _: int = Depends(require_admin)):
    """Delete a sale and restore stock"""
    logger.info("DELETE /api/sales/%s", sale_id)
    try:
        with pg_cursor(commit=True) as cur:
            # Fetch items
            cur.execute("SELECT product_id, quantity FROM sale_items WHERE sale_id = %s", (sale_id,))
            items = cur.fetchall()
            # Restore stock
            for product_id, qty in items:
                cur.execute(
                    "UPDATE products SET stock_quantity = stock_quantity + %s WHERE id = %s",
                    (qty, product_id),
                )
            # Delete sale items then sale
            cur.execute("DELETE FROM sale_items WHERE sale_id = %s", (sale_id,))
            cur.execute("DELETE FROM sales WHERE id = %s RETURNING id", (sale_id,))
            deleted = cur.fetchone()
            if not deleted:
                raise NotFoundError("Sale not found")
        logger.info("Sale %s deleted", sale_id)
        return {"message": "Sale deleted successfully"}
    except NotFoundError:
        logger.error("Sale %s not found for deletion", sale_id)
        raise
    except Exception as e:
        logger.error("Failed to delete sale %s: %s", sale_id, e)
        raise DatabaseError("Failed to delete sale")

@router.get("/stats/daily")
async def get_daily_sales_stats(date_filter: Optional[date] = None):
    """Get daily sales statistics"""
    if not date_filter:
        date_filter = date.today()
    next_day = date_filter + timedelta(days=1)
    logger.info("GET /api/sales/stats/daily | date=%s", date_filter)
    try:
        with pg_cursor() as cur:
            cur.execute(
                "SELECT total_amount, payment_status FROM sales WHERE sale_date >= %s AND sale_date < %s",
                (date_filter, next_day),
            )
            rows = cur.fetchall()

        total_sales = sum(r[0] for r in rows)
        paid_sales = sum(r[0] for r in rows if r[1] == PaymentStatus.PAID.value)
        pending_sales = sum(r[0] for r in rows if r[1] in (PaymentStatus.PENDING.value, PaymentStatus.PARTIAL.value))

        return {
            "date": date_filter,
            "total_sales": total_sales,
            "paid_sales": paid_sales,
            "pending_sales": pending_sales,
            "total_transactions": len(rows),
        }
    except Exception as e:
        logger.error("Failed to compute daily sales stats: %s", e)
        raise DatabaseError("Failed to compute daily sales stats")

