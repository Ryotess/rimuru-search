# src/exceptions.py
from fastapi import Request
from fastapi.responses import JSONResponse


async def db_pool_exhausted_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle database connection pool exhaustion errors."""
    return JSONResponse(
        status_code=503,
        content={
            "error": "service_unavailable",
            "message": "Service temporarily unavailable. Please retry later.",
        },
    )
