#!/bin/bash
# Installed root-owned outside the repo. SSH is restricted to this entry point.
set -euo pipefail
umask 077
base=/opt/sms-relay
exec 9>"$base/deploy.lock"
flock -w 600 9
release=$(mktemp -d "$base/releases/release-XXXXXXXX")
python3 /usr/local/lib/sms-relay-receive-release.py "$release"
image="sms-relay-gateway:$(basename "$release")"
docker build --quiet -t "$image" "$release/gateway"
previous=$(cat "$base/shared/image.env" 2>/dev/null || true)
# SQLite online backup before a new image touches the shared DB.
if [ -f "$base/shared/data/relay.sqlite3" ]; then
  python3 - "$base" <<'PY'
import sqlite3,sys,time
from pathlib import Path
base=Path(sys.argv[1]); target=base/'shared/backups'/('relay-'+str(int(time.time()))+'.sqlite3')
source=sqlite3.connect(base/'shared/data/relay.sqlite3'); dest=sqlite3.connect(target)
source.backup(dest);dest.close();source.close();target.chmod(0o600)
PY
fi
printf 'RELAY_IMAGE=%s\n' "$image" > "$base/shared/image.env"
compose=(docker compose --project-name sms-relay --env-file "$base/shared/image.env" -f /opt/sms-relay/compose.yaml)
"${compose[@]}" up -d --no-deps gateway
healthy=false
for n in $(seq 1 45); do
  if curl --fail --silent --max-time 3 -H 'X-Forwarded-Proto: https' http://127.0.0.1:18082/health >/dev/null; then healthy=true; break; fi
  sleep 2
done
if [ "$healthy" != true ]; then
  if [ -n "$previous" ]; then
    printf '%s\n' "$previous" > "$base/shared/image.env"
    "${compose[@]}" up -d --no-deps gateway
  fi
  echo 'Relay health check failed; previous image restored when available.' >&2
  exit 1
fi
ln -sfn "$release" "$base/current"
# Backups expire after 30 days. Do not prune unrelated Docker resources.
find "$base/shared/backups" -name 'relay-*.sqlite3' -type f -mtime +30 -delete
printf 'Relay deployed successfully: %s\n' "$image"
