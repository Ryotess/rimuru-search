import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _selected_services(tmp_path: Path, compose_environment: str) -> set[str]:
    docker = tmp_path / "docker"
    docker.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$FAKE_COMPOSE_ENVIRONMENT\"\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "FAKE_COMPOSE_ENVIRONMENT": compose_environment,
    }
    completed = subprocess.run(  # noqa: S603  # The executable is a repository-owned test script.
        [str(ROOT / "scripts/compose_services.sh")],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return set(completed.stdout.split())


def test_compose_services_include_bundled_defaults(tmp_path):
    assert _selected_services(tmp_path, "") == {
        "postgres",
        "migrate",
        "api",
        "embedding",
        "reranker",
        "redis",
    }


def test_compose_services_omit_disabled_and_external_dependencies(tmp_path):
    environment = "\n".join(
        [
            "SEARCH_ENABLE_RERANK=false",
            "COMPOSE_CACHE_REDIS_URL=",
            "COMPOSE_EMBED_API_BASE=http://models.example/v1",
        ]
    )

    assert _selected_services(tmp_path, environment) == {
        "postgres",
        "migrate",
        "api",
    }
