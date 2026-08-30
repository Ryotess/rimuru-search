# Public release checklist

This repository was prepared as an anonymized source tree. The existing Git metadata is not safe to publish as-is because historical commits may still contain former employee identities, organization-specific infrastructure, encrypted secrets, and removed deployment files.

## 1. Confirm publication rights

Before publishing, obtain written confirmation that you own the relevant copyright or have permission from the rights holder to release the work under Apache-2.0. Employment agreements often assign work product to the employer; anonymization does not change ownership.

Also verify that model, dataset, and dependency licenses allow the intended use. This repository does not include model weights or source data.

The **Rimuru Search** name is an anime-inspired reference, while the source code,
copy, and artwork in this repository are original. Before publication, review the
name for trademark and project-name conflicts in the jurisdictions where you plan
to distribute it. The disclaimer in `README.md` does not replace that review.

## 2. Review the sanitized tree

From the repository root, review every tracked file and run a secret scanner against the current working tree:

```bash
git status --short
git diff --stat
git diff
gitleaks dir . --redact
```

Search for organization names, personal email domains, internal hostnames, cloud account/project identifiers, private IP addresses, and customer-specific terminology. Treat encrypted secrets as sensitive metadata too; do not publish them merely because their plaintext is unavailable.

If any credential may previously have been exposed, rotate or revoke it. Removing a file or rewriting history does not invalidate a credential.

## 3. Start with clean history

The safest release path is a new repository with a single sanitized initial commit. Do not push the existing `.git` directory or reuse its remote.

```bash
release_dir="$(mktemp -d)/rimuru-search"
mkdir -p "$release_dir"
rsync -a \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='.env' \
  --exclude='.pytest_cache' \
  --exclude='.ruff_cache' \
  ./ "$release_dir/"

cd "$release_dir"
git init -b main
git add .
git commit -m "Initial open-source release"
```

Run the scanner and tests again inside the clean directory before adding a new GitHub remote.

## 4. Configure GitHub

- Create a new repository named `rimuru-search` without importing the old
  repository's history.
- Push the clean `main` branch.
- Confirm the Actions page shows only the `CI` workflow.
- Enable branch protection/rulesets with required CI checks and pull-request review.
- Enable secret scanning, push protection, Dependabot alerts, and private vulnerability reporting.
- Upload `docs/assets/rimuru-search-hero.png` as the repository social preview.
- Review GitHub account profile metadata if personal attribution is also meant to be minimized.

Use this repository metadata so GitHub search, package metadata, and the README
describe the project consistently:

- **Display name:** Rimuru Search
- **Repository slug:** `rimuru-search`
- **Description:** Run hybrid search locally or in production with PostgreSQL
  BM25, pgvector, RRF, and optional reranking.
- **Website:** leave empty unless public documentation is deployed.
- **Topics:** `bm25`, `hybrid-search`, `semantic-search`, `full-text-search`,
  `vector-search`, `information-retrieval`, `postgresql`, `pgvector`, `fastapi`,
  `python`, `reciprocal-rank-fusion`, `reranking`, `vllm`,
  `openai-compatible`, `docker-compose`

After the repository is created, verify that the clone URL, CI badge, and
`[project.urls]` entries in `pyproject.toml` all resolve to the same public slug.

## 5. Final verification

Inspect the public repository from a logged-out browser. Check commit authors, Actions logs, downloadable artifacts, repository metadata, issues, and the full file tree. Confirm that no package or container publishing credentials were added because this project intentionally implements CI only, not CD.
