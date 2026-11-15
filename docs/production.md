# Production operations (example deployment)

The gateway is deployed alongside the server's existing applications, using its existing host Caddy instance. No second proxy binds port 80/443.

- Public API: `https://relay.example.com/v1/messages`
- Device connection: `wss://relay.example.com/ws/device`
- Operator dashboard: `https://relay.example.com/admin`
- Private GitHub repository: `Hanzla-Double3/sms-relay-nokia`
- Isolated Compose project: `sms-relay`
- Backend binding: `127.0.0.1:18082`, never a public port
- Runtime configuration: `/opt/sms-relay/shared/.env`, root-owned mode `0600`
- Persistent SQLite ledger: `/opt/sms-relay/shared/data/relay.sqlite3`

The dashboard shows totals, pending work, confirmed sent/delivery counts, failures, unknown outcomes, accepted messages in the last 24 hours, device health/battery/heartbeat and the latest 50 jobs. It never displays SMS bodies or recipient numbers. Its API token panel creates device-scoped caller tokens, shows their metadata, and revokes them immediately. Browser login uses the `.env` value `RELAY_ADMIN_PASSWORD`, a one-hour Secure/HttpOnly/SameSite=Strict signed cookie and the independent `RELAY_ADMIN_SESSION_SECRET`. Login attempts are limited. Change the password and session secret together and redeploy to invalidate old sessions. No administrator password is committed to Git.

## Automatic deployments

Pushes to `main` run the gateway tests and Android build/unit/lint checks first. Only after both jobs succeed does GitHub Actions stream a Git archive over a dedicated SSH identity. Deployment secrets are `SMS_DEPLOY_KEY`, `SMS_DEPLOY_HOST`, and the pinned `SMS_DEPLOY_KNOWN_HOSTS`. The existing root SSH key is not stored in GitHub.

The deployment user has a forced SSH command and sudo access only to the root-owned `/usr/local/sbin/sms-relay-deploy`. Its archive receiver rejects traversal, links, devices and oversized releases. The deployment script builds a new image, takes a SQLite online backup, updates only the `sms-relay` gateway service, checks readiness, and restores the prior image on a failed health check. A lock and workflow concurrency serialize releases. This V1 deployment briefly disconnects the device when replacing its single gateway process; the durable queue and phone ledger reconcile on reconnect.

Runtime credentials and the database live outside releases, so deployments do not overwrite them. The script does not edit Caddy, restart existing applications, prune other Docker images/volumes, or touch their databases. Image rollback preserves the current database; future incompatible schema migrations need a separately planned migration/rollback path.

The host Caddyfile contains one additional SMS-specific site block. Changes to that proxy configuration should be validated with `caddy validate` before a graceful reload. The automated app deploy does not modify the shared proxy configuration.

## Operations

```sh
# Run on the VPS as an authorized operator:
docker compose --project-name sms-relay --env-file /opt/sms-relay/shared/image.env \
  -f /opt/sms-relay/compose.yaml ps

docker compose --project-name sms-relay --env-file /opt/sms-relay/shared/image.env \
  -f /opt/sms-relay/compose.yaml logs --tail 100 gateway
```

Before deployments, backups are written under `/opt/sms-relay/shared/backups/` and expire after 30 days. Container logs are limited to three 10 MiB files. The relay container runs as UID 10001, drops capabilities and has CPU/memory limits.

Recipient filtering is disabled in production at the owner's request: `RELAY_RECIPIENT_ALLOWLIST=[]` permits any valid E.164 recipient for authenticated callers. Token scopes, rate limits and queue limits still apply. To restrict recipients again, set `RELAY_RECIPIENT_ALLOWLIST` to a JSON list in the private `.env`, then redeploy/recreate only the relay container. Offline or unhealthy devices leave jobs queued. Only callback-confirmed SMS sends become `sent`; uncertain submissions require review and do not cause blind retries.

## Caller token management

Sign in to `/admin`, use **API Bearer tokens**, give a unique name and choose permitted devices. Creation displays a cryptographically random 256-bit secret once. Copy it and set `RELAY_TOKEN` in your sender. No token is embedded in the page source or saved in browser storage. Listing endpoints return only names, scopes, dates and status. The database stores SHA256 hashes; token creation/revocation is audited without raw secrets.

New tokens can submit SMS and inspect their own message statuses; they cannot access administrator routes or grant themselves administrator permissions. Existing configured caller credentials are imported once into the persistent SQLite token registry, so the current Python sender remains usable and those credentials can also be revoked. Revocations persist across app restarts and redeployments. Revocation does not cancel already accepted SMS. Device WSS credentials and the dashboard password remain separate.

After the initial production import, `RELAY_CALLERS_JSON` is cleared from the active environment. The database becomes authoritative for caller credentials. This prevents a rollback to pre-token-management software from reviving old environment tokens; such old images instead reject caller requests. Preserve the SQLite database and its backups. Environment caller definitions are bootstrap seeds, not a mechanism to overwrite/re-enable an existing credential; create replacement tokens through the dashboard.


## Administrator sessions

Sessions expire after one hour. Their random nonce is signed and only its SHA256 hash is registered in SQLite; logout deletes that registration immediately, so a copied cookie cannot be reused afterward. Changing either the admin password or session secret invalidates existing cookie signatures. Retain the database for valid sessions across redeployments. Admin HTML uses a new content-security-policy nonce per response. Token mutations require the exact same Origin and JSON content type. The dashboard password remains in the private environment, never in Git.


## Sending speed

A sequential deployment configures `RELAY_MIN_SEND_INTERVAL=1`, `RELAY_RATE_PER_MINUTE=60` per caller, and `RELAY_MAX_INFLIGHT=1` per device. Android v0.5.0+ negotiates this policy at authenticated connection setup and uses a one-second minimum interval, waiting for the previous message outcome before the next dispatch. Older phones retain five-second modem spacing until updated. For slower mode set interval 5 and rate 10, recreate only the gateway and let the handset reconnect. Settings remain outside releases. The outstanding confirmation window holds additional work in the durable queue; sent/failed/unknown outcomes free slots, without retrying uncertain IDs. Real modem/carrier throughput and multipart costs can differ from the submission target.
