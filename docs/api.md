# HTTP SMS API

Base URL: `https://relay.example.com` (replace with your own domain). Every SMS endpoint requires `Authorization: Bearer YOUR_CALLER_TOKEN`, obtained from your own admin dashboard. The dashboard password and device token cannot replace a caller token. FastAPI publishes the current schema at `/openapi.json` and interactive documentation at `/docs`.

## Single message

```sh
curl https://relay.example.com/v1/messages \
  -H 'Authorization: Bearer YOUR_CALLER_TOKEN' \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: notification-001' \
  -d '{"device_id":"auto","to":"+12025550123","text":"Your report is ready."}'
```

The example number is illustrative; use an authorized real recipient. `to` is E.164, `text` is 1–1600 characters, and `device_id` is a registered scoped device ID or `auto`. Omission uses the configured default device for single sends. HTTP 202 means durably accepted, including when offline, not delivered. Retrying the same payload/key returns the same ID; different content under the same key returns 409. Use a fresh key only for an intentional new send.

## Status and diagnostics

```http
GET /v1/messages/sms_RETURNED_ID
GET /v1/messages/sms_RETURNED_ID/logs
Authorization: Bearer YOUR_CALLER_TOKEN
```

Only the submitting caller can inspect these records. Status includes ID, device, current state/error, timestamps and transition history. Diagnostic responses omit body/full recipient. Normal progression:

`queued → dispatched → phone_received → submitted_to_modem → sent → delivered`

`buffered` is a bulk/automatic-routing backlog state; `failed` records an explicit failure and `unknown` records an ambiguous outcome requiring review. `sent` alone does not establish recipient delivery. Delivery receipts depend on carrier support.

## Bulk

```http
POST /v1/messages/bulk
Authorization: Bearer YOUR_CALLER_TOKEN
Content-Type: application/json
Idempotency-Key: batch-001

{"device_id":"auto","template":"Hi {name}, your code is {code}.","users":[{"phone":"+12025550123","name":"Alex","code":"1234"}]}
```

Returns 202 with a stable batch ID and individual message IDs. Up to 1000 recipients, a 512 KiB body, string template values and simple named placeholders. Entire batch validation is atomic. Server A renders/queues work and sends ordinary jobs individually to the phone. Check progress with `GET /v1/batches/{id}?offset=0&limit=100`; follow `next_offset`. See [bulk semantics and routing](bulk-api.md).

## Errors and pacing

401: invalid/missing/revoked caller credential. 403: caller device/recipient restriction. 404: record absent or owned by another caller. 409: idempotency conflict. 413: body too large. 422: invalid input. 429: configured rate/queue/backlog limit; inspect response details. Error bodies are intentionally scrubbed.

Default rate is 10 accepted messages/minute per caller and 5 seconds minimum dispatch spacing. Keep `RELAY_MAX_INFLIGHT=1` for sequential per-device processing. Faster minimum spacing does not guarantee one delivered SMS/second: multipart sends, callbacks, signal and carrier filtering determine actual throughput. Use status polling with backoff rather than resubmitting after a timeout.
