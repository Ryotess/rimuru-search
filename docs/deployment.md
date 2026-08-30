# Microservice deployment guide

This document describes the runtime contract for deploying the project as a set
of independently managed services. It is intentionally platform-neutral. The
repository does not provide Kubernetes manifests, Helm charts, Terraform,
container publishing, or continuous deployment automation.

Use the bundled Docker Compose stack for local evaluation. In a microservice
environment, build the application image and connect it to services managed by
your own platform.

## Service topology

```text
                              ┌────────────────────┐
Client / API gateway ───────> │ search-api         │
                              │ FastAPI replicas   │
                              └───┬────┬────┬──────┘
                                  │    │    │
                    ┌─────────────┘    │    └──────────────┐
                    ▼                  ▼                   ▼
              PostgreSQL          Redis              embedding API
              + pgvector        (optional)                 │
              + pg_textsearch                              │
                                                          ▼
                                                    reranker API
                                                      (optional)

migration process ───────────────> PostgreSQL
import / seed process ───────────> PostgreSQL + embedding API
```

The application image contains FastAPI, migrations, and ingestion commands. It
does not contain PostgreSQL, Redis, an embedding model, or a reranking model.
Those are separate backing services in a microservice deployment.

## One image, multiple processes

Build the application image from the repository root:

```bash
docker build -t rimuru-search-api:local .
```

The same immutable image can run several process types. A deployment platform
should run each process independently rather than starting all of them in one
container.

| Process | Command | Lifetime |
| --- | --- | --- |
| Search API | `/app/.venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000` | Long-running |
| Migration | `/app/.venv/bin/alembic upgrade head` | Run to completion |
| File import | `/app/.venv/bin/python scripts/import_documents.py /data/documents.jsonl` | Run to completion |
| Source seed | `/app/.venv/bin/python scripts/hybrid_db/seed.py` | Run to completion |
| Source reseed | `/app/.venv/bin/python scripts/hybrid_db/reseed_staging.py` | Run to completion |

The Dockerfile already uses exec-form `CMD` and listens on container port 8000.
The orchestration platform is responsible for exposing that port through its
service discovery and ingress mechanism.

## Runtime configuration

Inject normal application environment variables into the container. Do not use
the `COMPOSE_*` variables outside the bundled Compose workflow; those exist only
to distinguish container-network addresses from host addresses during local
development.

Minimum search-path configuration:

```dotenv
GLOBAL_DATABASE_URL=postgresql://search_user:password@postgres.example:5432/search  # pragma: allowlist secret

EMBED_HOSTED_VLLM_API_BASE=http://embedding-service:8000/v1
EMBEDDING_MODEL_ID=your-embedding-model

RERANKER_HOSTED_VLLM_API_BASE=http://reranker-service:8000/v1
RERANKER_MODEL_ID=your-reranker-model

CACHE_REDIS_URL=redis://redis-service:6379/0
DOCUMENT_DEFAULT_COLLECTION=default
VDB_EMBEDDING_DIM=1024
SEARCH_LEXICAL_BACKEND=bm25
```

Use the platform's secret mechanism for database passwords, Redis credentials,
API tokens, and other sensitive values. Do not bake secrets into the image,
commit a runtime `.env` file, or log resolved connection URLs.

### Configuration groups

| Concern | Variables |
| --- | --- |
| PostgreSQL | `GLOBAL_DATABASE_URL`, `GLOBAL_DB_POOL_SIZE`, `GLOBAL_DB_MAX_OVERFLOW`, `GLOBAL_DB_POOL_TIMEOUT`, `GLOBAL_DB_POOL_RECYCLE` |
| Embedding | `EMBED_HOSTED_VLLM_API_BASE`, `EMBEDDING_MODEL_ID`, optional `EMBEDDING_REQUEST_MODEL`, `VDB_EMBEDDING_DIM` |
| Reranking | `RERANKER_HOSTED_VLLM_API_BASE`, `RERANKER_MODEL_ID`, optional `RERANKER_REQUEST_MODEL`, `RERANKER_REMOTE_CODE_FLAG`, `SEARCH_ENABLE_RERANK`, `RERANKER_MAX_DOCUMENT_LENGTH` |
| Cache and coordination | `CACHE_REDIS_URL`, `CACHE_TTL_SECONDS`, `CACHE_KEY_PREFIX` |
| Browser access | `CORS_ALLOWED_ORIGINS`, `CORS_ALLOW_CREDENTIALS` |
| Search defaults | `SEARCH_LEXICAL_BACKEND`, `SEARCH_VECTOR_TOP_K_DEFAULT`, `SEARCH_LEXICAL_TOP_K_DEFAULT`, `SEARCH_RRF_TOP_K_DEFAULT`, `SEARCH_RERANK_TOP_N_DEFAULT`, `SEARCH_USE_FUZZY_DEFAULT` |
| Document scope | `DOCUMENT_DEFAULT_COLLECTION` |
| File ingestion | `IMPORT_*`, `SEED_ROWS_PER_CHUNK`, `SEED_EMBED_BATCH_SIZE`, `SEED_DB_BATCH_SIZE`, `SEED_MAX_EMBED_CONCURRENCY` |
| Source ingestion | `SOURCE_API_BASE_URL`, `SOURCE_API_DOCUMENTS_PATH` |

`API_PORT`, `POSTGRES_PORT`, `REDIS_PORT`, `SOURCE_API_PORT`,
`EMBEDDING_PORT`, and `RERANKER_PORT` only control host-port publishing in the
local Compose files. They do not configure service discovery in a microservice
environment.

See [Configuration](configuration.md) for individual defaults and the embedding
dimension migration requirements.

## PostgreSQL requirements

The bundled database image uses PostgreSQL 18 with pgvector and pg_textsearch
1.2.0. BM25 deployments must install `vector`, `pg_textsearch`, `unaccent`, and
`pg_trgm`, and must load `pg_textsearch` through
`shared_preload_libraries` before running migrations. The repository's
`docker/postgres/Dockerfile` builds this local image from pinned source; the
project does not publish it to a registry.

An operator-provided PostgreSQL service must support the same extensions. Run
the migration process only after the extension binaries and preload setting are
present. Restoring a database dump on another host likewise requires installing
the extension binaries first.

Do not start PostgreSQL 18 directly on a PostgreSQL 16 data directory. Upgrade
an existing installation with `pg_dump`/`pg_restore` or an operator-managed
major-version procedure. The project never removes or upgrades an existing
database volume automatically.

The bundled Compose files use PostgreSQL-major-versioned volume keys. Upgrading
the repository therefore creates a new PostgreSQL 18 volume instead of attaching
an older demo volume to an incompatible server. The older volume remains intact
until the operator deliberately migrates or removes it.

## Startup and migration order

Use this lifecycle:

```text
Backing services become reachable
              ↓
One migration process completes successfully
              ↓
Search API replicas start
              ↓
An explicit import or seed process runs when data should change
```

FastAPI startup intentionally does not run migrations, import documents, seed a
source, or resume interrupted ingestion. This avoids every API replica racing to
perform stateful work.

Run migrations once per release. For example, a generic one-off container run is:

```bash
docker run --rm \
  --env-file runtime.env \
  rimuru-search-api:local \
  /app/.venv/bin/alembic upgrade head
```

`runtime.env` is only a placeholder in this example. Prefer secret and
configuration injection supplied by the target platform.

## Ingestion processes

### Files

Mount or otherwise provide the input file to a one-off process:

```bash
docker run --rm \
  --env-file runtime.env \
  --mount type=bind,source=/absolute/path/documents.jsonl,target=/data/documents.jsonl,readonly \
  rimuru-search-api:local \
  /app/.venv/bin/python scripts/import_documents.py \
  /data/documents.jsonl --mode upsert
```

Use `upsert` for incremental changes. Use `replace` only when the input is an
authoritative service-wide snapshot: it fills a staging table and atomically
swaps it into place after all documents are embedded successfully. Collections
missing from that snapshot are removed.

### Paginated sources

For a paginated HTTP source, run `seed.py` or `reseed_staging.py` as an explicit
one-off process. `SEED` upserts live data and preserves missing upstream IDs;
`RESEED` replaces the complete service-wide snapshot through staging, including
all collections.

The `POST /v1/seeding/tasks` API remains convenient for local and simple
single-service operation, but its background work is owned by the FastAPI
process that accepted the request. A deployment that requires independently
scheduled, retried, or long-running ingestion should invoke the ingestion
command as a platform Job instead of depending on an API replica to host it.

Successful live imports, seeds, and reseeds invalidate search cache entries.
Configure Redis when multiple API or ingestion replicas need shared cache and
seeding coordination.

## Health probes

| Endpoint | Meaning | Suggested use |
| --- | --- | --- |
| `GET /health` | The FastAPI process is alive | Liveness probe |
| `GET /health/db` | PostgreSQL round trip and pool state | Diagnostics |
| `GET /health/ready` | PostgreSQL lexical indexes, configured model IDs, and configured Redis are ready | Readiness probe |

Do not use `/health` as readiness: it can succeed while the search path is
unavailable.

The model checks call each OpenAI-compatible `/v1/models` endpoint and verify
that the configured request-model name is exposed. When
`SEARCH_ENABLE_RERANK=false`, the response reports `"reranker": "disabled"`
and no reranker deployment is required. An empty `CACHE_REDIS_URL` similarly
reports Redis as disabled.

The lexical check validates the configured BM25 or FTS index and the trigram
extension/index used by `use_fuzzy=true`. A missing BM25 extension or invalid
index makes the service not ready; it does not silently change ranking backends.

## Model service resources

Model memory and startup time vary with architecture, runtime version, sequence
length, batch/concurrency limits, and CPU or GPU backend. Measure the exact model
image rather than copying the API container's resource settings. See
[Model compatibility](model-compatibility.md) for the runtime checklist and an
example showing why model-specific observations are not portable defaults.

For large model processes:

- keep downloaded model weights on a persistent cache volume;
- allow a startup probe long enough for first load and compilation;
- use a rollout strategy that does not temporarily require two model copies
  when the node cannot hold both;
- inspect `OOMKilled` status and model logs before increasing readiness delays;
- scale model replicas from request latency and queueing independently of API
  replicas.

## Horizontal scaling

The normal search request path is stateless. Replicate the API at the platform
level and keep one application process per container unless the target runtime
has a specific reason to use multiple workers in a container.

Each replica owns a PostgreSQL connection pool. Plan the maximum application
connections as:

```text
API replicas × (GLOBAL_DB_POOL_SIZE + GLOBAL_DB_MAX_OVERFLOW)
```

Add ingestion process pools to that total and keep the result within the
database connection limit. Scale embedding and reranking capacity from their
request latency, batch size, and concurrency rather than assuming they scale at
the same rate as the API.

Redis is optional for a single API process. In a multi-replica deployment it is
recommended for shared response caching and cross-process seeding locks. Cache
failures are fail-open, so search continues without cached responses when Redis
is unavailable.

## Data invariants

- Document identity is `(collection, id)`. A request searches exactly one
  collection, and the same ID may exist in another collection.
- The bundled database schema stores 1,024-dimensional vectors. A different
  embedding dimension requires a schema migration and regeneration of every
  stored embedding.
- Metadata filters use PostgreSQL JSONB containment. Metadata is returned with
  hits but is not automatically added to lexical or embedding content.
- `SEARCH_LEXICAL_BACKEND` is deployment-wide. Both BM25 and FTS indexes are
  retained, but clients cannot select a backend per request.
- Changing a model without regenerating stored embeddings can make existing and
  new vectors semantically incompatible even when their dimensions match.

## Platform responsibilities

This repository supplies the application runtime, not a hardened deployment
platform. Operators remain responsible for:

- authentication and authorization;
- TLS termination and trusted proxy configuration;
- network policies and database access controls;
- secret storage and rotation;
- request limits, rate limits, and abuse protection;
- logs, metrics, traces, alerts, and data-retention policy;
- backups and restore testing;
- resource requests, autoscaling, disruption policy, and rollout strategy;
- vulnerability review of application and model images.

Keep these policies outside the repository unless they can be expressed as a
safe, platform-neutral example without credentials or environment-specific
infrastructure.

## Non-goals

The project intentionally does not include:

- Kubernetes or cloud-provider manifests;
- Helm charts or operators;
- Terraform or other infrastructure provisioning;
- container registry publishing;
- deployment credentials;
- continuous deployment workflows.

These choices keep the production-capable search service reusable across
platforms while leaving infrastructure and perimeter policy under operator
control. The repository provides continuous integration only.
