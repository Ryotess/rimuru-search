# AGENTS.md

This file applies to the entire repository. More specific `AGENTS.md` files may
override it within their own subdirectories.

## Project intent

Rimuru Search is an anonymized, domain-neutral, production-capable hybrid search
service. It combines PostgreSQL lexical search, pgvector semantic search,
Reciprocal Rank Fusion, and optional cross-encoder reranking.

Use **Rimuru Search** for the public product name and `rimuru-search-api` for the
Python distribution name. The name is a light reference to absorbing, analyzing,
and synthesizing multiple signals. Keep all project artwork and copy original:
do not add copyrighted character images, franchise logos, quotations, screenshots,
or claims of affiliation or endorsement.

Keep the project suitable for a public GitHub repository:

- Use generic document terminology: `Document`, `id`, `content`, and `metadata`.
- Do not introduce former business-domain entities into core names or APIs.
- Do not add employer, customer, employee, or internal infrastructure details.
- Do not add production deployment configuration, CD workflows, image publishing,
  secrets, encrypted secrets, or environment-specific infrastructure.
- CI quality checks are in scope; deployment and release automation are not.
- Keep the repository description, topics, badges, package metadata, FastAPI
  metadata, README, and demo title consistent with the public project name.

The existing Git history is not safe for public release. Never push or publish it
as the open-source history. Follow `docs/PUBLISHING.md` and create a clean repository
with a sanitized initial commit.

## Runtime architecture

The search path is:

1. FastAPI receives a query.
2. The OpenAI-compatible embedding service creates a query vector.
3. PostgreSQL runs vector and lexical retrieval.
4. Reciprocal Rank Fusion combines candidates.
5. The OpenAI-compatible reranker produces the final order.

The ingestion path either maps a JSON/JSONL/CSV file or reads the paginated source
API contract documented in `README.md`, embeds each document, and writes it to
PostgreSQL.

Important invariants:

- Document identity is `(collection, id)`. Search, import, dump/load, cache, and
  fusion changes must preserve collection isolation.
- The database embedding column is 1,024-dimensional. Model changes must preserve
  that dimension or include an explicit schema and data-regeneration plan.
- `SEED` writes to the live table with an idempotent upsert. It does not delete IDs
  that disappeared from the source.
- `RESEED` builds a complete staging snapshot and atomically swaps it into place.
- Direct file `upsert` and `replace` preserve the same live/staging semantics as
  `SEED` and `RESEED`.
- FastAPI startup must not automatically import data or resume interrupted work.
  A user must explicitly submit a seeding operation.
- Successful live seed/reseed operations invalidate cached search responses.
- `GET /health` is liveness. `GET /health/ready` checks search-path dependencies.

## Development commands

Use `uv` through the existing Make targets when possible:

```bash
make install
make test
make lint
make typecheck
make format
```

For the complete Docker demo:

```bash
make demo-up
make demo-status
make demo-down
```

`make demo-reset` deletes the demo database and model-cache volumes. Do not run it
unless destructive reset behavior is explicitly requested.

For native development, use the separate targets documented in `README.md`:
`make host-db`, `make migrate-db`, `make sample-source`, `make serve-vllm`, and
`make run`.

## Code conventions

- Target Python 3.13 and follow the Ruff configuration in `pyproject.toml`.
- Prefer async implementations for database, HTTP, Redis, and service boundaries.
- Keep settings in `src/config.py` and expose feature-specific proxies through the
  existing feature config modules.
- Keep local defaults usable without a `.env` file. Never add real credentials or
  production endpoints to defaults or examples.
- Preserve the OpenAI-compatible embedding and reranking interfaces.
- Do not log database URLs, Redis URLs with credentials, secrets, or full sensitive
  payloads.
- Add an Alembic revision for schema changes. Do not silently make the ORM model and
  migration schema disagree.
- Update `README.md`, `.env.example`, Compose configuration, and API schemas together
  when public behavior or configuration changes.
- Update `uv.lock` only when dependency declarations or locked project metadata
  change.

## Public documentation

- Write the README for a first-time evaluator: lead with the problem, value,
  architecture, and shortest working demo before detailed configuration.
- Keep the README quick start runnable from a fresh public clone. Do not use
  placeholders for the canonical repository URL once the public slug is chosen.
- Keep advanced operational detail in `docs/` and link to it from the README.
- Use relative links for repository files and assets so forks render correctly.
- Badge and metadata changes must not imply capabilities the repository does not
  provide. In particular, do not add release, package, image, coverage, or
  deployment badges without the corresponding public workflow or service.
- Describe production scope precisely: the search service can run in production,
  while operators remain responsible for perimeter security, infrastructure,
  backups, observability, and environment-specific deployment policy.
- When public behavior changes, update the README, relevant `docs/` pages,
  `.env.example`, API metadata, and examples together.
- Repository topics and the GitHub About description are recorded in
  `docs/PUBLISHING.md`; keep that release metadata aligned with `pyproject.toml`.

## Tests

Tests must be grouped by feature under `tests/<feature>/`. Do not create a flat
catch-all test directory. Put shared fixtures only in `tests/conftest.py`.

Examples:

- Cache behavior: `tests/cache/`
- Configuration and application behavior: `tests/core/`
- Health endpoints: `tests/health/`
- Search orchestration: `tests/orchestrator/`
- Ingestion and task behavior: `tests/seeding/`
- Direct file import: `tests/importing/`
- Source API contract: `tests/source_api/`

For a change, run the closest feature tests first, then run the full checks before
handoff:

```bash
PYTHONPATH=src:. uv run pytest tests/<feature> -q
uv run ruff check .
uv run ruff format --check .
PYTHONPATH=src:. uv run mypy src
PYTHONPATH=src:. uv run pytest -q
git diff --check
```

Unit tests must not require live model services or public network access. When
changing Compose, models, migrations, or cross-service behavior, also validate the
relevant Compose configuration and perform an end-to-end smoke test when Docker is
available.

## Git and change safety

- Preserve unrelated user changes in a dirty working tree.
- Do not commit unless the user explicitly asks for a commit.
- Do not push, rewrite history, change remotes, or publish a repository unless the
  user explicitly requests that exact action.
- Do not delete Docker volumes, databases, dumps, model caches, or local `.env`
  files without explicit authorization.
- Before committing, inspect `git status`, run `git diff --check`, and verify the
  change with tests proportional to its risk.
