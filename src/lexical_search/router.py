from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.lexical_search.exceptions import LexicalSearchException
from src.lexical_search.schemas import FTSQuery, LexicalHit
from src.lexical_search.service import lexical_search_by_content

router = APIRouter(prefix="/v1/lexical-search", tags=["lexical_search"])


@router.post("/fts", response_model=list[LexicalHit])
async def search_by_fts(
    payload: FTSQuery, session: AsyncSession = Depends(get_session)
) -> list[LexicalHit]:
    """
    Full-text lexical search against document content.
    """
    try:
        hits = await lexical_search_by_content(
            session,
            payload.query,
            payload.top_k,
            document_ids=payload.document_ids,
            metadata_filter=payload.metadata_filter,
            min_similarity=payload.min_similarity,
            use_fuzzy=payload.use_fuzzy,
            collection=payload.collection,
        )
        logger.bind(hits=len(hits)).info("Lexical search completed")
        return [LexicalHit.model_validate(hit) for hit in hits]
    except LexicalSearchException as exc:
        logger.error("Lexical search failed: {}", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Unexpected lexical search error: {}", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Lexical search failed") from exc
