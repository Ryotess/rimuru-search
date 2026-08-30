# Troubleshooting

Start with effective settings and prerequisites:

```bash
make config
make doctor
docker compose ps -a
```

Use `make demo-logs` for the complete stack or `docker compose logs <service>` for one service.

## Migration reports missing settings

Current versions have local defaults, so `make migrate-db` does not require model or Source API variables. If it cannot connect to PostgreSQL:

```bash
cp .env.example .env
make host-db
make migrate-db
```

Keep `GLOBAL_DATABASE_URL` aligned with `PGSQL_DB`, `PGSQL_USER`, `PGSQL_PASSWORD`, and `POSTGRES_PORT`. Run `make config` to see the effective native URL with its password redacted.

## PostgreSQL reports an incompatible data directory

The bundled database moved from PostgreSQL 16 to PostgreSQL 18 for
pg_textsearch. PostgreSQL major versions cannot open each other's data
directories directly. The Compose volume key is versioned, so after updating the
repository, run `make demo-up` again. Compose creates a fresh PostgreSQL 18 demo
volume and leaves the previous PostgreSQL 16 volume untouched.

If the old volume contains data you need, start it with the old PostgreSQL 16
image, dump the database, and restore it into the new PostgreSQL 18 volume. Do
not remove the old volume until the restored data has been verified. For a
disposable active demo database, `make demo-reset && make demo-up` recreates the
PostgreSQL 18 volume and reimports the sample documents.

## Readiness reports a missing lexical extension or index

`SEARCH_LEXICAL_BACKEND=bm25` requires PostgreSQL 17/18, pg_textsearch loaded in
`shared_preload_libraries`, the `pg_textsearch` extension, and the migrated BM25
index. The bundled image supplies these pieces. For an external database, install
and preload pg_textsearch before running:

```bash
make migrate-db
curl -s http://localhost:8000/health/ready
```

Use `SEARCH_LEXICAL_BACKEND=fts` only as an explicit operator choice and restart
the API. Rimuru Search does not silently change backend when readiness fails.

## Embedding or reranker connection errors

For native services, verify both model health endpoints:

```bash
curl -f http://localhost:5678/health
curl -f http://localhost:5679/health
uv run scripts/doctor.py --services
```

`/health` only proves that vLLM is alive. The doctor and FastAPI readiness also
query `/v1/models` and verify the configured model name. If readiness reports
`model_not_found`, compare these values:

```bash
curl -s http://localhost:5678/v1/models
make config
```

For bundled Compose, change `EMBEDDING_MODEL_ID` or `RERANKER_MODEL_ID`; the
application request name is derived automatically. Use a `*_REQUEST_MODEL`
override only when an external endpoint deliberately exposes another served
alias.

If vLLM reports that the reranker repository contains custom code, review the
model repository before setting
`RERANKER_REMOTE_CODE_FLAG=--trust-remote-code`. Remote code remains disabled by
default.

If `make config` warns about `EMBED_EMBEDDING_MODEL` or
`RERANKER_RERANKER_MODEL`, update the old local `.env`. Those names are ignored
and should not be used in new configuration.

The first model startup can take several minutes while images and model files download. Inspect `docker compose logs embedding reranker` if health checks never become ready. A temporary reranker failure returns RRF-fused results with `rerank_score: null`; an embedding failure cannot run semantic retrieval and returns HTTP 502.

When FastAPI runs in Docker, `localhost` points back to the API container. Use the `COMPOSE_*` endpoint variables and a container-reachable hostname such as `embedding`, `reranker`, or `host.docker.internal`.

When `SEARCH_ENABLE_RERANK=false`, `make start` does not start the bundled
reranker and `/health/ready` reports it as disabled. If a replacement model is
reachable but produces poor results, verify its runner, pooling or score
conversion, input template, and served name with the
[model compatibility checklist](model-compatibility.md).

## Model container is OOMKilled or never becomes ready

Inspect the container status and logs first:

```bash
docker compose ps -a
docker compose logs embedding reranker
```

Measure the selected checkpoint under the actual vLLM image and hardware; model
size alone does not determine runtime memory. Reduce `EMBEDDING_MAX_NUM_SEQS` or
`EMBEDDING_MAX_MODEL_LEN` when appropriate; reranker equivalents are also
configurable. The first start is slower because model weights must be
downloaded. Preserve the Hugging Face cache volume between ordinary restarts.

## Port is already allocated

Change the host-side port in `.env`, for example:

```dotenv
API_PORT=8080
POSTGRES_PORT=55432
EMBEDDING_PORT=15678
```

Run `docker compose config --quiet` to validate the result. Container-to-container ports do not change.

## Import fails

Validate a mapping without starting an embedding request or changing the database:

```bash
make import-native FILE=./documents.csv ARGS='--dry-run --id-field sku --content-fields title,description'
```

Errors include the input record or JSONL line number. Common causes are a missing stable ID, empty configured content fields, duplicate IDs, a non-object metadata value, and an unsupported filename suffix. Use `--generate-ids` only when the source has no stable identifier.

`upsert` commits completed chunks to the live table. `replace` writes staging
data and leaves the live table unchanged if validation, embedding, or database
insertion fails. A successful `replace` is service-wide and removes every
collection missing from its input file.

## Search returns no matches

Confirm data was explicitly imported: API startup never imports records. Run a
known query through the browser demo and inspect request options in `/docs`.
Both lexical backends use the PostgreSQL `simple` text configuration. Enable
trigram matching per request with `"use_fuzzy": true`, or set
`SEARCH_USE_FUZZY_DEFAULT=true` in `.env`.

BM25 is the default lexical backend and also uses the `simple` text-search
configuration. Set `SEARCH_LEXICAL_BACKEND=fts` and restart only when comparing
or rolling back lexical behavior; this setting is not an API parameter.

Confirm the request uses the same `collection` that was used during import. Use a `metadata_filter` only when the stored metadata contains the supplied JSON object. An empty `document_ids` list intentionally restricts both retrieval branches to no documents.

## Embedding dimension mismatch

The bundled database column requires 1,024-dimensional vectors. Switching only the model name or `VDB_EMBEDDING_DIM` is insufficient. Choose a 1,024-dimensional embedding model, or update the schema and regenerate every embedding before using a model with another dimension.

## Stop or reset services

```bash
make down        # preserve PostgreSQL and model cache volumes
make demo-reset  # remove containers and volumes
```

`make demo-reset` is intentionally destructive and requires downloading models and importing data again.
