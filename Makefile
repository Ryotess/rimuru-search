.DEFAULT_GOAL := help

.PHONY: help install start demo-up demo-down demo-reset demo-logs demo-status sample-source host-db init-db migrate-db seed-db reseed-db import import-native dump-db seed-from-dump serve-vllm run doctor config smoke-models test pressure-test lint typecheck format clean tidy host build up down rebuild buildup

help:
	@echo "Rimuru Search"
	@echo "  make demo-up                         Start the complete sample demo"
	@echo "  make start FILE=./documents.jsonl   Start services and import your data"
	@echo "  make import FILE=./documents.csv    Upsert a file into running services"
	@echo "  make config                          Show effective native/.env settings"
	@echo "  make doctor                          Check local prerequisites"
	@echo "  make smoke-models                    Validate embedding and reranker output"
	@echo "  make test                            Run all feature-grouped tests"
	@echo "  make lint                            Run Ruff checks"
	@echo "  make typecheck                       Run mypy against production source"
	@echo "  make format                          Run Ruff formatter"
	@echo "  make down                            Stop services and preserve volumes"

start:
	@test -n "$(FILE)" || (echo "Usage: make start FILE=./documents.jsonl [ARGS='--mode replace']" && exit 2)
	@test -f "$(FILE)" || (echo "Input file not found: $(FILE)" && exit 2)
	@services="$$(./scripts/compose_services.sh)"; \
	docker compose up --build -d --wait $$services
	$(MAKE) import FILE="$(FILE)" ARGS="$(ARGS)"
	@published="$$(docker compose port api 8000 | tail -n 1)"; \
	port="$${published##*:}"; \
	echo "Search API ready at http://localhost:$$port/v1/search/demo"

demo-up:
	docker compose --profile demo up --build --wait
	@published="$$(docker compose port api 8000 | tail -n 1)"; \
	port="$${published##*:}"; \
	echo "Demo ready at http://localhost:$$port/v1/search/demo"

demo-down:
	docker compose --profile demo down

demo-reset:
	@echo "Removing demo containers and database/model-cache volumes..."
	docker compose --profile demo down --volumes

demo-logs:
	docker compose --profile demo logs -f

demo-status:
	docker compose --profile demo ps -a

install:
	uv sync --locked --no-cache

sample-source:
	PYTHONPATH=src:. uv run uvicorn examples.sample_source_api:app --host 127.0.0.1 --port 3000

host-db:
	docker compose -f scripts/hybrid_db/docker-compose.yml up -d

init-db:
	PYTHONPATH=src:. uv run alembic upgrade head
	PYTHONPATH=src:. uv run scripts/hybrid_db/seed.py

migrate-db:
	PYTHONPATH=src:. uv run alembic upgrade head

seed-db:
	PYTHONPATH=src:. uv run alembic upgrade head
	PYTHONPATH=src:. uv run scripts/hybrid_db/seed.py

reseed-db:
	PYTHONPATH=src:. uv run alembic upgrade head
	PYTHONPATH=src:. uv run scripts/hybrid_db/reseed_staging.py

import:
	@test -n "$(FILE)" || (echo "Usage: make import FILE=./documents.jsonl [ARGS='--mode replace']" && exit 2)
	@test -f "$(FILE)" || (echo "Input file not found: $(FILE)" && exit 2)
	docker compose run --build --rm --no-deps \
		-v "$(abspath $(FILE)):/data/$(notdir $(FILE)):ro" \
		importer "/data/$(notdir $(FILE))" $(ARGS)

import-native:
	@test -n "$(FILE)" || (echo "Usage: make import-native FILE=./documents.jsonl [ARGS='--mode replace']" && exit 2)
	@test -f "$(FILE)" || (echo "Input file not found: $(FILE)" && exit 2)
	PYTHONPATH=src:. uv run scripts/import_documents.py "$(FILE)" $(ARGS)

dump-db:
	PYTHONPATH=src:. uv run scripts/dump_documents.py

seed-from-dump:
	PYTHONPATH=src:. uv run scripts/load_documents.py

serve-vllm:
	docker compose -f docker-compose.vllm.yml up

run:
	PYTHONPATH=src:. uv run uvicorn src.main:app --reload

doctor:
	PYTHONPATH=src:. uv run scripts/doctor.py

config:
	PYTHONPATH=src:. uv run scripts/doctor.py --config-only

smoke-models:
	PYTHONPATH=src:. uv run scripts/check_models.py

test:
	PYTHONPATH=src:. uv run pytest

pressure-test:
	@set -e; \
	PYTHONPATH=src:. uv run uvicorn src.main:app --reload & \
	UVICORN_PID=$$!; \
	echo "uvicorn pid=$$UVICORN_PID"; \
	trap "echo 'stopping uvicorn group...'; pkill -P $$UVICORN_PID 2>/dev/null || true; kill $$UVICORN_PID 2>/dev/null || true" EXIT INT TERM; \
	sleep 3; \
	PYTHONPATH=src:. uv run scripts/pressure_test.py $(ARGS)


lint:
	uv run ruff check .

typecheck:
	PYTHONPATH=src:. uv run mypy src

format:
	uv run ruff format .

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .venv

tidy:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true

host:
	PYTHONPATH=src:. uv run uvicorn src.main:app

# Docker targets
build:
	docker compose build

up:
	@services="$$(./scripts/compose_services.sh)"; \
	docker compose up --wait $$services

down:
	docker compose down

rebuild:
	docker compose build --no-cache
	@services="$$(./scripts/compose_services.sh)"; \
	docker compose up --wait $$services
	@published="$$(docker compose port api 8000 | tail -n 1)"; \
	port="$${published##*:}"; \
	echo "Rebuilt and started the stack at http://localhost:$$port/v1/search/demo"

buildup: build up
	@echo "Built and started the stack."
