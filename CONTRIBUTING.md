# Contributing

Use Python 3.11+, uv, a complete JDK 21, and Android SDK platform 35/build tools 36.0.0. Follow the [README](README.md) for initial setup and [testing guide](docs/testing.md) for hardware acceptance. Root is unnecessary for basic SMS relay; charging control and unattended package installation are optional, Nokia-specific features.

Create a branch and keep changes focused. Run:

```sh
uv run --project gateway --extra test --locked pytest gateway/tests -q
cd android
./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleRelease
```

CI builds and tests without production credentials. Deployment and signed OTA packaging run only when the repository variable `SMS_PRODUCTION_ENABLED` equals `true` on main. Forks should leave it unset. See [release setup](docs/releasing.md).

Explain the problem, behavior change, and verification in your PR. Preserve caller/device isolation, durable duplicate guards, callback-confirmed outcomes, bounded logs, and the single-process dispatch model. Test recovery changes at crash boundaries, including ambiguous submission outcomes. Never introduce blind retry after a possible modem submission.

Use synthetic test tokens/numbers and isolated test databases. Do not send real SMS without permission, clear the live handset ledger, or use Gradle connected tests against an operational phone: install/update manually and run isolated instrumentation as described in the testing guide. Never attach `.env`, logs containing credentials, production DBs, phone backups, or signing material to issues/PRs.

Dependencies remain pinned in gateway/uv.lock. Refresh gateway/requirements.lock using the documented uv export command after runtime dependency changes. Dependency licenses remain their respective owners' licenses; the MIT license applies to this project's original code.
