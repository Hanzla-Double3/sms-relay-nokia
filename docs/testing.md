# Validation and later carrier acceptance

## Automated checks

```sh
uv run --project gateway --extra test --locked pytest gateway/tests -q
cd android
./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleRelease
```

Gateway tests use real FastAPI handlers and in-process WebSocket sessions backed by fresh SQLite files. They cover caller-scoped access, admin access, distinct device authentication, malformed/oversized payloads, allowlist/rate/queue limits, idempotency conflicts, no-SIM queuing, callback-derived status, server database reopening, same-ID redispatch, unknown reconciliation and cross-device isolation. Kotlin tests cover recovery/state/multipart rules and masking. These tests do not claim to validate a carrier, SIM, real callbacks, modem timing or reboot behavior.

## Connected handset smoke tests, without a SIM

Build and install the debug app; use the README's private local credentials and ADB reverse. Configure the phone, grant permissions, and Start. Expect:

- `CONNECTED` and `NO_SIM` in the terminal screen.
- Administrator `GET /v1/devices` shows online with `ready:false` and `health_code:NO_SIM`.
- An accepted job remains queued, never submitted/sent. Use a **disposable isolated development database** for dummy-number tests and expire/remove those test jobs before inserting any SIM.
- Press Home: foreground notification/service persists and heartbeats continue.
- Restart Server A with the same DB: the app reconnects without opening the UI, and the queued ID is unchanged.
- Kill only the debug application's process (not force-stop): Android's sticky service should recover, reconnect and preserve its ledger. Force-stop is different: Android intentionally suppresses background restarts until user launch.
- Denied permission shows `PERMISSION_REQUIRED`; no jobs are accepted for execution. Grant/start again to recover.

## Later tests requiring an authorized SIM/recipient

Begin with an allowlist containing only the explicit authorized recipient, low rate and a funded SMS-capable SIM. Use recipient consent and your operator's permitted traffic rules.

1. Submit one uniquely keyed short operational SMS. Check queued → dispatched → phone_received → submitted_to_modem → **sent only from Android's sent callback**. Confirm the recipient actually receives it. Delivery is optional.
2. Submit a long Unicode message requiring multiple segments. Verify each part's callbacks and aggregate sent/delivery result. Inject/observe a part failure to confirm partial outcomes become unknown, not a whole-message retry.
3. Lock the screen/close the Activity; submit another message and verify foreground service behavior.
4. Change Wi-Fi/mobile network and restart Server A. Verify queued jobs resume using the same IDs and late callback statuses reconcile.
5. Redeliver a previously persisted ID: confirm it is never intentionally sent twice. Retain the phone ledger.
6. Kill the process immediately after submission/lose the connection. Verify unknown or callback-derived sent is reported; no automatic retry follows callback silence.
7. Disable the SIM/revoke SEND_SMS: confirm no false sent result, health warning and queued jobs. Restore permission/SIM.
8. With startup enabled, reboot the phone and verify automatic service/socket recovery without opening the UI. Keep the optional root watchdog disabled for the normal-path test; test it separately only if chosen.
9. Rotate device and caller credentials; verify old tokens fail while existing jobs retain their IDs and statuses.

Record real outcomes in `docs/validation.md` as they are verified. A build, mock callback or protocol test is not evidence of carrier delivery.

For a disposable Android test handset, `./gradlew :app:connectedDebugAndroidTest` runs four additional SQLite persistence tests (duplicates/crash recovery, multipart callbacks/revision ACKs, received-job resumption and bounded logs). The tests use isolated database filenames and never invoke `SmsManager`. Android's Gradle test tooling can uninstall the target APK afterward; **do not run this command on a provisioned production relay with a live ledger**. Reinstall/provision the test app after completion.
