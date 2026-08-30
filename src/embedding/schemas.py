# src/embedding/schema.py
from litellm import EmbeddingResponse as LiteLLMEmbeddingResponse
from pydantic import BaseModel, Field

# Re-use LiteLLM's embedding response schema to mirror the provider output.
EmbeddingResponse = LiteLLMEmbeddingResponse


class EmbeddingRequest(BaseModel):
    """Payload for requesting a single text embedding."""

    text: str = Field(..., description="The text to embed into a dense vector.")
