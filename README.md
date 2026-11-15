# FAY // Nokia SMS Relay

Self-hosted SMS relay: a durable FastAPI gateway and a native Kotlin Android appliance. Licensed under [MIT](LICENSE). See [architecture](docs/architecture.md), [API reference](docs/api.md), [contributing](CONTRIBUTING.md), and [security policy](SECURITY.md).

FastAPI Server A + native Kotlin Android relay for the rooted Nokia 2.2 on stock Android 11. Root is **optional**; sending uses Android `SmsManager`. No rooting, flashing, ROM changes, inbound phone ports, or incoming SMS forwarding are involved.

Callers submit through HTTPS. Server A persists jobs in SQLite; the phone opens an outbound WSS connection, commits each job to its local ledger, and reports Android sent/delivery callbacks. A modem submission is **not** a sent confirmation. Ambiguous outcomes become `unknown` and are never automatically resent.

## Quick start

From the repository root, install Python 3.11+ and [uv](https://docs.astral.sh/uv/), then:

```sh
uv sync --project gateway --extra test --locked
python scripts/provision.py --recipient +YOUR_AUTHORIZED_NUMBER
uv run --project gateway uvicorn relay.main:app --env-file .local/gateway.env \
  --host 127.0.0.1 --port 8080 --workers 1 --ws-max-size 16384 --no-access-log
```

`provision.py` creates separate random caller, administrator and device tokens in `.local/credentials.json` (permissions `0600`) and a gitignored environment file containing SHA256 hashes. Replace the number with an actual authorized E.164 recipient. Omit `--recipient` only for disconnected/no-SIM development; an empty allowlist permits any otherwise authorized recipient. Never put raw credentials in Git or the APK.

Build with a **complete JDK 21** (including `jlink`) and Android SDK platform 35/build tools 36.0.0:

```sh
export JAVA_HOME=/path/to/jdk-21
export ANDROID_HOME=/path/to/Android/Sdk
cd android
./gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb reverse tcp:8080 tcp:8080
adb shell am start -n com.fay.smsrelay/.MainActivity
```

On the phone, choose **Configure**, enter `ws://127.0.0.1:8080/ws/device`, device ID `nokia-01`, and the device token from the private credentials file. Leave subscription `-1` for default/sole SIM. Tap **Start**, grant SMS and phone-state permissions, and exempt the app from battery optimization. With no SIM, the app connects, reports `NO_SIM`, and leaves jobs on Server A. Screen awake defaults off.

Only debug APKs permit cleartext, and only to loopback for `adb reverse`. Release APKs enforce WSS. For VPS deployment and release signing see [deployment instructions](docs/deployment.md).

## Submit and inspect

Use the `server-b` token as a Bearer credential. Tokens below are placeholders, not real credentials:

```sh
curl -X POST https://relay.example.com/v1/messages \
  -H 'Authorization: Bearer YOUR_CALLER_TOKEN' \
  -H 'Idempotency-Key: report-2026-001' \
  -H 'Content-Type: application/json' \
  -d '{"to":"+YOUR_AUTHORIZED_NUMBER","text":"Your report is ready."}'

curl https://relay.example.com/v1/messages/sms_RETURNED_ID \
  -H 'Authorization: Bearer YOUR_CALLER_TOKEN'
```

A newly accepted job returns `202` with `{id,status:"queued"}`. Reusing the same caller/idempotency key and payload returns the existing ID/current status; changing its payload returns `409`. Message status is caller-scoped. `GET /v1/devices` requires an administrator credential. Error responses and status endpoints omit message bodies and recipient numbers.

## Bulk templates and automatic routing

`POST /v1/messages/bulk` accepts `{"template":"Hi {name}","users":[{"phone":"+923001234567","name":"Ali"}],"device_id":"auto"}` with a caller Bearer token. Server A persists the batch, hashes recipients to available authorized devices, and feeds individual jobs to the phone. Use `GET /v1/batches/{id}` for progress and reuse an `Idempotency-Key` on retries. See [bulk API examples and limits](docs/bulk-api.md). Production dispatches one outstanding message per device; the existing phone does not need an update for this backend feature.

## Small Python sender

No additional packages are needed:

```sh
export RELAY_URL=https://relay.example.com/v1/messages
export RELAY_TOKEN=YOUR_CALLER_TOKEN
python scripts/send_sms.py +12025550123 "Hello from Python" --key greeting-001
```

The script uses `RELAY_TOKEN`, or the existing private `.local/credentials.json` caller token when run in this checkout. For a standalone copy, set `RELAY_TOKEN` to the `server-b` caller token; the dashboard password is not an API token. Set `RELAY_URL` or `--url` to your own HTTPS endpoint; there is no built-in live service destination. Redirects are rejected to protect the Bearer token. Use `--device nokia-01` to pin a device; the default is `auto`. It prints the message ID/status and request key. A `queued` response means accepted, not yet sent; inspect the dashboard or status API for confirmation. Reuse the same key, recipient and text after an uncertain request to avoid creating another SMS. Use a new key for an intentionally new message. An empty server recipient allowlist accepts any valid E.164 recipient for an authenticated, device-scoped caller token; rate and queue limits still apply.

## Tests

```sh
uv run --project gateway --extra test --locked pytest gateway/tests -q
cd android
./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleRelease
```

Gateway tests exercise the HTTP/WebSocket protocol, restart recovery, limits, privacy, authorization, unhealthy devices, and callback reconciliation. Kotlin tests exercise state rules, multipart outcomes, crash boundaries, backoff and masking. [The acceptance checklist](docs/testing.md) covers handset tests, including a later authorized carrier SMS test. CI runs both suites and builds the APKs.

## Layout and operating constraints

- `gateway/`: FastAPI app, durable queue/audit, config and tests; Python dependencies pinned in `uv.lock`.
- `android/`: native Activity, foreground Service, local SQLite ledger, callbacks and encrypted provisioning.
- `docs/protocol.md`: wire schema, state and recovery guarantees.
- `docs/deployment.md`: local/VPS, environment, phone setup, signing, rotation and optional watchdog.
- `scripts/root-watchdog.sh`: optional Magisk recovery loop; not installed automatically.

V1 supports multiple registered devices with explicit caller scopes and a configurable default, using **one gateway process**. Do not use multiple Uvicorn workers or simultaneous servers against this SQLite queue. Add a durable broker/ownership leases before scaling across processes. There is no admin sending UI. Automatic routing can reassign undispatched jobs; potentially submitted jobs remain pinned to their device.

Delivery receipts are carrier-dependent. There is no exactly-once claim: SQLite and the modem cannot share a transaction. Preserve the phone ledger and server database; do not clear app data/reinstall after a potentially sent job. A late callback can resolve `unknown`; otherwise investigate before intentionally creating a new send.

## Production dashboard and auto deployment

For your deployment, use `https://YOUR_HOST/admin`, with a private password stored only in the server environment. Its **API Bearer tokens** panel lets you create device-scoped sending tokens and revoke existing ones. New secrets are shown once; use them as `RELAY_TOKEN`. See [production operations](docs/production.md) for the isolated host-proxy deployment, secrets, automatic releases, backups and rollback. Configure the phone with `wss://YOUR_HOST/ws/device`. All hostnames and numbers in examples are placeholders; use your own endpoint and a recipient you are authorized to contact.

## Wall display (Android v0.4)

The home screen runs in landscape with a large local clock/date, authenticated server connection indicator (green online/red offline), cellular signal bars, charging/battery icon and exactly one latest event, with the most recent confirmed send underneath. The battery icon blinks while charging is paused or the phone is unplugged. **More info** opens a separate scrollable screen with Start/Reconnect/Stop, provisioning, battery settings, persistent brightness, screen-awake preference, ledger counts and the latest 100 log events.

Phone event logs expire after one hour, including on idle reads, and retain their 500-row safety cap. The screen holds only one event on the dashboard and at most 100 on the details screen; polling stops while hidden. SMS duplicate guards remain in the durable ledger. Opening the dashboard resumes a previously enabled relay; an explicitly stopped relay stays stopped.


On the rooted Nokia 2.2, **Charge limit** defaults on: charging pauses at 80% or above and resumes at 60% or below. Between the thresholds, the previous charging state is retained, including across app process restarts. The active relay service runs a fixed local root guardian; allow the app's Magisk root request if prompted. More info shows its state and provides an explicit retry button. Turning the limit off or stopping the relay restores normal charging. App process death also restores charging within approximately 15 seconds. No boot module, ROM, voltage/current limit or battery safety setting is changed. Unsupported phones do not write charging controls. The initial installation above 80% pauses immediately; it cannot reduce the battery to 80% instantly.

**Adaptive brightness** in More info uses the Nokia's ambient light sensor, smoothly adjusts the visible app window from 5% to 100%, and stops sensor sampling when hidden. It defaults off; enabling it disables the manual slider, whose saved value returns when adaptive mode is disabled. No system-settings permission is needed.

See the [security audit](docs/security-audit-2026-10-02.md) for findings, fixes, verification and remaining limitations.


**Battery graph** on the dashboard (also in More info) opens a landscape history screen with 1-hour, 6-hour, 24-hour and 7-day windows. The existing relay service takes one battery percentage/charging/plugged-in sample per minute, even while disconnected from the server or the graph is hidden. Samples are saved in a separate private SQLite database, deduplicated by minute and retained for seven days (at most 10,081 readings). No additional background service, network endpoint or permission is added. Sampling pauses when the relay is stopped. Missing minutes appear as gaps rather than fabricated slopes. History survives app updates/restarts; graph refreshes only while visible and follows the same brightness/awake settings. Charging/discharge lines use cyan/mint, with 80% and 60% guides. The graph starts collecting after this update; earlier battery data is not available.


Android v0.4.1 reduces idle work: the home clock and battery blink redraw at 1 FPS while visible; SIM/status/log reads and the relay maintenance timer run every five seconds. Incoming WebSocket events and modem callbacks still process immediately, with fresh SIM health checked before each send and durable submission guards retained. Heartbeats remain every 20 seconds, battery samples every minute and root charging checks every 15 seconds. The graph refreshes once per minute and More info every five seconds; hidden activities stop their refresh loops. Provisioning remains encrypted in preferences/Keystore and is decrypted once per Config instance until its encrypted secret, URL, device or subscription changes; no plaintext token is persisted.

A short same-dashboard handset measurement recorded 20 rendered frames over 20.06 seconds, and app CPU time decreased from 4.43 to 2.59 ticks/second (Android CLK_TCK=100) after the update. This is approximately 42% less app CPU in that sample, not a claimed battery-life improvement; brightness, signal and other system work also affect discharge. The 15 optional packages previously disabled remain disabled; modem, networking, system UI and shared system services were preserved.


Android v0.5.0 supports configurable pipelined sends. For optional one-message-per-second mode, set `RELAY_MIN_SEND_INTERVAL=1`, `RELAY_RATE_PER_MINUTE=60`, `RELAY_MAX_INFLIGHT=1` in the server's private environment and recreate only the relay container. The authenticated server policy controls the handset's spacing and bounded window of unconfirmed sends. Keep interval `5`, rate `10`, and inflight `1` for slower sequential sending. Install Android v0.5.0 or later to use the faster handset pacing; earlier APKs stay at five seconds. See [the protocol](docs/protocol.md) for guards and recovery. Carrier delivery speed is independent of this submission target.

Debugging and remote app updates are documented in [diagnostics](docs/diagnostics.md) and [remote updates](docs/remote-updates.md). App 0.6.0 adds a signed, administrator-requested updater for the rooted Nokia. The existing phone needs one USB upgrade to enable it; future versions can then be requested from the admin console.
