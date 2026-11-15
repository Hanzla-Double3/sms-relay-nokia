Server and phone diagnostics correlate events by `sms_...` message ID. The admin page's **Logs** button opens the selected message's events; **Show all** shows the most recent 200. An authenticated caller can fetch its own message's logs and durable status history:

```http
GET /v1/messages/sms_<32 hex characters>/logs
Authorization: Bearer <caller token>
```

The server records accepted API requests, dispatch attempts, state changes, device connects/disconnects, protocol rejection, and update requests. Structured events also go to the isolated gateway's Docker log stream. Phone version 0.6.0 adds durable diagnostic outbox events for received/duplicate jobs, modem submissions, submission exceptions, and individual sent/delivery callbacks. Callback fields include part index, Android result code, radio error when provided, whether a delivery PDU was present/decoded, and parsed delivery status. No raw PDU, SMS text, full recipient number, headers, or credentials are logged. API acceptance logs contain a masked recipient hint and text length.

A `MODEM_CALLBACK` with Android `RESULT_OK` confirms that the modem sent that part. `DELIVERY_CALLBACK` records receipt information even when it indicates failure or cannot be decoded. Neither a diagnostic nor a missing receipt is treated as successful delivery. Missing or failed receipts do not trigger blind retries. For multipart SMS, all sent parts must succeed for `sent`; delivery advances only through the existing receipt rules.

Phone logs and structured diagnostics expire after one hour, with separate caps of 500 rows each. Diagnostics awaiting upload also expire, so an outage over one hour loses those details but does not remove SMS state/duplicate guards. The gateway stores diagnostics for seven days capped at 10,000 rows globally; the separate status audit follows its existing 30-day retention. Uploaded events are deduplicated by device and diagnostic ID. Diagnostic storage failure does not prevent a durable SMS transition.

WebSocket `hello_ack` advertises `diagnostic_protocol:1`. Upgraded phones upload `diagnostic` frames and retire uploaded outbox entries after `diagnostic_ack`. Old phones continue using status frames; new phones do not upload diagnostic frames to servers that omit this capability. Only the authenticated device owning the message may attach logs, and diagnostic detail fields are strictly allowlisted.

Existing messages keep their status history, but the additional modem/PDU details cannot be reconstructed retroactively. The two earlier reported sends have no stored delivery receipt; new phone logging becomes available after the next USB installation.
