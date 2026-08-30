# src/embedding/router.py
from fastapi import APIRouter, HTTPException
from loguru import logger

from src.embedding.exceptions import EmbeddingException
from src.embedding.schemas import EmbeddingRequest, EmbeddingResponse
from src.embedding.service import encode_query

router = APIRouter(prefix="/v1/embeddings", tags=["embedding"])


@router.post("", response_model=EmbeddingResponse)
async def create_embedding(payload: EmbeddingRequest) -> EmbeddingResponse:
    """
    Generate an embedding for the provided text.
    """
    logger.bind(length=len(payload.text)).debug("Embedding request received")
    try:
        response = await encode_query(payload.text)
        logger.debug("Embedding request succeeded")
        return response
    except EmbeddingException as exc:
        logger.error("Embedding failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # Guard against unexpected issues
        logger.error(f"Unexpected embedding error: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to generate embedding"
        ) from exc
