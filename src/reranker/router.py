# src/reranker/router.py
from fastapi import APIRouter, HTTPException
from loguru import logger

from src.reranker.exceptions import RerankerException
from src.reranker.schemas import RerankRequest, RerankResponse
from src.reranker.service.rerank_docs import aget_rerank_result

router = APIRouter(prefix="/v1/rerank", tags=["reranker"])


@router.post("", response_model=RerankResponse)
async def rerank(payload: RerankRequest) -> RerankResponse:
    """
    Rerank provided documents in order of relevance to the query.
    """
    try:
        return await aget_rerank_result(
            query=payload.query,
            docs=payload.documents,
            top_n=payload.top_n,
            instruction=payload.instruction,
        )
    except RerankerException as exc:
        logger.error("Reranking failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # Guard against unexpected issues
        logger.error(f"Unexpected reranking error: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to rerank documents"
        ) from exc
