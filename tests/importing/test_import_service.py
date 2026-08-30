from unittest.mock import AsyncMock, patch

import pytest

from src.importing.reader import ImportDataError, ImportMapping
from src.importing.service import import_file


@pytest.mark.asyncio
async def test_dry_run_validates_without_database_or_embedding(tmp_path):
    path = tmp_path / "documents.jsonl"
    path.write_text('{"id":"1","content":"First"}\n{"id":"2","content":"Second"}\n')

    summary = await import_file(
        path,
        mapping=ImportMapping(),
        chunk_size=1,
        dry_run=True,
    )

    assert summary.rows == 2
    assert summary.chunks == 2
    assert summary.dry_run is True


@pytest.mark.asyncio
async def test_duplicate_ids_fail_before_second_chunk_is_written(tmp_path):
    path = tmp_path / "documents.jsonl"
    path.write_text(
        '{"id":"same","content":"First"}\n{"id":"same","content":"Second"}\n'
    )

    with pytest.raises(ImportDataError, match="Duplicate document ID"):
        await import_file(path, mapping=ImportMapping(), dry_run=True)


@pytest.mark.asyncio
async def test_same_id_is_allowed_in_different_collections(tmp_path):
    path = tmp_path / "documents.jsonl"
    path.write_text(
        '{"collection":"articles","id":"same","content":"First"}\n'
        '{"collection":"support","id":"same","content":"Second"}\n'
    )

    summary = await import_file(path, mapping=ImportMapping(), dry_run=True)

    assert summary.rows == 2


@pytest.mark.asyncio
async def test_upsert_processes_chunks_and_invalidates_cache(tmp_path):
    path = tmp_path / "documents.json"
    path.write_text('[{"id":"1","content":"First"}]')

    context = AsyncMock()
    context.__aenter__.return_value = "client"
    context.__aexit__.return_value = False
    with (
        patch("src.importing.service.short_keepalive_client", return_value=context),
        patch(
            "src.importing.service.process_chunk",
            new=AsyncMock(return_value=1),
        ) as process,
        patch(
            "src.importing.service.invalidate_search_cache",
            new=AsyncMock(return_value=1),
        ) as invalidate,
    ):
        summary = await import_file(path, mapping=ImportMapping())

    assert summary.rows == 1
    process.assert_awaited_once()
    invalidate.assert_awaited_once()


@pytest.mark.asyncio
async def test_replace_swaps_only_after_successful_import(tmp_path):
    path = tmp_path / "documents.csv"
    path.write_text("id,content\n1,First\n")

    context = AsyncMock()
    context.__aenter__.return_value = "client"
    context.__aexit__.return_value = False
    with (
        patch("src.importing.service.short_keepalive_client", return_value=context),
        patch("src.importing.service.ensure_extensions", new=AsyncMock()),
        patch("src.importing.service.recreate_staging", new=AsyncMock()),
        patch("src.importing.service.process_chunk", new=AsyncMock(return_value=1)),
        patch("src.importing.service.swap_tables", new=AsyncMock()) as swap,
        patch("src.importing.service.rebuild_indexes", new=AsyncMock()) as rebuild,
        patch("src.importing.service.invalidate_search_cache", new=AsyncMock()),
    ):
        await import_file(path, mapping=ImportMapping(), mode="replace")

    swap.assert_awaited_once()
    rebuild.assert_awaited_once()
