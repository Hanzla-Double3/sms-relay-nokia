# Deployment and handset operation

## Local development

Install Python 3.11+, uv, a complete JDK 21, ADB, and Android SDK platform 35/build tools 36.0.0. AGP 9.1.0 uses built-in Kotlin with Gradle 9.3.1; the wrapper and distribution checksum are included. A JRE or stripped IDE runtime without `jlink` cannot build Android's JDK image. See [AGP compatibility](https://developer.android.com/build/releases/about-agp).

From the root:

```sh
uv sync --project gateway --extra test --locked
python scripts/provision.py --recipient +YOUR_AUTHORIZED_NUMBER
uv run --project gateway uvicorn relay.main:app --env-file .local/gateway.env \
  --host 127.0.0.1 --port 8080 --workers 1 --ws-max-size 16384 --no-access-log
```

The root `.env` is also loaded if present. Explicit environment/`--env-file` settings override it. `provision.py` refuses to overwrite credentials. Both credentials and test database are gitignored under `.local/`; keep that directory private. Read device credentials locally to configure the handset; do not paste them into broad logs or screenshots.

`adb reverse tcp:8080 tcp:8080` allows the debug app to reach the host at `ws://127.0.0.1:8080/ws/device` while USB is connected. The production app permits WSS only and does not require USB. Bind a cleartext development server to loopback, never a public interface.

## Environment

Copy `.env.example` and replace credential hashes; placeholder hashes deliberately fail validation.

| Variable | Default / meaning |
|---|---|
| `RELAY_DATABASE` | `data/relay.sqlite3`, persistent private SQLite path |
| `RELAY_CALLERS_JSON` | Map caller name to `{token_sha256,devices:[ids],admin:false}` |
| `RELAY_DEVICES_JSON` | Map device ID to SHA256 of its separate random raw token |
| `RELAY_DEFAULT_DEVICE` | `nokia-01`; callers must be scoped to the selected device |
| `RELAY_ALLOW_INSECURE_LOCAL` | `false`; development only |
| `RELAY_RECIPIENT_ALLOWLIST` | JSON array; empty allows all otherwise authorized recipients |
| `RELAY_BULK_PENDING_LIMIT` | 10,000 unfinished messages per caller, including bulk backlog |
| `RELAY_MAX_INFLIGHT` | 1 outstanding dispatch/modem confirmation per device |
| `RELAY_QUEUE_LIMIT` | 100 outstanding jobs per device |
| `RELAY_RATE_PER_MINUTE` | 10 new jobs per caller, rolling minute, persisted across restarts |
| `RELAY_MIN_SEND_INTERVAL` | 5 seconds between dispatches per device; phone also spaces submissions |
| `RELAY_HEARTBEAT_TIMEOUT` | 75 seconds |
| `RELAY_REDISPATCH_SECONDS` | 30 seconds, only jobs without durable phone acknowledgement |
| `RELAY_RECONCILIATION_SECONDS` | 300 seconds; acknowledged jobs without a callback become unknown |
| `RELAY_RETENTION_DAYS` | 30 days for queued payload expiry/old audit details |
| `RELAY_MAX_FRAME_BYTES` | 16384; align Uvicorn's `--ws-max-size` |
| `RELAY_DOMAIN` | Public DNS hostname, needed by Docker/Caddy deployment |

Caller/device IDs use `[A-Za-z0-9_-]`, at most 64 characters. Generate random tokens with at least 32 bytes of entropy, store only their SHA256 hashes on Server A, and distribute different credentials to each calling application. The operator token has admin registry access but can read only its own submitted message statuses. Device credentials cannot use the HTTP caller API.

## VPS with Docker and Caddy

Set DNS to the VPS, allow inbound TCP 80/443, and provide Docker Compose. Generate production config in a new private directory:

```sh
python scripts/provision.py --production --output .local/production --recipient +YOUR_AUTHORIZED_NUMBER
cp .local/production/gateway.env .env
chmod 600 .env
# Append RELAY_DOMAIN=relay.your-domain.example to .env using your editor.
docker compose up --build -d
```

The compose environment overrides the database path to `/app/data/relay.sqlite3` and forces TLS. Runtime Python dependencies are installed from the hash-verified `gateway/requirements.lock`, exported from `uv.lock`. Refresh it after dependency changes with `uv export --project gateway --locked --no-dev --no-emit-project --format requirements-txt -o gateway/requirements.lock`.

Named volumes preserve SQLite and Caddy certificates across restarts. The gateway runs as an unprivileged user and is reachable only on the internal Docker network; only Caddy publishes ports. Caddy automatically obtains a valid TLS certificate and proxies WebSockets. Do not publish the gateway's cleartext container port.

The supplied container trusts forwarded headers because only its private reverse proxy should reach it. In any other topology, restrict Uvicorn `--forwarded-allow-ips` to your actual proxy IP, strip incoming forwarded headers at the proxy, and firewall direct backend access. For a host service, bind `127.0.0.1`, use one worker, and let the local HTTPS proxy supply the trusted protocol header.

Do **not** run multiple Uvicorn workers or two independent gateways against the same queue. V1 keeps socket ownership in one process while messages remain durable in SQLite. Multi-process support requires a durable broker and dispatch ownership leases. Application stdout uses IDs/machine codes, not text/phone numbers. Disable access logging as shown; configure your proxy logs so they omit Authorization headers, payloads and full request bodies. Container logs rotate at 3 × 10 MiB.

Back up SQLite with its online backup API, not by copying only the live main database while WAL writes are active. Keep backups encrypted/access-limited and age them out. Credential hashes and local raw provisioning credentials should have separate private backups. Do not store partition dumps or credentials in Git. Restoring a server backup must not be combined with clearing the handset ledger.

## Handset setup

Build/install the debug APK as in the README. On the Nokia:

1. Configure the WSS URL, registered ID and raw device token. Provisioning encrypts the token using a non-exportable Android Keystore AES-GCM key. Backups/device transfers are disabled.
2. Choose SMS subscription `-1` for the configured Android default/sole active SIM. If multiple SIMs have no valid default, the app reports `SELECT_SIM`; enter the intended **subscription ID**, not slot index. Removing that SIM makes the device unhealthy.
3. Tap Start and allow SEND_SMS and READ_PHONE_STATE. Android 13+ also requests notification permission. Denied SMS/SIM-selection permission blocks readiness and dispatch.
4. In Settings → Apps → FAY SMS Relay → Battery → Battery optimisation, choose **Don't optimise**. The Battery button opens that settings list. Keep the phone powered and verify Wi-Fi reconnects unattended.
5. Leave startup enabled for Android 11 boot recovery. Stop disables persistent startup. Start must be used at least once after installation or an Android force-stop; force-stop intentionally blocks boot receivers until user launch.
6. Screen awake is off by default and applies only to the visible Activity. Closing the UI does not stop the foreground service. Pause log and brightness affect only the display.

The Android 11 boot receiver starts the foreground service independently of the UI. On Android 14+ the service declares `remoteMessaging` and its permission; newer Android/OEM background restrictions may still require a user startup path. This deployment is validated primarily for the supplied API 30 Nokia, not every newer OEM. See [foreground service rules](https://developer.android.com/develop/background-work/services/fgs/service-types).

An active notification says `SMS Relay • Connected/Disconnected` with the current connection status. The UI reports SIM/permission/registration health separately from the WebSocket state. No SIM is a normal unhealthy device state; it must never produce a false sent result.

### Release APK and signing

```sh
cd android
./gradlew :app:assembleRelease
# Output: app/build/outputs/apk/release/app-release-unsigned.apk
```

Create a private signing key outside the repository with `keytool -genkeypair`, then use SDK `zipalign` and `apksigner`:

```sh
zipalign -p -f 4 app/build/outputs/apk/release/app-release-unsigned.apk /private/path/relay-aligned.apk
apksigner sign --ks /private/path/relay-release.jks --out /private/path/relay-release.apk /private/path/relay-aligned.apk
apksigner verify --verbose /private/path/relay-release.apk
```

Let `apksigner` prompt for passwords; don't commit or put them on the command line. Keep the same signing key for upgrades. A release-signed APK cannot update a debug-signed installation without removing it; **do not uninstall a working relay with potentially sent/outstanding jobs**. Drain/reconcile first and preserve the ledger. Release configuration rejects WS even on loopback.

### Optional Magisk watchdog

Not installed or enabled automatically. Normal SMS operation never invokes `su`. If Android 11 still kills the service despite battery exemption, copy `scripts/root-watchdog.sh` to `/data/adb/service.d/sms-relay.sh`, set owner root and mode `0755`, and explicitly create `/data/adb/sms-relay-watchdog.enabled`. Magisk runs the script at boot. It waits for boot completion, checks for a foreground service every minute, and attempts `am start-foreground-service` if missing. The app's enabled setting still governs startup.

Disable the watchdog by removing the opt-in file; remove the script to uninstall it. The next loop sees the removed marker. It performs no package disabling, SELinux changes or OS/modem modifications. Root does not make a process unkillable. On restricted Android versions a user may still need to launch/start the app.

## Credential rotation and recovery review

1. Generate a fresh device token privately and calculate its SHA256 hash. Update its `RELAY_DEVICES_JSON` entry, then restart the single gateway to invalidate its old authenticated socket.
2. Update the token in the phone's Configure dialog (blank keeps the existing token), save, and reconnect. Jobs stay in the same phone ledger/device ID and are reconciled.
3. Rotate callers independently by changing their hash/config and restarting, then updating their application's Bearer token. Remove the old raw credential from private provisioning files after verifying the new credential.
4. Never fix connectivity by clearing app data or resubmitting old messages with new IDs. Review `unknown` using callback history/carrier evidence first. Deliberately retry only when you're certain the original wasn't sent or a duplicate is acceptable, using a new idempotency key and explicit operational approval.

Optional-package cleanup is described separately in [phone cleanup](phone-cleanup.md). Core telephony, SIM/IMS, networking, permission controller, Keystore, SystemUI and Magisk must remain intact.
