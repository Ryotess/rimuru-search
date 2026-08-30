# src/vector_search/router.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.vector_search.schemas import ANNQueryByVector, DocumentHit
from src.vector_search.service import ann_search_by_vector

router = APIRouter(prefix="/v1/vector-search", tags=["vector_search"])


@router.post("/ann", response_model=list[DocumentHit])
async def search_by_vector(
    payload: ANNQueryByVector, session: AsyncSession = Depends(get_session)
):
    return await ann_search_by_vector(
        session,
        payload.vector,
        payload.top_k,
        document_ids=payload.document_ids,
        metadata_filter=payload.metadata_filter,
        collection=payload.collection,
    )
