#!/usr/bin/env python3
"""Submit an SMS to Server A. Uses only the Python standard library."""
import argparse
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("to", help="Recipient in E.164 format, e.g. +12025550123")
    parser.add_argument("text", help="Message text")
    parser.add_argument("--key", default=None, help="Reuse this key and payload to safely repeat a request")
    parser.add_argument("--url", default=os.environ.get("RELAY_URL"), help="Your HTTPS /v1/messages endpoint (or RELAY_URL)")
    parser.add_argument("--device", default="auto", help="Device ID, or auto for recipient-hash routing")
    args = parser.parse_args()
    endpoint = urlsplit(args.url or "")
    if endpoint.scheme != "https" or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment or endpoint.path != "/v1/messages":
        parser.error("Set --url or RELAY_URL to https://YOUR_HOST/v1/messages.")
    token = os.environ.get("RELAY_TOKEN", "").strip()
    if not token:
        credentials = Path(__file__).resolve().parents[1] / ".local" / "credentials.json"
        try:
            token = json.loads(credentials.read_text())["server-b"]
        except (OSError, ValueError, KeyError):
            parser.error("Set RELAY_TOKEN to your caller token (not the admin password).")
    key = args.key or str(uuid.uuid4())
    print(f"Request key: {key}", file=sys.stderr, flush=True)
    request = Request(
        args.url,
        data=json.dumps({"to": args.to, "text": args.text, "device_id": args.device}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Idempotency-Key": key},
        method="POST",
    )
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None  # Never forward the Bearer token to a redirect target.

    try:
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            print(json.dumps(json.load(response), indent=2))
    except HTTPError as error:
        print(f"Relay rejected the request: HTTP {error.code}", file=sys.stderr)
        return 1
    except (URLError, TimeoutError, OSError) as error:
        print(f"Connection failed ({type(error).__name__}). Outcome may be uncertain; repeat the same message with --key {key}.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
