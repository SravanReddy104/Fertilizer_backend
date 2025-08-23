from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Optional, Any, Dict
from app.models.models import Product, ProductCreate, ProductUpdate, ProductType
from app.core.database import pg_cursor
from app.core.logging import logger
from app.core.exceptions import NotFoundError, BadRequestError, DatabaseError
from app.core.security import get_current_user, require_admin


def _rows_to_dicts(cur) -> List[Dict[str, Any]]:
    """Convert psycopg2 cursor results to list of dicts."""
    columns = [desc[0] for desc in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]

router = APIRouter(dependencies=[Depends(get_current_user)])

@router.get("/", response_model=List[Product])
async def get_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    product_type: Optional[ProductType] = None,
    search: Optional[str] = None
):
    """Get all products with optional filtering"""
    logger.info(
        "GET /api/products | skip=%s limit=%s type=%s search=%s",
        skip,
        limit,
        product_type.value if product_type else None,
        search,
    )
    sql = "SELECT * FROM products"
    clauses = []
    params: List[Any] = []

    if product_type:
        clauses.append("type = %s")
        params.append(product_type.value)

    if search:
        clauses.append("(name ILIKE %s OR brand ILIKE %s)")
        like = f"%{search}%"
        params.extend([like, like])

    if clauses:
        sql += " WHERE " + " AND ".join(clauses)

    sql += " ORDER BY id ASC LIMIT %s OFFSET %s"
    params.extend([limit, skip])

    try:
        with pg_cursor() as cur:
            cur.execute(sql, params)
            rows = _rows_to_dicts(cur)
            return rows
    except Exception as e:
        logger.error("Failed to fetch products: %s", e)
        raise DatabaseError("Failed to fetch products")

@router.get("/{product_id}", response_model=Product)
async def get_product(product_id: int):
    """Get a specific product by ID"""
    logger.info("GET /api/products/%s", product_id)
    try:
        with pg_cursor() as cur:
            cur.execute("SELECT * FROM products WHERE id = %s", (product_id,))
            rows = _rows_to_dicts(cur)
            if not rows:
                raise NotFoundError("Product not found")
            return rows[0]
    except NotFoundError:
        logger.error("Product %s not found", product_id)
        raise
    except Exception as e:
        logger.error("Failed to fetch product %s: %s", product_id, e)
        raise DatabaseError("Failed to fetch product")

@router.post("/", response_model=Product)
async def create_product(product: ProductCreate, _: int = Depends(require_admin)):
    """Create a new product"""
    logger.info("POST /api/products - creating product")
    data = product.dict()
    if not data:
        raise BadRequestError("No fields provided")

    columns = list(data.keys())
    values = [data[c] for c in columns]
    placeholders = ",".join(["%s"] * len(columns))
    cols_sql = ",".join(columns)

    sql = f"INSERT INTO products ({cols_sql}) VALUES ({placeholders}) RETURNING *"

    try:
        with pg_cursor(commit=True) as cur:
            cur.execute(sql, values)
            rows = _rows_to_dicts(cur)
            if not rows:
                raise BadRequestError("Failed to create product")
            logger.info("Product created id=%s", rows[0].get("id"))
            return rows[0]
    except BadRequestError:
        logger.error("Failed to create product - bad request")
        raise
    except Exception as e:
        logger.error("Failed to create product: %s", e)
        raise DatabaseError("Failed to create product")

@router.put("/{product_id}", response_model=Product)
async def update_product(product_id: int, product: ProductUpdate, _: int = Depends(require_admin)):
    """Update a product"""
    logger.info("PUT /api/products/%s", product_id)
    # Ensure exists
    with pg_cursor() as cur:
        cur.execute("SELECT 1 FROM products WHERE id = %s", (product_id,))
        if cur.fetchone() is None:
            raise NotFoundError("Product not found")

    update_data = {k: v for k, v in product.dict().items() if v is not None}
    if not update_data:
        # Nothing to update; return current row
        with pg_cursor() as cur:
            cur.execute("SELECT * FROM products WHERE id = %s", (product_id,))
            rows = _rows_to_dicts(cur)
            return rows[0]

    set_clauses = ", ".join([f"{k} = %s" for k in update_data.keys()])
    params = list(update_data.values()) + [product_id]
    sql = f"UPDATE products SET {set_clauses} WHERE id = %s RETURNING *"

    try:
        with pg_cursor(commit=True) as cur:
            cur.execute(sql, params)
            rows = _rows_to_dicts(cur)
            if not rows:
                raise BadRequestError("Failed to update product")
            logger.info("Product %s updated", product_id)
            return rows[0]
    except NotFoundError:
        logger.error("Product %s not found for update", product_id)
        raise
    except BadRequestError:
        logger.error("Bad request updating product %s", product_id)
        raise
    except Exception as e:
        logger.error("Failed to update product %s: %s", product_id, e)
        raise DatabaseError("Failed to update product")

@router.delete("/{product_id}")
async def delete_product(product_id: int, _: int = Depends(require_admin)):
    """Delete a product"""
    logger.info("DELETE /api/products/%s", product_id)
    try:
        with pg_cursor(commit=True) as cur:
            cur.execute("DELETE FROM products WHERE id = %s RETURNING id", (product_id,))
            deleted = cur.fetchone()
            if not deleted:
                raise NotFoundError("Product not found")
        logger.info("Product %s deleted", product_id)
        return {"message": "Product deleted successfully"}
    except NotFoundError:
        logger.error("Product %s not found for deletion", product_id)
        raise
    except Exception as e:
        logger.error("Failed to delete product %s: %s", product_id, e)
        raise DatabaseError("Failed to delete product")

@router.get("/low-stock/", response_model=List[Product])
async def get_low_stock_products():
    """Get products with low stock"""
    logger.info("GET /api/products/low-stock")
    try:
        with pg_cursor() as cur:
            cur.execute("SELECT * FROM products WHERE stock_quantity < minimum_stock")
            return _rows_to_dicts(cur)
    except Exception as e:
        logger.error("Failed to fetch low stock products: %s", e)
        raise DatabaseError("Failed to fetch low stock products")

@router.post("/{product_id}/update-stock")
async def update_stock(product_id: int, quantity: float, operation: str = "add", _: int = Depends(require_admin)):
    """Update product stock (add or subtract)"""
    logger.info("POST /api/products/%s/update-stock | qty=%s op=%s", product_id, quantity, operation)
    try:
        with pg_cursor(commit=True) as cur:
            # Get current stock
            cur.execute("SELECT stock_quantity FROM products WHERE id = %s", (product_id,))
            row = cur.fetchone()
            if not row:
                raise NotFoundError("Product not found")
            (current_stock,) = row

            if operation == "add":
                new_stock = current_stock + quantity
            elif operation == "subtract":
                new_stock = max(0, current_stock - quantity)
            else:
                raise BadRequestError("Operation must be 'add' or 'subtract'")

            cur.execute(
                "UPDATE products SET stock_quantity = %s WHERE id = %s RETURNING stock_quantity",
                (new_stock, product_id),
            )
            updated = cur.fetchone()
            if not updated:
                raise BadRequestError("Failed to update stock")

        logger.info("Stock updated for product %s -> %s", product_id, new_stock)
        return {"message": f"Stock updated successfully. New stock: {new_stock}"}
    except NotFoundError:
        logger.error("Product %s not found for stock update", product_id)
        raise
    except BadRequestError as e:
        logger.error("Bad request updating stock for product %s: %s", product_id, e)
        raise
    except Exception as e:
        logger.error("Failed to update stock for product %s: %s", product_id, e)
        raise DatabaseError("Failed to update stock")

