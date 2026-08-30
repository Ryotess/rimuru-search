import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_make_import_preserves_file_extension_for_auto_detection(
    tmp_path: Path,
):
    input_path = tmp_path / "documents.jsonl"
    input_path.touch()
    make = shutil.which("make")
    assert make is not None

    completed = subprocess.run(  # noqa: S603  # Resolved make executable and fixed dry-run arguments.
        [make, "-n", "import", f"FILE={input_path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert f"{input_path}:/data/documents.jsonl:ro" in completed.stdout
    assert "docker compose run --build --rm --no-deps" in completed.stdout
    assert 'importer "/data/documents.jsonl"' in completed.stdout
