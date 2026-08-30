# Configuration

All runtime settings are optional and can be provided as environment variables or in the repository-root `.env` file. Pydantic reads the normal variables for native Python processes. Docker Compose also reads `.env`, passes behavior settings into containers, and constructs its internal database URL from `PGSQL_*`.

Restart the affected native process, or rerun `docker compose up`, after changing `.env`; settings are loaded when each process starts.

Start from the documented defaults:

```bash
cp .env.example .env
make config
make doctor
```

`make config` prints the effective native settings and redacts database passwords. `make doctor` additionally validates Docker, Compose configuration, and the database embedding-dimension invariant. Use `uv run scripts/doctor.py --services` to probe services that are already running.

## Native and Compose endpoints

`localhost` means different things on the host and inside a container. The setting pairs make that distinction explicit:

| Purpose | Native process | API/import container |
| --- | --- | --- |
| PostgreSQL | `GLOBAL_DATABASE_URL` | Constructed from `PGSQL_DB`, `PGSQL_USER`, `PGSQL_PASSWORD` and service `postgres` |
| Embedding | `EMBED_HOSTED_VLLM_API_BASE` | `COMPOSE_EMBED_API_BASE`, default `http://embedding:8000/v1` |
| Reranker | `RERANKER_HOSTED_VLLM_API_BASE` | `COMPOSE_RERANKER_API_BASE`, default `http://reranker:8000/v1` |
| Source API | `SOURCE_API_BASE_URL` | `COMPOSE_SOURCE_API_BASE_URL`, default `http://sample-source:3000` |
| Redis | `CACHE_REDIS_URL` | `COMPOSE_CACHE_REDIS_URL`, default `redis://redis:6379/0` |

For the bundled model servers, `EMBEDDING_MODEL_ID` and `RERANKER_MODEL_ID` are
the canonical values: Compose loads those IDs, exposes the same served names,
and the application derives `hosted_vllm/<model-id>` request names. This avoids
configuring one model in the API while the container loads another.

`RERANKER_REMOTE_CODE_FLAG` defaults to `--no-trust-remote-code`. Set it to
`--trust-remote-code` only when the selected reranker requires custom Hugging
Face code and you have reviewed and trust that model repository.

For a model API running on the Docker host, use a container-reachable URL such as:

```dotenv
COMPOSE_EMBED_API_BASE=http://host.docker.internal:9001/v1
COMPOSE_EMBED_REQUEST_MODEL=hosted_vllm/embedding-served-alias
COMPOSE_RERANKER_API_BASE=http://host.docker.internal:9002/v1
COMPOSE_RERANKER_REQUEST_MODEL=hosted_vllm/reranker-served-alias
```

The request-model overrides are only necessary when `/v1/models` exposes a name
different from `*_MODEL_ID`. For native execution, the equivalent advanced
overrides are `EMBEDDING_REQUEST_MODEL` and `RERANKER_REQUEST_MODEL`.
The former `EMBED_EMBEDDING_MODEL` and `RERANKER_RERANKER_MODEL` names are no
longer runtime settings. `make config` detects them in an existing local `.env`
and reports a migration warning without printing their values. Remove them when
the model server exposes the same ID, or rename them to the corresponding
`*_REQUEST_MODEL` variable when an alias is required.

`make start` and `make up` select services from the effective Compose
environment. They omit the bundled model server when its `COMPOSE_*_API_BASE`
points outside the matching Compose hostname. They also omit Redis when
`COMPOSE_CACHE_REDIS_URL=` and omit the reranker when
`SEARCH_ENABLE_RERANK=false`. `make demo-up` intentionally starts the complete
demo stack.

Readiness validates each configured model against the endpoint's `/v1/models`
response. A served-name mismatch therefore returns `not_ready` instead of first
appearing as a failed search request. It also validates the extension and index
required by the configured lexical backend plus the optional fuzzy-search index.

## Model runtime compatibility

Changing a Hugging Face model ID is sufficient only when the replacement uses
the same API, dimension, runner, input format, pooling, and score conversion
contract. Model-specific runtime configuration belongs in a separate Compose
override or deployment configuration, not in the core application.

`EMBEDDING_MAX_MODEL_LEN`, `EMBEDDING_MAX_NUM_SEQS`,
`RERANKER_MAX_MODEL_LEN`, and `RERANKER_MAX_NUM_SEQS` control the bundled CPU
servers. Longer sequences and higher concurrency consume more memory.

See [Model compatibility](model-compatibility.md) for the complete checklist,
data-regeneration rules, validation workflow, and a worked example.

## Search behavior

These values become defaults in the generated OpenAPI request schema. A client may override them in each request.

Database-side vector search also uses these operator settings:

| Variable | Default | Purpose |
| --- | ---: | --- |
| `GLOBAL_HNSW_EF_SEARCH` | `200` | HNSW search breadth; higher values can improve recall with more database work |
| `GLOBAL_HNSW_ITERATIVE_SCAN` | `strict_order` | Continue scanning after collection/ID/metadata filters remove candidates; valid values are `off`, `strict_order`, and `relaxed_order` |

| Variable | Default | Purpose |
| --- | ---: | --- |
| `SEARCH_LEXICAL_BACKEND` | `bm25` | Operator-selected lexical backend: `bm25` or `fts`; restart after changing it |
| `SEARCH_VECTOR_TOP_K_DEFAULT` | `100` | Vector candidates before fusion |
| `SEARCH_LEXICAL_TOP_K_DEFAULT` | `100` | Lexical candidates before fusion |
| `SEARCH_RRF_TOP_K_DEFAULT` | `15` | Fused candidates retained |
| `SEARCH_RERANK_TOP_N_DEFAULT` | `3` | Final results returned by the reranker or fallback |
| `SEARCH_ENABLE_RERANK` | `true` | Use the reranker; when false, return RRF order with a null rerank score |
| `SEARCH_USE_FUZZY_DEFAULT` | `false` | Enable trigram matching by default |
| `SEARCH_MIN_SIMILARITY_DEFAULT` | `0.2` | Trigram floor when fuzzy matching is enabled |

`SEARCH_LEXICAL_BACKEND` is intentionally not exposed as an API request field.
Both the BM25 and FTS indexes are created by migrations so an operator can make
an explicit rollback to `fts`. The application does not silently fall back when
the configured backend is unhealthy; `/health/ready` returns `not_ready`
instead. BM25 and FTS use the `simple` text-search configuration. Changing the
index-time text configuration requires a schema migration and index rebuild.

If the optional reranker is unavailable, the API returns fused results instead of returning an empty result set.

Vector and lexical top-k values control database work.
`SEARCH_RRF_TOP_K_DEFAULT` controls the fused candidate set sent to the
cross-encoder and therefore has the largest direct effect on reranking cost.
`SEARCH_RERANK_TOP_N_DEFAULT` controls how many of those scored candidates are
returned. For CPU-only evaluation, start with `10`, `10`, `3`, and `3`, then
measure recall and MRR on a labeled dataset before increasing them. Disabling
reranking can be appropriate when embedding retrieval already meets the
collection's quality target; it should remain an evaluated choice rather than a
universal default. See [Search tuning](search-tuning.md) for request-level tuning
recipes and score interpretation.

## Import and seeding

| Variable | Default | Purpose |
| --- | ---: | --- |
| `IMPORT_ID_FIELD` | `id` | Source field containing a stable document ID |
| `DOCUMENT_DEFAULT_COLLECTION` | `default` | Collection used by imports and searches when omitted |
| `IMPORT_COLLECTION_FIELD` | `collection` | Optional source field that selects a collection per record |
| `IMPORT_CONTENT_FIELDS` | `content` | Comma-separated fields joined into searchable text |
| `IMPORT_METADATA_FIELDS` | empty | Fields retained in metadata; empty keeps all unused fields |
| `IMPORT_GENERATE_IDS` | `false` | Generate an ID when no ID field exists |
| `IMPORT_MODE` | `upsert` | Default file synchronization behavior (`upsert` or `replace`) |
| `SEED_ROWS_PER_CHUNK` | `2000` | Source/file records processed per chunk |
| `SEED_EMBED_BATCH_SIZE` | `256` | Texts per embedding request |
| `SEED_DB_BATCH_SIZE` | `2000` | Rows committed per database statement |
| `SEED_MAX_EMBED_CONCURRENCY` | `6` | Concurrent embedding requests |

Lower batch size and concurrency when using a small model endpoint. See [Data import](importing-data.md) for mapping examples and synchronization semantics.

## Embedding dimension

The schema and bundled embedding model use 1,024-dimensional vectors. `VDB_EMBEDDING_DIM` is validated by application code, but changing it alone does not alter an existing PostgreSQL column. To adopt a different embedding dimension, change the migration/schema, recreate or migrate the database, and regenerate every stored embedding together. Mixing dimensions is not supported.

## Ports and cache

`API_PORT`, `POSTGRES_PORT`, `REDIS_PORT`, `SOURCE_API_PORT`, `EMBEDDING_PORT`, and `RERANKER_PORT` change host-side Compose ports. They do not change service-to-service container ports.

An empty native `CACHE_REDIS_URL` disables caching and distributed task locking. Compose enables Redis by default; set `COMPOSE_CACHE_REDIS_URL=` explicitly to disable cache access from application containers. `make start` and `make up` then omit the Redis service. The search pipeline fails open if Redis becomes unavailable.

`CORS_ALLOWED_ORIGINS` is a comma-separated list of browser origins and defaults
to `http://localhost:3000`. An empty value disables cross-origin browser access;
same-origin requests and non-browser API clients are unaffected.
`CORS_ALLOW_CREDENTIALS` defaults to `false`. CORS controls browser behavior and
does not provide authentication or authorization.
