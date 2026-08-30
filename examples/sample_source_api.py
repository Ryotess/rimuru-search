"""Minimal paginated document API backed by the bundled sample JSON file."""

import json
import math
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query

DATA_PATH = Path(__file__).parent / "data" / "documents.json"
DOCUMENTS: list[dict[str, Any]] = json.loads(DATA_PATH.read_text(encoding="utf-8"))

app = FastAPI(
    title="Rimuru Search Sample Source API",
    description="Serves generated documents using the ingestion contract.",
    version="0.1.0",
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/v1/documents")
async def list_documents(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=2000, ge=1, le=5000),
) -> dict[str, Any]:
    """Return one page using the source API envelope expected by the seeder."""
    item_count = len(DOCUMENTS)
    page_count = max(1, math.ceil(item_count / limit))
    start = (page - 1) * limit
    items = DOCUMENTS[start : start + limit]

    return {
        "data": {
            "list": items,
            "meta": {
                "page": page,
                "take": len(items),
                "itemCount": item_count,
                "pageCount": page_count,
                "hasPreviousPage": page > 1,
                "hasNextPage": page < page_count,
            },
        }
    }
