# src/orchestrator/service/fusion.py
from typing import Any

from loguru import logger

from src.orchestrator.schemas import RRFHit
from src.orchestrator.utils import fuse_hits_with_rrf


def fuse_search_hits(
    vector_hits: list[dict[str, Any]],
    lexical_hits: list[dict[str, Any]],
    top_k: int,
) -> list[RRFHit]:
    """
    Fuse vector and lexical hits and truncate to the requested top_k.
    """
    hybrid_hits = fuse_hits_with_rrf(vector_hits, lexical_hits)
    top_hybrid_hits = hybrid_hits[:top_k]
    logger.bind(
        hybrid_candidates=len(hybrid_hits), returning=len(top_hybrid_hits)
    ).info("Hybrid RRF fusion complete")
    return top_hybrid_hits
