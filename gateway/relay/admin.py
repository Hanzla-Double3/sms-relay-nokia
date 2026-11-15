"""Operator dashboard with isolated password/session authentication."""
import hashlib
import hmac
import json
import secrets
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=256)


class TokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    devices: list[str] = Field(min_length=1, max_length=100)


def register_admin(app, settings, store, connections):
    attempts = defaultdict(deque)
    started = time.monotonic()
    def enabled():
        if not settings.admin_password.get_secret_value():
            raise HTTPException(404, "ADMIN_DISABLED")
    def same_origin(request):
        # JSON-only login/logout and same-origin browser requests prevent form-based CSRF.
        origin = request.headers.get("origin")
        expected = str(request.base_url).rstrip("/")
        if origin and origin != expected:
            raise HTTPException(403, "ORIGIN_FORBIDDEN")
    def signature(value):
        return hmac.new(settings.admin_session_secret.get_secret_value().encode(),(value+"."+hashlib.sha256(settings.admin_password.get_secret_value().encode()).hexdigest()).encode(),hashlib.sha256).hexdigest()
    def authenticated(request):
        enabled()
        value = request.cookies.get("relay_admin", "")
        try:
            token, signed = value.rsplit(".",1)
            expiry, nonce = token.split(".",1)
            if not hmac.compare_digest(signed,signature(token)) or int(expiry) <= time.time() or len(nonce) != 32:
                raise ValueError()
            if not store.db.execute("SELECT 1 FROM admin_sessions WHERE nonce_sha256=? AND expires=? AND expires>?",(hashlib.sha256(nonce.encode()).hexdigest(),int(expiry),time.time())).fetchone():
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(401,"LOGIN_REQUIRED")
    def stamp(value):
        return datetime.fromtimestamp(value,timezone.utc).isoformat() if value else None

    @app.get("/admin",response_class=HTMLResponse,include_in_schema=False)
    async def page():
        enabled()
        nonce = secrets.token_urlsafe(24)
        html = Path(__file__).with_name("admin.html").read_text().replace("<style>",f'<style nonce="{nonce}">',1).replace("<script>",f'<script nonce="{nonce}">',1)
        return HTMLResponse(html,headers={"Cache-Control":"no-store","Content-Security-Policy":f"default-src 'self'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'","X-Content-Type-Options":"nosniff","Referrer-Policy":"no-referrer"})

    @app.post("/admin/login",include_in_schema=False)
    async def login(request: Request, body: Login):
        enabled(); same_origin(request)
        if not request.headers.get("content-type", "").startswith("application/json"):
            raise HTTPException(415,"JSON_REQUIRED")
        now=time.monotonic(); ip=request.client.host if request.client else "unknown"
        for key in list(attempts):
            while attempts[key] and attempts[key][0] < now-60: attempts[key].popleft()
            if not attempts[key]: del attempts[key]
        # Also cap aggregate guesses, including a flood of different addresses.
        if sum(map(len,attempts.values())) >= 30 or len(attempts[ip]) >= 5:
            raise HTTPException(429,"LOGIN_RATE_LIMIT")
        attempts[ip].append(now)
        if not hmac.compare_digest(hashlib.sha256(body.password.encode()).digest(),hashlib.sha256(settings.admin_password.get_secret_value().encode()).digest()):
            raise HTTPException(401,"INVALID_PASSWORD")
        expiry=int(time.time())+3600
        nonce=secrets.token_hex(16)
        store.db.execute("DELETE FROM admin_sessions WHERE expires<=?",(time.time(),))
        store.db.execute("INSERT INTO admin_sessions(nonce_sha256,expires) VALUES(?,?)",(hashlib.sha256(nonce.encode()).hexdigest(),expiry))
        token=f"{expiry}.{nonce}"
        response=JSONResponse({"status":"ok"},headers={"Cache-Control":"no-store"})
        response.set_cookie("relay_admin",token+"."+signature(token),max_age=3600,httponly=True,secure=not settings.allow_insecure_local,samesite="strict",path="/admin")
        return response

    @app.post("/admin/logout",include_in_schema=False)
    async def logout(request: Request):
        same_origin(request)
        try:
            value = request.cookies.get("relay_admin", "")
            token, signed = value.rsplit(".",1)
            _, nonce = token.split(".",1)
            if hmac.compare_digest(signed,signature(token)):
                store.db.execute("DELETE FROM admin_sessions WHERE nonce_sha256=?",(hashlib.sha256(nonce.encode()).hexdigest(),))
        except (ValueError,TypeError):
            pass
        response=JSONResponse({"status":"ok"},headers={"Cache-Control":"no-store"})
        response.delete_cookie("relay_admin",path="/admin",httponly=True,secure=not settings.allow_insecure_local,samesite="strict")
        return response

    def mutation(request):
        authenticated(request)
        if request.headers.get("origin") != str(request.base_url).rstrip("/"):
            raise HTTPException(403,"ORIGIN_FORBIDDEN")
        if not request.headers.get("content-type", "").startswith("application/json"):
            raise HTTPException(415,"JSON_REQUIRED")

    @app.get("/admin/tokens",include_in_schema=False)
    async def tokens(request: Request):
        authenticated(request)
        rows = store.tokens()
        for row in rows:
            for key in ("created","last_used","revoked"):
                row[key] = stamp(row[key])
        return JSONResponse({"tokens":rows,"devices":list(settings.devices)},headers={"Cache-Control":"no-store"})

    @app.post("/admin/tokens",status_code=201,include_in_schema=False)
    async def create_token(request: Request, body: TokenCreate):
        mutation(request)
        return JSONResponse(store.create_token(body.name,body.devices),status_code=201,headers={"Cache-Control":"no-store"})

    @app.post("/admin/tokens/{token_id}/revoke",include_in_schema=False)
    async def revoke_token(request: Request, token_id: str):
        mutation(request)
        store.revoke_token(token_id)
        return JSONResponse({"status":"revoked"},headers={"Cache-Control":"no-store"})

    @app.get("/admin/updates",include_in_schema=False)
    async def updates(request: Request):
        authenticated(request)
        from .updates import release_info
        return JSONResponse({"release":release_info(),"requests":[dict(r) for r in store.db.execute("SELECT * FROM update_requests")]},headers={"Cache-Control":"no-store"})

    @app.post("/admin/devices/{device}/update",include_in_schema=False)
    async def request_update(request: Request,device: str):
        mutation(request)
        if device not in settings.devices: raise HTTPException(404,"DEVICE_NOT_FOUND")
        from .updates import release_info
        release=release_info()
        if not release: raise HTTPException(409,"NO_RELEASE_AVAILABLE")
        store.db.execute("INSERT INTO update_requests(device,requested) VALUES(?,?) ON CONFLICT(device) DO UPDATE SET requested=excluded.requested",(device,time.time()))
        store.diagnostic("UPDATE_REQUESTED",device,version=release["version_name"])
        return {"status":"requested","version":release["version_name"]}

    @app.get("/admin/logs",include_in_schema=False)
    async def diagnostic_logs(request: Request,message_id: str | None=None):
        authenticated(request)
        if message_id and not re.fullmatch(r"sms_[a-f0-9]{32}",message_id): raise HTTPException(422,"INVALID_MESSAGE_ID")
        return JSONResponse({"logs":store.diagnostic_rows(message_id),"history":[dict(r) for r in store.db.execute("SELECT at,status,error_code FROM audit WHERE message_id=? ORDER BY seq",(message_id,))] if message_id else []},headers={"Cache-Control":"no-store"})

    @app.get("/admin/stats",include_in_schema=False)
    async def stats(request: Request):
        authenticated(request)
        now=time.time()
        total={r["status"]:r["n"] for r in store.db.execute("SELECT status,count(*) n FROM messages GROUP BY status")}
        today={r["status"]:r["n"] for r in store.db.execute("SELECT status,count(*) n FROM messages WHERE created>=? GROUP BY status",(now-86400,))}
        devices=[{"id":r["id"],"online":r["id"] in connections and bool(r["heartbeat"]) and now-r["heartbeat"]<settings.heartbeat_timeout,"heartbeat":stamp(r["heartbeat"]),"telemetry":json.loads(r["telemetry"] or "{}"),"queued":store.db.execute("SELECT count(*) FROM messages WHERE device=? AND status IN ('buffered','queued','dispatched','phone_received','submitted_to_modem')",(r["id"],)).fetchone()[0]} for r in store.db.execute("SELECT * FROM devices") if r["id"] in settings.devices]
        recent=[{"id":r["id"],"caller":r["caller"],"device":r["device"],"status":r["status"],"error":r["error_code"],"created":stamp(r["created"]),"updated":stamp(r["updated"])} for r in store.db.execute("SELECT id,caller,device,status,error_code,created,updated FROM messages ORDER BY created DESC LIMIT 50")]
        failures=[{"code":r["error_code"],"count":r["n"]} for r in store.db.execute("SELECT error_code,count(*) n FROM messages WHERE status IN ('failed','unknown') GROUP BY error_code ORDER BY n DESC LIMIT 10")]
        return JSONResponse({"total":total,"last_24h":today,"devices":devices,"recent":recent,"failures":failures,"uptime_seconds":int(time.monotonic()-started),"server_time":stamp(now)},headers={"Cache-Control":"no-store"})
