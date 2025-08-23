from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import products, sales, purchases, debts, dashboard, auth, admin
from app.core.config import settings
from app.core.logging import logger
from app.core.exceptions import register_exception_handlers

app = FastAPI(
    title="Fertilizer Shop Dashboard API",
    description="API for managing fertilizer shop operations",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register exception handlers
register_exception_handlers(app)

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(products.router, prefix="/api/products", tags=["products"])
app.include_router(sales.router, prefix="/api/sales", tags=["sales"])
app.include_router(purchases.router, prefix="/api/purchases", tags=["purchases"])
app.include_router(debts.router, prefix="/api/debts", tags=["debts"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])

@app.get("/")
async def root():
    logger.info("Root endpoint hit")
    return {"message": "Fertilizer Shop Dashboard API"}

@app.get("/health")
async def health_check():
    logger.info("Health check requested")
    return {"status": "healthy"}
