from pathlib import Path


def test_demo_management_targets_include_the_demo_profile():
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "demo-down:\n\tdocker compose --profile demo down" in makefile
    assert (
        "demo-reset:\n"
        '\t@echo "Removing demo containers and database/model-cache volumes..."\n'
        "\tdocker compose --profile demo down --volumes"
    ) in makefile
    assert "demo-logs:\n\tdocker compose --profile demo logs -f" in makefile
    assert "demo-status:\n\tdocker compose --profile demo ps -a" in makefile
