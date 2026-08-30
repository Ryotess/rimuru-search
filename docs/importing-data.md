# Importing data

The quickest path from an existing file to a search API is `make start FILE=...`. It accepts JSON, newline-delimited JSON (`.jsonl` or `.ndjson`), and CSV, calculates embeddings through the configured embedding API, and writes the domain-neutral document contract to PostgreSQL.

## Standard document shape

JSONL example:

```jsonl
{"id":"guide-1","content":"Configure a hybrid search service","metadata":{"type":"guide","language":"en"}}
{"id":"guide-2","content":"Monitor database readiness","metadata":{"type":"guide","language":"en"}}
```

JSON may be a single object, an array, `{"documents": [...]}`, or `{"data": [...]}`. CSV must have a header row. A CSV `metadata` cell may contain a serialized JSON object.

The stored contract has four fields:

| Field | Required | Import and search behavior |
| --- | --- | --- |
| `collection` | no | Advanced namespace for multiple corpora in one service; single-dataset imports normally omit it and use `DOCUMENT_DEFAULT_COLLECTION` |
| `id` | yes | Stable identifier unique within the collection; identity is `(collection, id)` |
| `content` | yes | Searchable text used for lexical retrieval, embeddings, and reranking |
| `metadata` | no | Returned JSON attributes usable with exact containment filters; not part of searchable content |

One uploaded dataset does not need an explicit collection. Imports and searches
that omit it use `default`, or the value configured by
`DOCUMENT_DEFAULT_COLLECTION`. Use named collections only when one service hosts
multiple corpora that must be searched independently, such as separate catalogs
and help centers. Use metadata for attributes such as category, language, status,
or source. Collection scoping does not replace authentication or authorization.

```bash
make start FILE=./documents.jsonl
```

The filename is mounted read-only into a one-shot Compose container. It is not copied into the application image.

`make start` launches PostgreSQL, Redis, the two bundled model services, migrations, and FastAPI before importing the file. It does not run the sample Source API or sample seed. Once services are running, use `make import FILE=...` for later updates.

## Map an existing schema

Suppose a CSV has `sku,title,description,category,language`. Put this in `.env`:

```dotenv
IMPORT_ID_FIELD=sku
IMPORT_CONTENT_FIELDS=title,description
IMPORT_METADATA_FIELDS=category,language
DOCUMENT_DEFAULT_COLLECTION=products
```

`title` and `description` are joined into the text used by lexical retrieval, embeddings, and reranking. Dot paths such as `attributes.title` work for JSON objects. When `IMPORT_METADATA_FIELDS` is empty, every unused top-level field is retained as metadata automatically.

Every document belongs to a collection namespace. `DOCUMENT_DEFAULT_COLLECTION` is used when a record omits it. If one file contains multiple collections, set `IMPORT_COLLECTION_FIELD=dataset` (or pass `--collection-field dataset`). IDs only need to be unique within their collection.

If a source has no stable ID, set `IMPORT_GENERATE_IDS=true`. The importer creates deterministic IDs from each full source record. Explicit source IDs are preferred because they allow a later import to update the same logical record when its content changes.

Every `.env` default can be overridden for one run:

```bash
make import FILE=./products.csv \
  ARGS='--id-field sku --content-fields title,description --metadata-fields category --dry-run'
```

Run `docker compose run --rm importer --help` for all options.

## Upsert versus replace

| Mode | Behavior | Missing IDs | Failure behavior |
| --- | --- | --- | --- |
| `upsert` | Inserts new IDs and updates existing IDs in the live table | Preserved | Completed chunks remain committed; rerun the same file safely |
| `replace` | Embeds the full file in a fresh staging table, then atomically swaps it live | Removed across every collection | Live data is unchanged unless all input rows finish |

Use the default `upsert` for incremental imports:

```bash
make import FILE=./updates.jsonl
```

Use `replace` when the file is the authoritative complete snapshot:

```bash
make import FILE=./snapshot.jsonl ARGS='--mode replace'
```

`replace` is service-wide, not collection-scoped: its staging table becomes the
entire live `documents` table, so collections absent from the file are removed
at the swap. Use `upsert` when updating one collection while preserving others.
An empty file never replaces live data. Duplicate IDs and invalid records fail
with their record or line number. Successful imports invalidate cached searches.

## Native execution

When PostgreSQL and the embedding service are reachable through the normal `.env` URLs:

```bash
make migrate-db
make import-native FILE=./documents.jsonl
```

## Paginated Source API

Use the Source API task flow when data comes from a database or remote system and needs resumable, page-based synchronization. It uses the same `id`, `content`, and `metadata` contract.

- `SEED` upserts into the live table and preserves IDs no longer present upstream.
- `RESEED` builds a service-wide upstream snapshot in staging and atomically replaces the live table, including all collections.

Configure `SOURCE_API_BASE_URL` and `SOURCE_API_DOCUMENTS_PATH` for native commands, or `COMPOSE_SOURCE_API_BASE_URL` for a source called from the API container. FastAPI startup never imports data automatically.
