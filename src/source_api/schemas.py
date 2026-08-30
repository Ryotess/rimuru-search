from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.config import app_settings


class DocumentItem(BaseModel):
    collection: str = Field(
        default=app_settings.document_default_collection, min_length=1
    )
    id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PaginationMeta(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    page: int
    take: int
    item_count: int = Field(alias="itemCount")
    page_count: int = Field(alias="pageCount")
    has_previous_page: bool = Field(alias="hasPreviousPage")
    has_next_page: bool = Field(alias="hasNextPage")


class DocumentListResponse(BaseModel):
    list: list[DocumentItem]
    meta: PaginationMeta
