from fastapi import APIRouter, Depends
from datetime import date, timedelta
from typing import List, Dict, Any
from app.models.models import DashboardStats
from app.core.database import pg_cursor
from app.core.logging import logger
from app.core.exceptions import DatabaseError
from app.core.security import get_current_user


def _rows_to_dicts(cur) -> List[Dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

router = APIRouter(dependencies=[Depends(get_current_user)])

@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats():
    """Get comprehensive dashboard statistics"""
    logger.info("GET /api/dashboard/stats - computing dashboard statistics")
    try:
        # Totals and counts
        with pg_cursor() as cur:
            cur.execute("SELECT COALESCE(SUM(total_amount),0) FROM sales WHERE payment_status = 'paid'")
            (total_sales,) = cur.fetchone()
            cur.execute("SELECT COALESCE(SUM(total_amount),0) FROM purchases WHERE payment_status = 'paid'")
            (total_purchases,) = cur.fetchone()
            cur.execute("SELECT COUNT(*), COALESCE(SUM(CASE WHEN stock_quantity <= minimum_stock THEN 1 ELSE 0 END),0) FROM products")
            total_products, low_stock_products = cur.fetchone()
            cur.execute("SELECT COALESCE(SUM(amount),0) FROM debts WHERE status IN ('pending','partial','overdue')")
            (total_debts,) = cur.fetchone()

        # Recent sales (5) with item count
        with pg_cursor() as cur:
            cur.execute(
                """
                SELECT s.*, (
                    SELECT COUNT(*) FROM sale_items si WHERE si.sale_id = s.id
                ) AS items_count
                FROM sales s ORDER BY s.sale_date DESC, s.id DESC LIMIT 5
                """
            )
            recent_sales = _rows_to_dicts(cur)

        # Recent purchases (5) with item count
        with pg_cursor() as cur:
            cur.execute(
                """
                SELECT p.*, (
                    SELECT COUNT(*) FROM purchase_items pi WHERE pi.purchase_id = p.id
                ) AS items_count
                FROM purchases p ORDER BY p.purchase_date DESC, p.id DESC LIMIT 5
                """
            )
            recent_purchases = _rows_to_dicts(cur)

        # Pending debts (10)
        with pg_cursor() as cur:
            cur.execute(
                "SELECT * FROM debts WHERE status IN ('pending','partial','overdue') ORDER BY created_at DESC LIMIT 10"
            )
            pending_debts = _rows_to_dicts(cur)

        logger.info(
            "Dashboard stats computed | sales=%s purchases=%s debts=%s products=%s low_stock=%s",
            total_sales,
            total_purchases,
            total_debts,
            total_products,
            low_stock_products,
        )
        return DashboardStats(
            total_sales=total_sales,
            total_purchases=total_purchases,
            total_debts=total_debts,
            total_products=total_products,
            low_stock_products=low_stock_products,
            recent_sales=recent_sales,
            recent_purchases=recent_purchases,
            pending_debts=pending_debts,
        )
    except Exception as e:
        logger.error("Failed to compute dashboard stats: %s", e)
        raise DatabaseError("Failed to compute dashboard stats")

@router.get("/sales-trend")
async def get_sales_trend(days: int = 30):
    """Get sales trend for the last N days"""
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    logger.info("GET /api/dashboard/sales-trend | days=%s", days)
    try:
        with pg_cursor() as cur:
            cur.execute(
                """
                SELECT CAST(sale_date AS date) AS d, total_amount, payment_status
                FROM sales
                WHERE sale_date >= %s AND sale_date <= %s
                ORDER BY d
                """,
                (start_date, end_date),
            )
            rows = _rows_to_dicts(cur)

        daily_sales: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            day = str(r["d"])  # YYYY-MM-DD
            if day not in daily_sales:
                daily_sales[day] = {"total": 0, "paid": 0, "count": 0}
            daily_sales[day]["total"] += r["total_amount"]
            daily_sales[day]["count"] += 1
            if r["payment_status"] == "paid":
                daily_sales[day]["paid"] += r["total_amount"]

        logger.info("Sales trend computed for %s days | days_with_sales=%s", days, len(daily_sales))
        return daily_sales
    except Exception as e:
        logger.error("Failed to compute sales trend: %s", e)
        raise DatabaseError("Failed to compute sales trend")

@router.get("/top-products")
async def get_top_selling_products(limit: int = 10):
    """Get top selling products"""
    logger.info("GET /api/dashboard/top-products | limit=%s", limit)
    try:
        with pg_cursor() as cur:
            cur.execute(
                """
                SELECT p.id AS product_id, p.name, p.type, COALESCE(SUM(si.quantity),0) AS total_quantity
                FROM sale_items si
                JOIN products p ON p.id = si.product_id
                GROUP BY p.id, p.name, p.type
                ORDER BY total_quantity DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = _rows_to_dicts(cur)
        logger.info("Top products computed | count=%s", len(rows))
        return rows
    except Exception as e:
        logger.error("Failed to compute top products: %s", e)
        raise DatabaseError("Failed to compute top products")

@router.get("/monthly-summary")
async def get_monthly_summary(year: int = None, month: int = None):
    """Get monthly summary of sales, purchases, and debts"""
    if not year:
        year = date.today().year
    if not month:
        month = date.today().month
    
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)

    logger.info("GET /api/dashboard/monthly-summary | year=%s month=%s", year, month)
    try:
        with pg_cursor() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(total_amount),0), COALESCE(SUM(CASE WHEN payment_status='paid' THEN total_amount ELSE 0 END),0) FROM sales WHERE sale_date >= %s AND sale_date <= %s",
                (start_date, end_date),
            )
            monthly_sales, paid_sales = cur.fetchone()

            cur.execute(
                "SELECT COALESCE(SUM(total_amount),0), COALESCE(SUM(CASE WHEN payment_status='paid' THEN total_amount ELSE 0 END),0) FROM purchases WHERE purchase_date >= %s AND purchase_date <= %s",
                (start_date, end_date),
            )
            monthly_purchases, paid_purchases = cur.fetchone()

            cur.execute(
                "SELECT COALESCE(SUM(amount),0) FROM debts WHERE created_at >= %s AND created_at <= %s",
                (start_date, end_date),
            )
            (monthly_debts,) = cur.fetchone()

        payload = {
            "year": year,
            "month": month,
            "sales": {
                "total": monthly_sales,
                "paid": paid_sales,
                "pending": monthly_sales - paid_sales,
            },
            "purchases": {
                "total": monthly_purchases,
                "paid": paid_purchases,
                "pending": monthly_purchases - paid_purchases,
            },
            "new_debts": monthly_debts,
            "profit": paid_sales - paid_purchases,
        }
        logger.info("Monthly summary computed | year=%s month=%s", year, month)
        return payload
    except Exception as e:
        logger.error("Failed to compute monthly summary: %s", e)
        raise DatabaseError("Failed to compute monthly summary")

