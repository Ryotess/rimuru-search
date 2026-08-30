# src/reranker/schemas.py

from litellm import RerankResponse as LiteLLMRerankResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from src.reranker.config import reranker_settings

# Re-use LiteLLM's response model for transparency.
RerankResponse = LiteLLMRerankResponse


class RerankRequest(BaseModel):
    """Payload for reranking a list of documents against a query."""

    query: str = Field(..., min_length=1, description="The query to rank against.")
    documents: list[str] = Field(
        ..., min_length=1, description="Documents to rerank in relevance order."
    )
    top_n: int | None = Field(
        None, ge=1, description="Number of documents to return (defaults to settings)."
    )
    instruction: str | None = Field(
        None,
        description="Optional instruction to override the default prompt instruction.",
    )

    @field_validator("documents")
    @classmethod
    def validate_documents(cls, documents: list[str]) -> list[str]:
        if not documents:
            raise ValueError("At least one document is required.")
        max_length = reranker_settings.max_document_length
        for doc in documents:
            if not doc or not doc.strip():
                raise ValueError("Documents cannot be empty.")
            if len(doc) > max_length:
                raise ValueError(
                    f"Document exceeds max length of {max_length} characters."
                )
        return documents

    @model_validator(mode="after")
    def validate_top_n(self):
        effective_top_n = self.top_n or reranker_settings.top_n
        if effective_top_n > len(self.documents):
            raise ValueError("top_n cannot exceed number of documents provided.")
        self.top_n = effective_top_n
        return self
