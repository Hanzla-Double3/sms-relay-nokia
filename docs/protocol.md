# Protocol v1

UTF-8 JSON objects over outbound `/ws/device` WebSocket. Production requires HTTPS/WSS with normal certificate/hostname verification. No remote shell commands exist. Frames over 16 KiB or malformed/unknown operations close the socket with `1008`. Uvicorn also limits frame size. Configure credentials as SHA256 hashes on the server; provision the raw token privately on the phone.

## Authentication and connection ownership

Within 10 seconds after opening, the device sends:

```json
{"type":"hello","device_id":"nokia-01","token":"DEVICE_CREDENTIAL","protocol":1}
```

The server checks that device's credential before accepting statuses, telemetry or dispatching jobs:

```json
{"type":"hello_ack","protocol":1,"server_time":"2026-10-01T12:00:00+00:00","send_interval_ms":5000,"max_inflight":10}
```

Only one live socket per device is allowed. A second connection gets `1013`; old connections expire after 75 seconds without an application heartbeat. Credentials for HTTP callers do not authenticate devices.

## Health and keepalive

Immediately after authentication and every 20 seconds:

```json
{"type":"heartbeat","ready":false,"battery":82,"charging":true,"sim_ready":false,"permission":true,"health_code":"NO_SIM","app_version":"0.1.0"}
```

Fields are required; booleans are health flags, battery is 0–100 and health_code is a bounded uppercase machine code. `ready`, `sim_ready` and `permission` must all be true for dispatch. Phone readiness requires permission, an unambiguous selected subscription, a ready SIM and network registration. A device with missing permission/SIM remains online but unhealthy; its jobs remain queued. The app requests `READ_PHONE_STATE` for active subscription selection/health, not phone numbers. No location or incoming SMS permissions are requested.

```json
{"type":"heartbeat_ack","server_time":"2026-10-01T12:00:00+00:00"}
```

OkHttp additionally uses WebSocket ping/pong every 20 seconds. The app drops/reconnects sockets without a hello/heartbeat ACK for 75 seconds. Retry uses exponential jittered delays (base 1,2,4,8,16,32,60 seconds; ±25%, maximum 75 seconds), reset after 60 seconds stable. UI reconnect only replaces the socket; it never resubmits SMS.

## Dispatch and durable statuses

The server commits `dispatched` before writing the socket:

```json
{"type":"send_sms","id":"sms_0123456789abcdef0123456789abcdef","to":"+923001234567","text":"Your report is ready.","attempt":1}
```

IDs are `sms_` plus 32 lowercase hex characters. Numbers must be E.164 (8–15 digits, starting nonzero); text is nonblank, max 1600 Unicode code points, without surrogates or control characters other than CR/LF/TAB. The handset also limits messages to 16 segments. Phone ledger insertion is unique by ID and committed before acknowledgement. Existing IDs return their stored state without intentionally sending again.

```json
{"type":"sms_status","id":"sms_0123456789abcdef0123456789abcdef","status":"phone_received","revision":1}
{"type":"sms_status","id":"sms_0123456789abcdef0123456789abcdef","status":"submitted_to_modem","revision":2}
{"type":"sms_status","id":"sms_0123456789abcdef0123456789abcdef","status":"sent","revision":3}
```

Optional failure information is `{...,"error_code":"NO_SERVICE"}`. States accepted from devices are `phone_received`, `submitted_to_modem`, `sent`, `delivered`, `failed`, `unknown`. The server associates every report with the authenticated device, so another device cannot mutate it.

```json
{"type":"status_ack","id":"sms_0123456789abcdef0123456789abcdef","revision":3,"accepted":true}
```

A local status remains dirty until its exact revision is ACKed. ACKs for older revisions cannot clear newer updates. On reconnect all ledger states are replayed in batches of 100; dirty states are resent until ACKed. Intermediate states may be coalesced if callbacks arrive before reconnect. `accepted:false` means the server no longer recognizes/owns the ID; the app retires that outbox entry while preserving the local duplicate guard.

## Reconciliation and recovery

After `hello_ack`, the server sends outstanding acknowledged IDs in batches of up to 100:

```json
{"type":"reconcile","ids":["sms_0123456789abcdef0123456789abcdef"]}
```

The phone reports the state it has. If an acknowledged ID is absent, it persists/reports `unknown` with `LEDGER_MISSING`. Replaying the local outbox also resolves statuses from jobs whose ACK was lost before a server crash.

| Situation | Recovery |
|---|---|
| Server restart before dispatch | Queued row remains; dispatch once healthy. |
| Socket write or phone-received ACK lost | Only queued/dispatched jobs are redelivered, same ID, after 30 seconds. Local unique ID prevents intentional duplicates. |
| Phone stored received job but never guarded submission | Local `phone_received` can resume when healthy, including after reboot, within its five-minute execution window. |
| Crash after committing submission guard | Local `submitted_to_modem` becomes `unknown/PROCESS_RESTART`; do not resend. |
| Modem callback absent for 5 minutes | Local submission/server acknowledged job becomes `unknown/CALLBACK_TIMEOUT`; do not resend. |
| Late sent/delivery callback | Can resolve `unknown` to a confirmed outcome. |
| Phone ledger missing an acknowledged job | `unknown/LEDGER_MISSING`; do not redeliver. |
| Mixed multipart success/failure or pending parts after failure | `unknown/PARTIAL_OR_PENDING`; no whole-message retry. |

State progression is monotonic:

`queued → dispatched → phone_received → submitted_to_modem → sent → delivered`

`failed` means a definite rejection before send or every part reported failure. `unknown` means potentially sent or partially sent. `sent` cannot regress to earlier states, failed or unknown; `delivered` is strongest proof, even if its callback arrived first. Unknown may resolve to sent/delivered/definite failed. Failure does not regress to earlier states. Duplicate status reports do not create duplicate audit rows. No state triggers automatic retry of a potentially submitted SMS.

A local received job that has not reached its submission guard within five minutes fails with `NOT_SUBMITTED_TIMEOUT`. It is definitely unsubmitted; this bounds sensitive local payload retention and prevents a long-blocked phone from later sending an old job that an operator has already reviewed. Server queued jobs retain their separate 30-day expiry.

The submission guard is written **before** `SmsManager`. This avoids intentional duplicate sends, but a crash between that guard and the actual call may sacrifice a message by treating it as unknown. There is no atomic modem/SQLite transaction and no exactly-once guarantee. Delivery reports depend on the carrier and may never arrive; `sent` remains a successful terminal result without delivery proof. Failed/unknown jobs require explicit investigation; there is no automatic resubmit endpoint.

## Privacy and retention

Server scrubs recipient/text when an outcome is sent/delivered/failed/unknown. Queued jobs expire after 30 days by default; expired dispatches become unknown rather than retry. Changed-state audit rows are retained for the configured period with the latest row preserved. Minimal ID/idempotency tombstones remain indefinitely to keep old keys/dispatches from causing new sends.

Phone scrubs recipient/text after the modem call or terminal/unknown transition. Logs have no message bodies and mask numbers, are capped at 500 entries and aged after one hour; the UI displays the latest 100. Ledger IDs, per-part outcomes and latest state remain to reject late duplicate dispatches. SQLite secure-delete is enabled, but WAL snapshots, encrypted host/phone backups and stock Android's SMS Provider need their own retention controls. Android normally records sent SMS in its stock provider; this app does not request broad SMS read/delete permissions to change that history.


## Configurable send pacing (Android v0.5+)

The default/production confirmation window is now **one** outstanding message per device. Bulk templates and `device_id: "auto"` are processed entirely by Server A; see [bulk API](bulk-api.md). Larger configurable windows remain available for controlled tests.

The authenticated `hello_ack` advertises `send_interval_ms` (1,000–60,000) and `max_inflight` (1–10). The handset defaults to 5,000 ms / 10 if connecting to an older server, and rejects values outside its safe bounds. Set `RELAY_MIN_SEND_INTERVAL=1`, `RELAY_RATE_PER_MINUTE=60` and `RELAY_MAX_INFLIGHT=1` for sequential outcomes, or a larger window only for explicitly enabled pipelining. A one-second interval is an upper-bound target of one new message submission per second. API acceptance limits and send pacing are separate; old handset versions retain their hardcoded five-second spacing.

The phone uses one serialized worker to write each durable submission guard and call SmsManager. Several IDs can await independent modem callbacks at once; the next submission does not wait for the preceding callback. A scheduled task runs only while jobs are pending, so the normal five-second idle timer, minute battery sampling and 1 FPS display remain unchanged. A fresh SIM/network check precedes every send. A full local modem window waits for callbacks/maintenance; callbacks immediately reconsider queued work. Disconnect and Stop cancel scheduled submission tasks.

The server also bounds dispatched/phone-received/submitted jobs per device, holding additional messages queued. A retransmission of an unacknowledged dispatched ID reuses its existing window slot. Slots close on confirmed/failed/unknown outcomes; ambiguity never resends the original ID. Delivery receipts are not required to free a sent slot. This target is measured in whole message submissions: multipart messages may consume several carrier SMS segments. Firmware/carrier behavior can lower actual throughput or reject a burst; there is no promise of one delivered SMS per second.
