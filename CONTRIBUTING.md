# Contributing

Thank you for helping improve Rimuru Search.

## Development setup

1. Install Python 3.13, uv, and Docker.
2. Copy `.env.example` to `.env` and use local or non-sensitive values.
3. Run `make install`.
4. Run `make test`, `make lint`, and `make typecheck` before opening a pull request.

Use `make format` to apply the repository's Ruff formatting rules.

## Pull requests

Keep changes focused and include tests for changed behavior. Explain configuration or schema changes in the pull request and update the README when the public API changes.

Before submitting, confirm that the change contains none of the following:

- Credentials, tokens, private keys, or encrypted production secrets
- Employer, customer, or employee names and contact details
- Internal hostnames, IP addresses, cloud project/account IDs, or registry paths
- Proprietary datasets, model artifacts, screenshots, logs, or copied tickets
- Deployment automation or environment-specific production configuration

Only contribute work you have the right to license under Apache-2.0.

## Reporting security issues

Do not open public issues for suspected vulnerabilities or leaked credentials. Follow [SECURITY.md](SECURITY.md) instead.
