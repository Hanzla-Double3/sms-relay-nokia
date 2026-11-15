# Nokia SMS Relay: implementation brief for Codex

**Status:** Ready for implementation  
**Owner:** Han  
**Target:** Dedicated Android handset acting as a self-healing SMS gateway, connected *outbound* to a central server.

## 1. Confirmed hardware and existing setup

These facts were verified during device preparation; do not redo rooting or unlock steps.

| Item | Confirmed value |
|---|---|
| Device | Nokia 2.2, model **TA-1188** |
| Device codename | `WSP_sprout` |
| Chipset | MediaTek MT6761 family (MTKClient detected it) |
| OS | Stock Android One, **Android 11** |
| Build fingerprint | `Nokia/Wasp_00WW/WSP_sprout:11/RP1A.200720.011/00WW_3_38H:user/release-keys` |
| Previously active A/B slot | `_b` (verify again if firmware/slots change) |
| Bootloader | Unlocked; Orange State displayed at boot |
| Root | **Working Magisk**; `adb shell su -c id` returned `uid=0(root) gid=0(root) groups=0(root) context=u:r:magisk:s0` |
| Host development machine | Arch Linux; ADB works |
| Fastboot caveat | `fastboot devices` enumerated the handset, but `getvar` commands timed out. MTKClient BROM communication worked. No further flashing is required for this project. |
| Stock firmware/modem | Preserved. No custom ROM was installed. |
| Backups | A backup procedure for key partitions was performed before unlocking; **verify that backup files are still present locally before any future device modification**. Never commit dumps to source control. |

The exact SIM operator, assigned phone number, Server A hostname, hosting provider, and credentials have **not** been fixed. Expose them as configuration, not hardcoded assumptions.

## 2. Goal and non-goals

Turn the handset into a small, dedicated GSM/SMS appliance. Other applications (Server B, Server C, Tibbsync, etc.) submit SMS jobs to **Server A** through an authenticated HTTPS API. The Nokia maintains a persistent outbound **WSS (WebSocket)** connection to Server A, authenticates as a device, receives jobs, sends SMS via the Android telephony stack, and reports status. Server A never needs to connect inbound to the Nokia. This works across changing phone IPs, Wi-Fi/mobile-data transitions, and carrier NAT.

The user also wants a full-screen **terminal-style monitoring interface** on the phone: connection state, scrolling event log, message status, queue and sent/failed counts, SIM/network health, uptime, battery/charging status. Include a user-controlled *Keep screen awake* option; default to a sensible display-off state for unattended operation.

**V1 non-goals:** custom ROM, direct MTK modem/RIL access, Play Store distribution, arbitrary shell-command execution from Server A, bulk marketing campaigns, multi-device scheduling UI, and inbound SMS forwarding. Design the protocol so inbound SMS can be added later, but do not request `RECEIVE_SMS` unless implementing that feature.

## 3. Proposed topology

```text
Server B / Server C / Tibbsync
        |
        | authenticated HTTPS POST /v1/messages
        v
+-------------------------------+
| Server A: SMS gateway API     |
| - authenticate callers        |
| - durable job queue / DB      |
| - device registry             |
| - WebSocket endpoint          |
| - audit / status API          |
+-------------------------------+
        ^
        | persistent outbound WSS
        | device initiates + reconnects
        |
+-------------------------------+
| Nokia 2.2 / Android 11        |
| - foreground RelayService     |
| - reconnect / heartbeat       |
| - persistent local job ledger |
| - Android SmsManager          |
| - sent/delivery callbacks     |
| - terminal-style Activity     |
| - optional root watchdog      |
+-------------------------------+
        |
        v
   SIM / GSM network -> recipient
```

## 4. Deliverables

Create a monorepo, or use the existing repository if supplied:

```text
sms-relay/
  android/               # native Kotlin Android app, Android 11-compatible
  gateway/               # FastAPI Server A
  docs/protocol.md       # JSON protocol, transitions, and recovery rules
  docs/deployment.md     # local dev + VPS + handset setup
  README.md
  .env.example           # placeholder config only; no secrets
```

Prioritize a functioning end-to-end MVP before visual polish. Include development tests and commands to run them. Codex should not assume the actual phone is connected to its execution environment.

## 5. Android application

**Preferred stack:** Native Kotlin. Android 11 is API 30. Use a foreground `Service` owning the network client, `SmsManager`, local persistence (Room or SQLite), and status callbacks. The UI should be a separate Activity observing service state. Keep the Android stock telephony stack intact.

### 5.1 Lifecycle and recovery

- Request runtime `SEND_SMS` permission and declare `INTERNET`, foreground-service permission, and boot-receiver permission as appropriate. The APK will be sideloaded. Use explicit exported settings compatible with the chosen target SDK. Avoid requesting unnecessary permissions.
- `RelayService` starts as an actual foreground service promptly, with a persistent notification (`SMS Relay • Connected/Disconnected`). Use a valid service type and start restrictions for the target SDK; provide an appropriate user-enabled startup path.
- A `BOOT_COMPLETED` receiver attempts to restore the relay after reboot in accordance with Android rules. It must not rely on the Activity being open.
- WebSocket reconnect uses exponential backoff with jitter, approximately 1 -> 2 -> 4 -> 8 -> 16 -> 30-60 seconds; reset after a stable connection. Detect half-open sockets using ping/pong and a stale-heartbeat deadline.
- On reconnection, authenticate and reconcile pending work with Server A. Do **not** assume a dropped WebSocket implies SMS delivery failed.
- Provide battery-optimization exemption instructions. Root is available, but the normal application must work without using `su` for each SMS.
- Optional, separate root/Magisk watchdog via `/data/adb/service.d/` can check the Android service and attempt supported recovery. Make it opt-in and document it. Do not disable core system packages or turn off SELinux.
- Keep display-awake behavior within the visible Activity, e.g. `FLAG_KEEP_SCREEN_ON`; this is independent of the service. Terminal UI supports immersive mode and brightness adjustment, with a toggle for always-on display (not required for relay operation).

### 5.2 SMS execution

- Use Android `SmsManager` with the appropriate/default SIM subscription; handle absent SIM or multiple SIM subscriptions explicitly.
- For text requiring multiple segments, call `divideMessage` and `sendMultipartTextMessage`; use unique `PendingIntent`s / request codes and correct mutable/immutable flags for the targeted Android version. Associate callbacks to the job ID and multipart part index.
- Distinguish **received by phone**, **submitted to Android modem**, **sent callback success**, and optional **delivery callback**. Delivery receipts depend on carrier support and are not guaranteed.
- If the user denies `SEND_SMS`, mark device unhealthy and do not take jobs until granted.
- Persist each incoming job ID and its state **before** invoking `SmsManager`. Reject duplicates by ID and return current known state.
- Important limitation: SMS submission and local SQLite commit cannot form one atomic transaction. On a crash at the boundary, whether the carrier accepted a send may be unknowable. Represent `UNKNOWN/NEEDS_RECONCILIATION`; **never automatically resend an ambiguous potentially-sent SMS**. This favors avoiding duplicate customer messages. Document this tradeoff.
- Mask recipient numbers in on-screen logs, and avoid logging full OTPs or private message bodies. Store sensitive details only as long as necessary.

### 5.3 Phone UI: terminal appliance

A dark, monospace, compact status screen. Example layout (illustrative values only):

```text
FAY//SMS RELAY                         v0.1.0
---------------------------------------------
DEVICE    nokia-01              [CONNECTED]
SERVER    wss://relay.example.com/ws/device
SIM       READY                 SIGNAL -- dBm
UPTIME    02h 14m               BATTERY 82%
QUEUE     002                   LAST PING 28ms
---------------------------------------------
19:42:18  [RECV] sms_a382
19:42:19  [SEND] +92300*****67 -> modem
19:42:20  [SENT] sms_a382
19:42:26  [DLV ] sms_a382
19:44:01  [WS  ] heartbeat ok
---------------------------------------------
TODAY       SENT 024  FAILED 001  QUEUED 002
```

Features: bounded scrolling log backed by local DB, auto-scroll/pause, reconnection state, explicit permission/SIM warnings, a non-destructive reconnect control, startup health indicator, optional always-on-display toggle. Never make UI visibility necessary for background sending.

## 6. Server A: gateway

**Preferred stack:** FastAPI with WebSocket support, a persistent database and configurable per-device API credentials. For V1 a single gateway process is acceptable; if multiple workers are later introduced, use Redis Streams / another durable broker so the worker holding the socket receives commands. An in-memory `connections` dictionary alone is not a durable message queue.

### 6.1 HTTPS endpoints

| Endpoint | Purpose |
|---|---|
| `POST /v1/messages` | An authenticated caller submits `{to, text, device_id?}`; validate E.164 number, authorization, limits; respond `202` with stable message ID and `queued` status. Accept optional idempotency key. |
| `GET /v1/messages/{id}` | Caller-scoped message status, timestamps, and sanitized errors. |
| `GET /v1/devices` | Admin-only registered devices with online/offline and heartbeat. |
| `GET /health` | Server readiness/liveness, without leaking credentials. |
| `WS /ws/device` | Device-authenticated, bidirectional WebSocket. |

Use separate **server-caller credentials** and **per-device credentials**. Secrets must not be embedded in source code, logs, or the APK committed to the repository. Initial device provisioning may use a secure local configuration flow or a sideloaded, gitignored config. TLS/WSS required for deployment.

### 6.2 Example protocol (revise as necessary; document final schema)

Client-to-server on connect:

```json
{"type":"hello","device_id":"nokia-01","token":"<device-secret>","protocol":1}
```

Server-to-device after authentication:

```json
{"type":"hello_ack","protocol":1,"server_time":"<ISO-8601>"}
```

Job dispatch:

```json
{"type":"send_sms","id":"sms_01J...","to":"+923001234567","text":"Your report is ready.","attempt":1}
```

Device acknowledgement after durable local storage:

```json
{"type":"sms_status","id":"sms_01J...","status":"phone_received"}
```

Subsequent events:

```json
{"type":"sms_status","id":"sms_01J...","status":"submitted_to_modem"}
{"type":"sms_status","id":"sms_01J...","status":"sent"}
{"type":"sms_status","id":"sms_01J...","status":"delivered"}
```

Errors carry machine-readable codes, not sensitive message bodies:

```json
{"type":"sms_status","id":"sms_01J...","status":"failed","error_code":"NO_SERVICE"}
```

Heartbeat includes connection health and optional non-sensitive telemetry such as charging, battery percent, SIM-ready and app version. Authenticate before allowing any dispatch or telemetry updates.

### 6.3 Job state model

```text
QUEUED -> DISPATCHED -> PHONE_RECEIVED -> SUBMITTED_TO_MODEM -> SENT -> DELIVERED (optional)
                                |                 |             |
                                +-----------------+-------------+-> FAILED (on definite errors)
                                \-> UNKNOWN / NEEDS_RECONCILIATION (ambiguous outcome)
```

These states are not all guaranteed to arrive in order over reconnects. Store monotonic/reconciled status with timestamps; do not regress `sent` to `dispatched`. Jobs that were never acknowledged by the phone can be redelivered with the *same* ID. Jobs with ambiguous modem submission must not be automatically retried just because a heartbeat or status callback was lost. Maintain an audit trail.

## 7. Safety, abuse prevention, and reliability requirements

- Gateway credentials per calling application; scoped permissions, rate limits, per-device queue size limit, and an optional recipient allowlist for initial testing.
- Explicitly intended for authorized operational/customer notification traffic. Respect recipient consent and applicable operator bulk messaging rules. Start with low send volume; SIM plans may restrict automated traffic.
- Do not allow WebSocket messages to execute arbitrary commands on the phone. Allow only a small schema of predefined operations.
- Validate number, text length, body encoding, idempotency key, and payload size; don't leak message text or phone numbers into broad logs.
- Offline Nokia: queue on Server A; expose offline status. Do not report `sent` until Android's send callback confirms it.
- Use a persistent queue/database and local phone ledger to recover from server restart, device reboot, Wi-Fi change, socket drop, duplicate dispatch, and callback delay.
- Build a bounded log/history retention policy and basic device authentication rotation procedure.
- If the system cannot know whether an SMS was sent, surface `UNKNOWN` for explicit review rather than claiming exactly-once semantics.
- Add structured logs and a device-online alert on heartbeat expiry when convenient. Never claim that root makes a process unkillable.

## 8. Implementation phases for Codex

1. **Scaffold and protocol:** Android Kotlin project, FastAPI project, protocol document, env examples, message DB schema, CI/unit test scaffolding.
2. **Server A MVP:** Authenticated submit/status endpoints; durable queue; one authenticated WebSocket device; message dispatch; reconnect reconciliation.
3. **Android MVP:** Foreground RelayService, configuration, WSS auth/reconnect, local ledger, runtime SEND_SMS permission, actual single and multipart sends, sent/delivery callbacks.
4. **Terminal UI:** Full-screen terminal aesthetic, health, events, masked numbers, sent/failed/queued counters, reconnect control, screen-awake toggle.
5. **Boot and hardening:** Boot receiver, battery-exemption instructions, optional Magisk watchdog, auth/key rotation, limits, diagnostics, end-to-end tests, README/deployment guide.

## 9. Acceptance tests

- Server B calls `POST /v1/messages`; Nokia receives job over outbound WSS, sends test SMS to an explicitly authorized number, and Server A displays actual callback-derived status.
- Nokia has no static/public IP and requires no inbound open port.
- UI can be closed or screen locked without stopping relay service; foreground notification remains visible.
- Restart Wi-Fi, switch network, reboot the server: phone reconnects and queued, undispatched jobs resume.
- Re-dispatch an existing message ID: phone does not intentionally send it twice.
- Simulate connection loss after SMS submission: system reports reconcilable status / UNKNOWN rather than blindly resending.
- Disable SIM or deny SMS permission: no false `sent` result; an intelligible error appears on phone and server.
- Multi-segment message yields correct per-part callbacks and an aggregate status.
- Reboot phone: relay recovers through allowed Android boot flow or documented opt-in watchdog without opening the UI manually.
- No secrets in git; requests from unauthorized callers/devices rejected; malformed payloads rejected.

## 10. Suggested first Codex prompt

> Implement the project described in `Nokia_SMS_Relay_Codex_Spec.md`. The Nokia 2.2 TA-1188 is already rooted with Magisk and runs stock Android 11; do not attempt rooting, flashing, or ROM changes. Build an Android Kotlin foreground-service SMS relay plus FastAPI Server A with an outbound authenticated WSS link, durable queue and local idempotency ledger. Begin by creating the repository structure, protocol/schema and functioning smallest end-to-end path, then build the terminal-style monitoring UI. Use configurable credentials and provide explicit setup, testing, and APK build instructions. Do not silently claim guaranteed exactly-once sending.

---

**Decisions to fill in during implementation:** actual Server A domain, preferred deployment database, Nokia's SIM subscription/number, whether incoming SMS should be supported in V2, whether the screen-awake toggle defaults off or on, and whether Server A will serve other devices beyond `nokia-01`.
