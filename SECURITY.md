# Security policy

Do not disclose vulnerabilities or real credentials in a public issue. Use GitHub's private vulnerability reporting / Security Advisories if enabled by the maintainer. If unavailable, ask for a private reporting channel without posting exploit details or sensitive data. Only the current main branch is maintained; no response-time or security warranty is promised.

## Trust boundaries

Caller Bearer tokens, device WebSocket tokens, the dashboard password/session secret, SSH deployment keys, APK signing keys, and OTA manifest signing keys are independent credentials. Caller tokens are scoped to devices and their own jobs. The gateway stores credential hashes; Android encrypts provisioning through Keystore. TLS is mandatory outside loopback debug development. Never use the example credential placeholders in a real deployment.

The gateway can send SMS through configured SIMs, and root updater/charging features add local privileges on supported devices. Only run trusted builds and restrict root/USB access. The root OTA installer accepts signed, version-increasing APKs with the installed signing identity, not arbitrary remote shell commands. The committed OTA public key is public verification material, not a secret; independent deployments must replace it with their own key before first installation.

## Data and recovery

Queued SMS content and destination numbers exist in private server/phone databases until terminal processing scrubs payloads. Diagnostics omit bodies and full numbers but expose operational metadata. Encrypt/restrict backups and preserve the SMS duplicate guards. This relay cannot guarantee exactly-once delivery across the database/modem boundary. `sent` is an Android send callback, `delivered` requires carrier receipts, and `unknown` needs human review. Carrier filtering can prevent delivery even after a successful send callback.

Run one gateway process. Keep the backend behind HTTPS, scope caller tokens, use an explicit recipient allowlist where practical, and retain queue/rate limits. A rooted phone, compromised host, physical attacker, or malicious administrator can defeat these boundaries. Admin MFA and horizontal dispatch leases are not implemented. The historical [October audit](docs/security-audit-2026-10-02.md) is a dated record, not a current certification.

## Before publication

Follow the [publication checklist](docs/publication-review.md). Ignore rules prevent accidental additions but do not remove already committed data or clean history. If a genuine secret is exposed, revoke/rotate it first, then purge affected history and any downloadable artifacts. Do not assume deleting a file fixes exposure.
