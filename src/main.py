# src/main.py
# FastAPI packages
import gc
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from litellm.llms.custom_httpx.async_client_cleanup import close_litellm_async_clients
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from src.cache.client import close_redis
from src.config import app_settings
from src.database import dispose_engines
from src.exceptions import db_pool_exhausted_handler
from src.health.router import router as health_router
from src.logging_config import logger, shutdown_logging

# from src.embedding.router import router as embed_router
# from src.lexical_search.router import router as lexical_router
# from src.vector_search.router import router as vector_router
# from src.reranker.router import router as reranker_router
from src.orchestrator.router import router as orchestrator_router
from src.seeding.router import router as seeding_router

logger.info("Starting Rimuru Search...")


# ---------------- Lifespan ---------------- #
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("App is starting up...")
    from src.seeding.service.task_manager import seed_task_manager

    yield
    logger.info("App is shutting down...")
    await seed_task_manager.cancel_running()

    await dispose_engines()

    await close_redis()
    await close_litellm_async_clients()
    shutdown_logging()
    gc.collect()


# ---------------- App Setup ---------------- #
app = FastAPI(
    title="Rimuru Search API",
    description=(
        "Hybrid BM25 and semantic document retrieval with Reciprocal Rank Fusion "
        "and optional cross-encoder reranking."
    ),
    version="0.1.0",
    lifespan=lifespan,  # <- use lifespan here
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.cors_allowed_origins_list,
    allow_credentials=app_settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- Exception Handlers ---------------- #
app.add_exception_handler(SQLAlchemyTimeoutError, db_pool_exhausted_handler)

# ---------------- Routers ---------------- #
app.include_router(orchestrator_router)
app.include_router(health_router)
app.include_router(seeding_router)
# app.include_router(embed_router)
# app.include_router(lexical_router)
# app.include_router(vector_router)
# app.include_router(reranker_router)


# ---------------- Endpoints ---------------- #
@app.get("/")
async def read_root():
    return {
        "name": "Rimuru Search API",
        "docs": "/docs",
        "demo": "/v1/search/demo",
        "readiness": "/health/ready",
    }


# ---------------- Run ---------------- #
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104  # Container entry point intentionally listens on all interfaces.
