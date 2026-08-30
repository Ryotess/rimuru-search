# Security Policy

## Supported version

Security fixes are applied to the latest revision of the `main` branch.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting feature for this repository. Do not include credentials, personal data, proprietary datasets, or exploit details in a public issue.

If private vulnerability reporting is unavailable, ask a maintainer in a public issue to enable a private reporting channel without disclosing the vulnerability itself.

You should receive an acknowledgement within seven days. Timelines for validation and remediation depend on severity and reproducibility.

## Deployment responsibility

Rimuru Search can be deployed as a production search service, but it does not
provide authentication, authorization, TLS termination, or environment-specific
deployment configuration. Operators are responsible for placing it behind
appropriate access controls and reviewing data exposure, CORS, secrets, logging,
dependencies, backups, observability, resource limits, and rate limits.
