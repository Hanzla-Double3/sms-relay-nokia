# Publication review — 15 November 2026

The GitHub repository remains private. Changing visibility is an owner review step, not part of this preparation.

## Included

FastAPI gateway, native Kotlin Android app, tests, locked Python dependencies and Gradle wrapper, deployment/provisioning/sender scripts, example environment, architecture/API/setup/recovery guides, MIT license, contribution guidance, and security policy.

The working tree uses example hostnames and phone numbers. The sender requires your own HTTPS URL and rejects redirects. Production automation is explicitly opt-in, so a fork can build/test without signing or server secrets. The original private deployment can keep its variables/secrets outside source.

## Secrets review

Before the history reset, Gitleaks scanned the reachable Git history and tracked source. Three initial scanner findings were inspected: two documentation Bearer placeholders and a deterministic Android test token, not live credentials. Narrow scanner allowlists cover only those explicit strings. A separate exact-value check of the local provisioning tokens, administrator password and session secret found no occurrences in reachable history. Private credential files, databases, phone backups, keystores and private keys remain ignored, not published.

The pinned RSA PUBLIC_KEY is intentionally public verification material. No private signing key is included. Independent deployments must establish their own signing trust before initial installation.

## Before changing visibility

- Review the MIT license and your authorship/right to distribute all original code. Third-party libraries retain their own licenses.
- Review full history, branches/tags, releases, Actions artifacts/logs, PRs/issues and GitHub settings. Source scanning is not a guarantee that every external attachment or previous build artifact is free of sensitive information.
- **Main history was replaced with one clean initial commit on 15 November 2026.** The old 17-commit history included a real test recipient number and the original deployment hostname; those references were already removed from the current files. A recovery bundle remains only in the ignored private local backup directory. No old branch or tag is published. GitHub may retain old objects through caches, Actions runs, or other references, and existing clones retain their copies. Rewriting main is not a guarantee of global deletion; rotate any genuinely exposed credential and contact GitHub Support if sensitive cached objects need removal. No live credential was identified by the preparation scans.
- Configure a private vulnerability-reporting channel. Review Actions permissions and deployment environment protection before opening contributions.
- Re-run secret scanning and tests at the final reviewed commit. Audit dependency vulnerabilities again; the October audit is historical.
- Do not upload private `.local/`, `.env`, runtime data, a provisioned APK backup, or production signing material with a public release.

This review does not change GitHub visibility, rotate production credentials, touch the phone, send SMS, or certify the operator's carrier/SIM usage terms.

## Reproduce the history scan

Install Gitleaks from its official releases and verify its release checksum. From the repository root run:

```sh
gitleaks git . --redact --log-opts='--all'
```

The project configuration extends the default rules and permits only the explicit documentation placeholder and isolated deterministic test token listed in `.gitleaks.toml`. Do not widen those exceptions for real credentials. Avoid scanning private `.local/` into a public report. The preparation used Gitleaks 8.30.1 and checksum-verified its downloaded executable archive.
