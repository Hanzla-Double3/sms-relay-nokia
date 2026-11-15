import hashlib
import json
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RELAY_", env_file=".env", extra="ignore")
    admin_password: SecretStr = SecretStr("")
    admin_session_secret: SecretStr = SecretStr("")
    database: str = "data/relay.sqlite3"
    # JSON: caller name -> {token_sha256, devices: [...], admin: false}
    callers_json: str = "{}"
    # JSON: device id -> SHA256 credential hash
    devices_json: str = "{}"
    default_device: str = "nokia-01"
    allow_insecure_local: bool = False
    recipient_allowlist: list[str] = Field(default_factory=list)
    queue_limit: int = Field(100, ge=1)
    rate_per_minute: int = Field(10, ge=1)
    min_send_interval: float = Field(5, ge=0.1, le=60, allow_inf_nan=False)
    max_inflight: int = Field(1, ge=1, le=10)
    heartbeat_timeout: float = Field(75, ge=2)
    redispatch_seconds: float = Field(30, ge=1)
    reconciliation_seconds: float = Field(300, ge=10)
    retention_days: int = Field(30, ge=1)
    bulk_pending_limit: int = Field(10000,ge=1000,le=100000)
    max_frame_bytes: int = Field(16384, ge=1024)

    @property
    def callers(self):
        return json.loads(self.callers_json)

    @property
    def devices(self):
        return json.loads(self.devices_json)

    @model_validator(mode="after")
    def validate_credentials(self):
        import re
        if self.admin_password.get_secret_value() and (len(self.admin_password.get_secret_value()) < 16 or len(self.admin_session_secret.get_secret_value()) < 32):
            raise ValueError("Admin password must be at least 16 characters and session secret at least 32")
        for name, item in self.callers.items():
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) or not re.fullmatch(r"[a-f0-9]{64}", item["token_sha256"]):
                raise ValueError("Invalid caller identity or credential hash")
            if not isinstance(item.get("devices"), list) or any(d not in self.devices for d in item["devices"]):
                raise ValueError("Caller device scope must contain registered devices")
        for name, token_hash in self.devices.items():
            if name=="auto" or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) or not re.fullmatch(r"[a-f0-9]{64}", token_hash):
                raise ValueError("Invalid device identity or credential hash")
        return self
