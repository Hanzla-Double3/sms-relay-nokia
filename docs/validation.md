# Validation record — 1 October 2026

Implementation was built and checked on the supplied Arch host with the attached Nokia 2.2, stock Android 11/API 30. No flashing, rooting or ROM changes were performed. The app uses stock Android telephony, not root, to send SMS.

| Check | Observed outcome |
|---|---|
| Gateway automated suite | 25 passed; includes real HTTPS/WSS transport with verified test certificate, HTTP/WebSocket state/recovery/security tests and database reopening. |
| Kotlin unit suite | 8 passed; multipart aggregate outcomes, monotonic transitions, crash rules, masking and backoff. |
| Android SQLite instrumentation | 4 passed on the actual Nokia, using isolated test DBs; duplicate guard and crash recovery survive reopening, multipart callbacks/old ACK handling, known-received resumption and bounded logs. |
| Debug APK | Built, installed and locally provisioned on the Nokia. |
| Release APK | Built successfully, unsigned; private release signing is documented. |
| Android lint | Passed, zero errors; advisory warnings for deliberately chosen SDK/library versions and English-only appliance UI remain. |
| Docker | Gateway image built from hash-verified locked runtime dependencies; container health, DB write access and unprivileged UID 10001 verified. |
| Compose | Deployed on the public VPS as isolated project `sms-relay`, loopback backend behind the existing Caddy. |
| No-SIM operation | Nokia authenticated with `NO_SIM`; accepted disposable job stayed queued with zero dispatches. It was explicitly retired and payload scrubbed before the SIM was inserted. |
| UI closed | Foreground service stayed active with the Activity closed. |
| Server restart | Phone reconnected using its exponential backoff; durable queued ID remained unchanged. |
| Phone process crash | Killed only the relay process as a local diagnostic using existing root; Android restarted its sticky foreground service and it authenticated again without opening the UI. No root watchdog was installed. |
| Optional-app cleanup | 15 optional enabled packages disabled for user 0; original states preserved in a private restore snapshot. Telephony/network/core system packages preserved. |
| Secrets | Generated raw tokens absent from all non-ignored project files; private credentials, database, cleanup snapshot and APK build outputs are gitignored. |

## Actual carrier SMS acceptance

After the user inserted an SMS-capable SIM and explicitly authorized the test recipient, one short test SMS was submitted through the caller-authenticated API with a stable idempotency key. The active subscription was chosen by Android/default-SIM configuration; no source code embeds a SIM number.

Message ID: `sms_6c90132c4c56425393c80d47d2af3936`.

Server history recorded:

`queued → dispatched → phone_received → submitted_to_modem → sent`

Accepted at 21:58:55 Asia/Karachi; Android sent callback confirmed at 21:58:57. The user subsequently confirmed **received**. Server recipient/text fields were scrubbed after the successful callback. Only one real SMS was submitted in this local test; repeated use of its idempotency key returns the existing job.

## Public production acceptance

Server A is deployed at `https://relay.example.com`, and Nokia `nokia-01` is provisioned with `wss://relay.example.com/ws/device`. Android validates the public TLS certificate; the handset no longer depends on USB reverse forwarding. The app remains installed, startup enabled and exempted from battery optimization.

A second authorized carrier test, `sms_932e2c1a27354b01b13f1657c498d0e8`, was accepted while the phone was offline on the new gateway. It remained `queued` until the phone connected, then recorded the full history:

`queued → dispatched → phone_received → submitted_to_modem → sent`

Accepted at 22:16:08 Asia/Karachi; dispatched after WSS connection at 22:18:27 and callback-confirmed sent at 22:18:29. Recipient delivery has not been independently confirmed for this second test. Reusing the idempotency key returns the same job. No potentially submitted message was automatically retried.

Public HTTPS health, admin login, Secure/HttpOnly/SameSite session cookie and authenticated privacy-preserving stats were checked. The browser login page was observed; full dashboard visual verification was interrupted by browser-tool unavailability. Automated admin authorization/privacy tests passed. The dashboard password lives in the root-only production `.env`, outside releases and Git.

The existing Caddy configuration was preserved byte-for-byte before appending the SMS site block and gracefully reloading. Other application containers were not replaced or restarted. Unrelated sites retained their pre-deployment HTTP baseline responses.

Private source repository: `https://github.com/Hanzla-Double3/sms-relay-nokia`. Main pushes run gateway tests, Android debug/release builds, unit tests and lint before deploying through a dedicated restricted SSH identity. GitHub Actions run `36898385016` completed successfully, including the real restricted-SSH production deployment and public health check. See `docs/production.md` for operations, persistent storage, backups and rollback.

The recipient allowlist still contains only the authorized test number. Raw caller/device credentials remain private in `.local/credentials.json`. The production configuration mirror is `.local/production.env`; the active VPS configuration is `/opt/sms-relay/shared/.env`.

## Remaining hardware acceptance checks

A real phone reboot, live Wi-Fi/mobile-data handover, carrier multipart/partial-failure behavior, delivery-receipt support, and an actual crash during a potentially sent modem call were not exercised on the carrier. Their state/recovery logic is covered by automated/instrumentation tests; use the separate acceptance checklist for later hardware testing. No exactly-once guarantee is claimed.

Undo optional-package cleanup with `python scripts/phone_cleanup.py --restore` using the saved `.local/phone-cleanup.json`. The optional Magisk watchdog remains opt-in and uninstalled.

## Wall display update — 2 October 2026

Android v0.2.0 was upgraded in place on the Nokia, preserving provisioning and the existing SMS ledger. The landscape clock/status dashboard and separate controls screen were inspected on the physical display. Home shows one last event; detailed logs and startup/ledger controls are off the home screen. The production gateway observed the new app version online and READY. No carrier test SMS was sent for this UI update.

Debug and unsigned release builds, eight Kotlin unit tests and Android lint passed. Seven isolated handset SQLite tests passed, including a new check that one-hour-old events are deleted even on idle log reads and maintenance, while SMS duplicate guards remain. Last-sent metadata survives log expiry/reopening; late delivery does not alter its send time. The additive version-1-to-2 ledger migration preserves old confirmed sends and duplicate guards. The old 500-row cap remains. Brightness persists locally; the awake preference is preserved.
