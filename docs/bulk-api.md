Bulk SMS is handled by Server A. The phone receives ordinary individual `send_sms` frames and never receives templates or user lists. Existing phone versions can use this API without an app update.

```http
POST https://relay.example.com/v1/messages/bulk
Authorization: Bearer YOUR_CALLER_TOKEN
Idempotency-Key: customer-notice-001
Content-Type: application/json
```

```json
{
  "device_id": "auto",
  "template": "Hi {name}, your code is {code}.",
  "users": [
    {"phone": "+923001234567", "name": "Ali", "code": "1234"},
    {"phone": "+923001234568", "name": "Sara", "code": "5678"}
  ]
}
```

`phone` must be an E.164 string. All other user values must also be strings and can be referenced as `{name}`, `{code}`, etc. Simple placeholders only; Python expressions, attributes, indexing, format specifiers, and conversions are rejected. Use `{{` and `}}` for literal braces. Missing values, invalid numbers, or rendered messages exceeding 1,600 characters reject the entire batch with `422 INVALID_PAYLOAD`; no partial acceptance. Each user entry creates one message, including repeated entries if intentionally present.

The endpoint accepts up to 1,000 users and a 512 KiB JSON body. Existing endpoints retain their 8 KiB limit. Authentication and device/recipient scopes apply to every entry. Validation errors, progress responses and logs omit SMS bodies and full numbers.

A valid batch returns **202**, even when every device is offline:

```json
{
  "id": "batch_<32 hex characters>",
  "status": "queued",
  "total": 2,
  "pending": 2,
  "counts": {"buffered": 2},
  "messages": [
    {"index": 0, "id": "sms_<32 hex characters>", "device_id": null, "status": "buffered", "error_code": null},
    {"index": 1, "id": "sms_<32 hex characters>", "device_id": null, "status": "buffered", "error_code": null}
  ],
  "next_offset": null
}
```

The server assigns stable message IDs and atomically persists rendered messages. `buffered` means waiting in the durable bulk backlog; `queued` means admitted to a device queue. The backlog feeds the queue within the shared per-caller rolling message rate and per-device queue capacity. The default backlog limit is 10,000 unfinished messages per caller (`RELAY_BULK_PENDING_LIMIT`). Bulk submission frequency is also limited to the configured rate per minute. Thus a large batch does not bypass send pacing or fill the phone's ledger at once. Pending payloads expire under the existing retention setting (30 days by default), and terminal payloads are scrubbed. Small idempotency guards remain.

Production uses **`RELAY_MAX_INFLIGHT=1`**: Server A waits for an outcome from the current submission before dispatching another message to that device. Different devices can work independently. `sent` means all Android sent callbacks succeeded; `delivered` requires a receipt. An ambiguous timeout becomes `unknown` and needs review; it is never blindly retried.

Omitting `device_id` from a bulk request defaults to `auto`. Set a specific device ID to pin every message to it. `auto` uses **rendezvous hashing of the recipient phone number and device ID**, across only the caller's authorized devices with an active connection, a fresh heartbeat, SIM/permission availability, and `ready=true`. Device-list order has no effect. New jobs to the same recipient choose the same device for the same available pool, and adding/removing a device changes only some recipient mappings. An assigned queued job stays with its device while available; if that device becomes unavailable before dispatch, the server may hash-route it to another authorized available device. Once dispatched, a message remains pinned to that device, including after disconnects or uncertain outcomes, to prevent cross-device duplicate sends. With no eligible devices, messages remain persisted until one becomes ready. Hashing distributes recipients, so one recipient's large batch uses one device while multiple recipients can use several devices.

Single-message `POST /v1/messages` also accepts `device_id: "auto"`, using the same routing rules. Its existing default when `device_id` is omitted remains unchanged.

Inspect progress with the same caller token:

```http
GET /v1/batches/batch_<id>?offset=0&limit=100
Authorization: Bearer YOUR_CALLER_TOKEN
```

The response includes all status counts and at most 100 individual message entries. Follow `next_offset` to paginate. Batch outcomes are `queued`, `processing`, `completed`, `completed_with_errors`, or `needs_review` (for ambiguous results). `completed` means no automatically pending jobs remain and sends succeeded; it does not imply recipient delivery. Individual IDs use the existing message status/log APIs. Other callers cannot inspect the batch.

Reuse the same `Idempotency-Key` and request content after an uncertain HTTP response. It returns the same batch/message IDs and current progress. Changing the content with that key returns `409 IDEMPOTENCY_CONFLICT`. Bulk keys and single-message keys have separate endpoint namespaces. A new key creates an intentionally new batch. Token revocation blocks new submissions; accepted batches continue under the device permissions captured at acceptance.
