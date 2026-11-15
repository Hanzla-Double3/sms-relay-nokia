# SMS relay security audit — 2026-10-02

Scope: FastAPI gateway, administrator/token management, Kotlin client, root charging helper, CI/deployment isolation and the live SMS virtual host. This is a source review with automated regressions and targeted live checks, not an exhaustive penetration test or certification. No SMS was submitted by the audit.

## Findings and fixes

**Medium: logout did not invalidate a copied session cookie. Fixed.** Previously logout deleted the browser cookie but its signed value remained valid for an hour. A regression reproduced a successful authenticated request after logout. Sessions now require a live SQLite registration of their hashed random nonce; logout deletes it immediately. Signatures also bind to the administrator password, so password rotation invalidates older cookies. Tests cover replay rejection, expiry, password rotation and durable logout across restart.

**Defense in depth: inline administrator scripts/styles previously required `unsafe-inline`. Fixed.** Each HTML response now generates a random CSP nonce for its script and style. The policy denies objects and framing and restricts connections to the same origin. Token mutations require authenticated sessions, JSON and the exact same Origin. Cookies are Secure, HttpOnly and SameSite=Strict in production; responses containing secrets/statistics are not cached.

**Credential rollback risk. Mitigated in production.** Environment caller credentials are imported once into the persistent hashed token registry. The active production environment now has an empty caller bootstrap map, preventing old pre-registry images from resurrecting a revoked static credential. Older images would reject callers instead. Preserve the SQLite registry/backups. Creation uses 256 random bits; raw new secrets are returned once, never listed or stored in the database. Revocation is persistent and immediately blocks new caller requests. Already accepted queue entries continue.

**Charging recovery stall on this handset. Fixed during hardware testing.** An unbounded Android process-command read could stall after app termination. The guardian now bounds that read to 128 bytes before parsing the process name. The real script is tested against padded command-line fixtures and threshold/recovery fixtures. The helper uses fixed local paths and a locally generated numeric PID; no server payload enters the root command. Its private root directory has mode 700, with a single-controller lock. It preserves the USB flag and changes only the MediaTek charging-disable flag. Battery safety timers, current/voltage limits, power path and firmware remain untouched.

## Verified controls and checks

- 35 pytest cases pass, including token authentication/scope/revocation/privacy, queue recovery, session replay and the actual charging shell resource's 80/60 hysteresis, cycle persistence across restarts, STOP, parent exit and invalid-reading cleanup.
- Android debug/release APK builds, 9 unit tests and lint pass. Earlier handset ledger/recovery instrumentation passed 7 tests; it was not rerun for unchanged ledger code in this audit.
- `pip-audit` reports no known vulnerabilities in the 21 pinned Python runtime packages. OSV batch queries report no known vulnerabilities for the 8 resolved Maven runtime coordinates. This reflects database coverage and versions on this date, not proof of absence of vulnerabilities.
- Live token creation/authentication, unauthorized Origin rejection, secret-free listing and revocation were checked using a temporary token that was then revoked. Existing sender credentials still authenticate. No message was created by these checks.
- Public SMS submissions require Bearer authentication; device WSS credentials and the administrator password are separate. Caller status queries are scoped. The current recipient allowlist remains restricted to the user-authorized recipient. Queue/rate/payload limits and bounded WSS handshake/frame handling are present.
- The Android client uses TLS, encrypted Keystore-backed provisioning, private components and explicit callback receivers. It does not request incoming-SMS read permissions. Duplicate guards survive restarts; uncertain modem submissions are not blindly retried. Logs expire after one hour with a row cap and redact recipients/message bodies.
- Live gateway runs as an unprivileged container user, drops all capabilities, enables no-new-privileges and publishes only `127.0.0.1:18082`. Private environment/database modes are 600; the data directory is 700. CPU, memory and Docker log limits are configured. Caddy handles the SMS hostname separately.
- Deployment uses a dedicated forced SSH command and a constrained archive receiver, with online SQLite backups and health-check rollback. The root SSH key is not stored in GitHub. Existing unrelated application containers were observed without replacement by this deployment.

## Remaining limitations

The installed handset APK is a development/debug build on an already rooted phone. A privileged local user, compromised root service or physical debugging access can defeat app secret protection; use a separately managed release signing key and restrict USB/root access for unattended production. Root guardian cleanup covers ordinary app exit/force-stop and requested stop; hardware failure, kernel failure or forcibly killing the guardian itself cannot be guaranteed to restore charging. No boot/OS module was installed. Unsupported phones fail closed for charging writes.

Only one gateway process is supported. Resource bounds and login throttling reduce abuse but a dedicated denial-of-service/load test was not performed; aggregate login throttling can temporarily delay legitimate sign-in. MFA is not implemented. OS, handset firmware, Docker base-image packages, host configuration beyond the SMS deployment and build-tool vulnerabilities were not exhaustively scanned. CI action major tags and the base image tag are not pinned to immutable digests. A full physical battery discharge/recharge cycle requires hours and remains an observation task; threshold transitions are simulated in tests, with actual charging pause/recovery checked on the Nokia.

## References

- [OWASP session management guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html): server-side session invalidation.
- [OSV API](https://google.github.io/osv.dev/api/): Maven runtime vulnerability queries.
- [Nokia MT6761 kernel charging driver](https://github.com/nokia-mt6761-devs/android_kernel_nokia_mt6761/blob/alps-wasp/drivers/power/supply/mtk_charger.c): current_cmd charging-disable semantics, checked against this rooted Nokia's exposed node.
