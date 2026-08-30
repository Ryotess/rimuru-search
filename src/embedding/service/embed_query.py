# src/embedding/service/embed_query.py
from litellm import EmbeddingResponse, aembedding
from loguru import logger

from src.embedding.config import embedding_settings
from src.embedding.exceptions import EmbeddingException

# import litellm

# litellm._turn_on_debug()


async def encode_query(query: str) -> EmbeddingResponse:
    """
    Encode input query into embeddings using vllm hosted model
    Args:
        query(str): The query string to be encoded
    Returns:
        EmbeddingResponse: The response from vllm embedding endpoint
    """
    try:
        logger.bind(
            model=embedding_settings.embedding_model,
            query_length=len(query),
        ).debug("Requesting embedding")
        embedding: EmbeddingResponse = await aembedding(
            model=embedding_settings.embedding_model,
            input=[query],
            api_base=embedding_settings.hosted_vllm_api_base,
        )
        return embedding
    except Exception as e:
        logger.error(
            "Failed to encode query; upstream error type={}",
            type(e).__name__,
            exc_info=True,
        )
        raise EmbeddingException("Failed to encode query") from e
