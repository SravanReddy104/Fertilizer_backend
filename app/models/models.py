from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from enum import Enum

class ProductType(str, Enum):
    FERTILIZER = "fertilizer"
    PESTICIDE = "pesticide"
    SEED = "seed"

class TransactionType(str, Enum):
    SALE = "sale"
    PURCHASE = "purchase"

class PaymentStatus(str, Enum):
    PAID = "paid"
    PENDING = "pending"
    PARTIAL = "partial"
    OVERDUE = "overdue"

# Base Models
class ProductBase(BaseModel):
    name: str
    type: ProductType
    brand: str
    unit: str  # kg, liter, packet, etc.
    price_per_unit: float
    stock_quantity: float
    minimum_stock: float
    description: Optional[str] = None

class Product(ProductBase):
    id: int
    created_at: datetime
    updated_at: datetime

class ProductCreate(ProductBase):
    pass

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[ProductType] = None
    brand: Optional[str] = None
    unit: Optional[str] = None
    price_per_unit: Optional[float] = None
    stock_quantity: Optional[float] = None
    minimum_stock: Optional[float] = None
    description: Optional[str] = None

# Sale Models
class SaleItemBase(BaseModel):
    product_id: int
    quantity: float
    unit_price: float
    total_price: float

class SaleItem(SaleItemBase):
    id: int
    sale_id: int

class SaleBase(BaseModel):
    customer_name: str
    customer_phone: Optional[str] = None
    customer_address: Optional[str] = None
    total_amount: float
    paid_amount: float
    payment_status: PaymentStatus
    notes: Optional[str] = None

class Sale(SaleBase):
    id: int
    sale_date: datetime
    items: list[SaleItem] = []
    created_at: datetime
    updated_at: datetime

class SaleCreate(BaseModel):
    customer_name: str
    customer_phone: Optional[str] = None
    customer_address: Optional[str] = None
    notes: Optional[str] = None
    items: list[SaleItemBase]

# Purchase Models
class PurchaseItemBase(BaseModel):
    product_id: int
    quantity: float
    unit_price: float
    total_price: float

class PurchaseItem(PurchaseItemBase):
    id: int
    purchase_id: int

class PurchaseBase(BaseModel):
    supplier_name: str
    supplier_phone: Optional[str] = None
    supplier_address: Optional[str] = None
    total_amount: float
    paid_amount: float
    payment_status: PaymentStatus
    notes: Optional[str] = None

class Purchase(PurchaseBase):
    id: int
    purchase_date: datetime
    items: list[PurchaseItem] = []
    created_at: datetime
    updated_at: datetime

class PurchaseCreate(BaseModel):
    supplier_name: str
    supplier_phone: Optional[str] = None
    supplier_address: Optional[str] = None
    notes: Optional[str] = None
    items: list[PurchaseItemBase]

# Debt Models
class DebtBase(BaseModel):
    customer_name: str
    customer_phone: Optional[str] = None
    amount: float
    description: str
    due_date: Optional[datetime] = None
    status: PaymentStatus

class Debt(DebtBase):
    id: int
    created_at: datetime
    updated_at: datetime

class DebtCreate(DebtBase):
    pass

class DebtUpdate(BaseModel):
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    amount: Optional[float] = None
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    status: Optional[PaymentStatus] = None

# Dashboard Models
class DashboardStats(BaseModel):
    total_sales: float
    total_purchases: float
    total_debts: float
    total_products: int
    low_stock_products: int
    recent_sales: list[Sale]
    recent_purchases: list[Purchase]
    pending_debts: list[Debt]
