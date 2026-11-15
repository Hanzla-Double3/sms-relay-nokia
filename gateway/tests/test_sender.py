"""Exercise the standalone sender without network access or an SMS."""
import importlib.util
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

spec = importlib.util.spec_from_file_location("relay_sender", Path(__file__).parents[2] / "scripts/send_sms.py")
sender = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sender)


def test_sender_uses_explicit_server_and_rejects_redirects(monkeypatch):
    monkeypatch.setenv("RELAY_TOKEN", "synthetic-test-credential")
    monkeypatch.setenv("RELAY_URL", "https://relay.example.com/v1/messages")
    monkeypatch.setattr(sys, "argv", ["send_sms.py", "+12025550123", "Example", "--key", "test-001"])
    captured = {}

    class Opener:
        def open(self, request, timeout):
            captured["request"] = request
            return io.BytesIO(b'{"id":"sms_example","status":"queued"}')

    def build(handler):
        assert handler.redirect_request(None, None, 302, "", {}, "https://other.example/") is None
        return Opener()

    with patch.object(sender, "build_opener", build):
        assert sender.main() == 0
    request = captured["request"]
    assert request.full_url == "https://relay.example.com/v1/messages"
    assert json.loads(request.data)["device_id"] == "auto"
    assert request.get_header("Idempotency-key") == "test-001"


@pytest.mark.parametrize("url", ["", "http://relay.example.com/v1/messages", "https://user:pass@relay.example.com/v1/messages", "https://relay.example.com/v1/messages?token=example"])
def test_sender_rejects_missing_or_unsafe_endpoint(monkeypatch, url):
    monkeypatch.setenv("RELAY_URL", url)
    monkeypatch.setattr(sys, "argv", ["send_sms.py", "+12025550123", "Example"])
    with pytest.raises(SystemExit) as error:
        sender.main()
    assert error.value.code == 2
