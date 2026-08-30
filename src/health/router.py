# src/health/router.py
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.health.service import get_db_health, get_readiness

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


@router.get("/db")
async def db_health():
    """Database connectivity and connection-pool health check."""
    return await get_db_health()


@router.get("/ready")
async def readiness_check():
    """Search-path readiness check for the database and model services."""
    result = await get_readiness()
    status_code = 200 if result["status"] == "ready" else 503
    return JSONResponse(content=result, status_code=status_code)
