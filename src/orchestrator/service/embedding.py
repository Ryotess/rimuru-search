# src/orchestrator/service/embedding.py
import time

from loguru import logger

from src.embedding.exceptions import EmbeddingException
from src.embedding.service import encode_query
from src.orchestrator.exceptions import EmbeddingParseException, OrchestratorException
from src.orchestrator.utils import extract_embedding_vector


async def generate_query_vector(query: str) -> list[float]:
    """
    Encode a query string into an embedding vector.
    """
    logger.bind(length=len(query)).debug("Embedding stage started")
    try:
        t0 = time.perf_counter()
        embedding_response = await encode_query(query)
        query_vector = extract_embedding_vector(embedding_response)
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        logger.bind(
            model=getattr(embedding_response, "model", None),
            vector_dim=len(query_vector),
            elapsed_ms=elapsed_ms,
        ).info("Embedding generated")
        return query_vector
    except (EmbeddingException, EmbeddingParseException):
        # Let embedding-specific errors bubble up to FastAPI handlers
        raise
    except Exception as exc:
        logger.error("Embedding stage failed: {}", exc, exc_info=True)
        raise OrchestratorException("Failed to generate embedding") from exc
