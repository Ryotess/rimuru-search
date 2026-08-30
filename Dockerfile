FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/src

RUN groupadd --system app && useradd --system --gid app app

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-cache --no-dev --no-install-project

COPY --chown=app:app . .
USER app

CMD ["/app/.venv/bin/uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
