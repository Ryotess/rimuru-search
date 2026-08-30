# src/orchestrator/router.py
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.embedding.exceptions import EmbeddingException
from src.orchestrator.exceptions import EmbeddingParseException, OrchestratorException
from src.orchestrator.schemas import (
    SearchDetailResponse,
    SearchIdsResponse,
    SearchRequest,
    SearchResponse,
)
from src.orchestrator.service import (
    orchestrate_search,
    orchestrate_search_ids,
    orchestrate_search_with_details,
)

router = APIRouter(prefix="/v1/search", tags=["search"])

DEMO_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent.parent / "templates" / "index.html"
)
DEMO_HTML: str | None = None


@router.post("", response_model=SearchResponse)
async def search(
    payload: SearchRequest, session: AsyncSession = Depends(get_session)
) -> SearchResponse:
    try:
        return await orchestrate_search(payload, session)
    except EmbeddingException as exc:
        logger.error("Embedding failed: {}", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except EmbeddingParseException as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except OrchestratorException as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Search pipeline failed unexpectedly: {}", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Search failed") from exc


@router.post("/ids", response_model=SearchIdsResponse)
async def search_ids(
    payload: SearchRequest, session: AsyncSession = Depends(get_session)
) -> SearchIdsResponse:
    """Return only document IDs for compact backwards-compatible clients."""
    try:
        return await orchestrate_search_ids(payload, session)
    except EmbeddingException as exc:
        logger.error("Embedding failed: {}", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except EmbeddingParseException as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except OrchestratorException as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Search pipeline failed unexpectedly: {}", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Search failed") from exc


@router.post("/details", response_model=SearchDetailResponse, deprecated=True)
async def search_with_details(
    payload: SearchRequest, session: AsyncSession = Depends(get_session)
) -> SearchDetailResponse:
    """Return reranked documents with content, metadata, and scores."""
    try:
        return await orchestrate_search_with_details(payload, session)
    except EmbeddingException as exc:
        logger.error("Embedding failed: {}", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except EmbeddingParseException as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except OrchestratorException as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Search pipeline failed unexpectedly: {}", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Search failed") from exc


@router.get("/demo", response_class=HTMLResponse, include_in_schema=False)
async def search_demo() -> HTMLResponse:
    """Serve the bundled hybrid-search demo UI."""
    global DEMO_HTML
    if DEMO_HTML is None:
        if not DEMO_TEMPLATE_PATH.exists():
            raise HTTPException(status_code=404, detail="Demo UI not found")
        DEMO_HTML = DEMO_TEMPLATE_PATH.read_text(encoding="utf-8")
    return HTMLResponse(content=DEMO_HTML)
