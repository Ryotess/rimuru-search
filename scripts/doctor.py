#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from src.config import app_settings

_DEPRECATED_SETTINGS = {
    "EMBED_EMBEDDING_MODEL": "EMBEDDING_MODEL_ID or EMBEDDING_REQUEST_MODEL",
    "RERANKER_RERANKER_MODEL": "RERANKER_MODEL_ID or RERANKER_REQUEST_MODEL",
}


@dataclass(frozen=True)
class Check:
    label: str
    ok: bool
    detail: str


def redact_url(value: str) -> str:
    """Hide credentials while keeping an endpoint useful for diagnostics."""
    parts = urlsplit(value)
    if not parts.password:
        return value
    hostname = parts.hostname or ""
    if parts.port:
        hostname = f"{hostname}:{parts.port}"
    username = f"{parts.username}:***@" if parts.username else "***@"
    return urlunsplit(
        (parts.scheme, f"{username}{hostname}", parts.path, parts.query, parts.fragment)
    )


def _run(command: list[str]) -> Check:
    try:
        completed = subprocess.run(  # noqa: S603  # Commands are fixed local diagnostics assembled by this script.
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Check(" ".join(command), False, str(exc))
    detail = (completed.stdout or completed.stderr).strip().splitlines()
    return Check(
        " ".join(command),
        completed.returncode == 0,
        detail[-1] if detail else f"exit {completed.returncode}",
    )


def _http_check(label: str, url: str) -> Check:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:  # noqa: S310
            return Check(label, 200 <= response.status < 400, f"HTTP {response.status}")
    except (urllib.error.URLError, TimeoutError) as exc:
        return Check(label, False, str(exc.reason if hasattr(exc, "reason") else exc))


def _model_check(label: str, api_base: str, configured_model: str) -> Check:
    base = api_base.rstrip("/")
    models_url = f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"
    requested_model = configured_model.removeprefix("hosted_vllm/")
    try:
        with urllib.request.urlopen(models_url, timeout=3) as response:  # noqa: S310
            payload = json.load(response)
    except (OSError, ValueError) as exc:
        return Check(label, False, str(exc))

    available = {
        item.get("id")
        for item in payload.get("data", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if requested_model not in available:
        return Check(
            label,
            False,
            f"configured model {requested_model!r} is not exposed by /v1/models",
        )
    return Check(label, True, f"model={requested_model}")


def deprecated_setting_names() -> set[str]:
    """Find deprecated names without reading or printing their values."""
    found = {name for name in _DEPRECATED_SETTINGS if name in os.environ}
    env_path = Path(app_settings.env_file_path)
    if not env_path.is_file():
        return found

    for line in env_path.read_text(encoding="utf-8").splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#") or "=" not in candidate:
            continue
        name = candidate.split("=", 1)[0].removeprefix("export ").strip()
        if name in _DEPRECATED_SETTINGS:
            found.add(name)
    return found


def _print_config() -> None:
    values = {
        "database": redact_url(app_settings.global_database_url),
        "embedding API": app_settings.embed_hosted_vllm_api_base,
        "embedding model ID": app_settings.embedding_model_id,
        "embedding request": app_settings.embed_embedding_model,
        "embedding dimension": app_settings.vdb_embedding_dim,
        "default collection": app_settings.document_default_collection,
        "HNSW iterative scan": app_settings.global_hnsw_iterative_scan,
        "browser origins": (
            ",".join(app_settings.cors_allowed_origins_list) or "disabled"
        ),
        "lexical backend": app_settings.search_lexical_backend,
        "reranker API": app_settings.reranker_hosted_vllm_api_base,
        "reranker model ID": app_settings.reranker_model_id,
        "reranker request": app_settings.reranker_reranker_model,
        "reranking enabled": app_settings.search_enable_rerank,
        "Redis": redact_url(app_settings.cache_redis_url or "disabled"),
        "Compose Redis": redact_url(app_settings.compose_cache_redis_url or "disabled"),
        "source API": (
            f"{app_settings.source_api_base_url}{app_settings.source_api_documents_path}"
        ),
        "search defaults": (
            f"vector={app_settings.search_vector_top_k_default}, "
            f"lexical={app_settings.search_lexical_top_k_default}, "
            f"rrf={app_settings.search_rrf_top_k_default}, "
            f"rerank={app_settings.search_rerank_top_n_default}"
        ),
        "import mapping": (
            f"id={app_settings.import_id_field}, "
            f"collection_field={app_settings.import_collection_field or 'fixed default'}, "
            f"content={app_settings.import_content_fields}, "
            f"metadata={app_settings.import_metadata_fields or 'all unused fields'}, "
            f"mode={app_settings.import_mode}"
        ),
    }
    print("Effective native/.env configuration")
    for key, value in values.items():
        print(f"  {key:20} {value}")
    for name in sorted(deprecated_setting_names()):
        print(f"  WARNING deprecated {name}; use {_DEPRECATED_SETTINGS[name]}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check local hybrid-search prerequisites."
    )
    parser.add_argument("--config-only", action="store_true")
    parser.add_argument(
        "--services", action="store_true", help="Also probe running native services"
    )
    args = parser.parse_args()

    _print_config()
    if args.config_only:
        return

    checks = [
        Check("Python 3.13+", sys.version_info >= (3, 13), sys.version.split()[0]),
        Check(
            "Docker CLI",
            shutil.which("docker") is not None,
            shutil.which("docker") or "not found",
        ),
    ]
    if checks[-1].ok:
        checks.extend(
            [
                _run(["docker", "info", "--format", "Docker daemon is reachable"]),
                _run(["docker", "compose", "version", "--short"]),
                _run(["docker", "compose", "config", "--quiet"]),
            ]
        )

    checks.append(
        Check(
            "Embedding dimension",
            app_settings.vdb_embedding_dim == 1024,
            f"configured={app_settings.vdb_embedding_dim}; schema=1024",
        )
    )

    if args.services:
        checks.append(
            _model_check(
                "Embedding service",
                app_settings.embed_hosted_vllm_api_base,
                app_settings.embed_embedding_model,
            )
        )
        if app_settings.search_enable_rerank:
            checks.append(
                _model_check(
                    "Reranker service",
                    app_settings.reranker_hosted_vllm_api_base,
                    app_settings.reranker_reranker_model,
                )
            )
        else:
            checks.append(Check("Reranker service", True, "disabled"))
        checks.append(_http_check("FastAPI", "http://localhost:8000/health/ready"))

    print("\nChecks")
    for check in checks:
        print(f"  {'OK' if check.ok else 'FAIL':4} {check.label}: {check.detail}")
    if not all(check.ok for check in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
