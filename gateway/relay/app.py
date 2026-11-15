import asyncio
import hashlib
import hmac
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal
from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from .config import Settings, digest
from .store import Store
from .bulk import BulkMessage, render

log = logging.getLogger("relay")


def iso(at):
    return datetime.fromtimestamp(at, timezone.utc).isoformat() if at else None


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str = Field(pattern=r"^\+[1-9][0-9]{7,14}$")
    text: str = Field(min_length=1, max_length=1600)
    device_id: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]{1,64}$")

    @field_validator("text")
    @classmethod
    def safe_text(cls, value):
        if not value.strip() or any((ord(c) < 32 and c not in '\n\r\t') or 0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ValueError("Invalid text encoding")
        return value


class Hello(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["hello"]
    device_id: str = Field(max_length=64)
    token: str = Field(min_length=16, max_length=256)
    protocol: Literal[1]


class Status(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["sms_status"]
    id: str = Field(pattern=r"^sms_[a-f0-9]{32}$")
    status: Literal["phone_received", "submitted_to_modem", "sent", "delivered", "failed", "unknown"]
    revision: int = Field(ge=1)
    error_code: str | None = Field(None, pattern=r"^[A-Z0-9_]{1,64}$")


class Heartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["heartbeat"]
    ready: bool
    battery: int = Field(ge=0, le=100)
    charging: bool
    sim_ready: bool
    permission: bool
    app_version: str = Field(max_length=32)
    health_code: str = Field(pattern=r"^[A-Z0-9_]{1,64}$")


class DiagnosticDetails(BaseModel):
    model_config=ConfigDict(extra="forbid")
    part: int | None = Field(None,ge=0,le=15)
    parts: int | None = Field(None,ge=1,le=16)
    result: int | None = Field(None,ge=-1,le=10000)
    radio_error: int | None = Field(None,ge=-2147483648,le=2147483647)
    delivery_status: int | None = Field(None,ge=-2147483648,le=2147483647)
    has_pdu: bool | None = None
    pdu_decoded: bool | None = None
    subscription: int | None = Field(None,ge=-1,le=2147483647)
    signal_dbm: int | None = Field(None,ge=-200,le=100)
    text_chars: int | None = Field(None,ge=1,le=1600)

class Diagnostic(BaseModel):
    model_config=ConfigDict(extra="forbid")
    type: Literal["diagnostic"]
    id: str = Field(pattern=r"^diag_[a-f0-9]{32}$")
    message_id: str = Field(pattern=r"^sms_[a-f0-9]{32}$")
    event: Literal["MODEM_SUBMIT","MODEM_CALLBACK","DELIVERY_CALLBACK","SUBMISSION_ERROR","JOB_RECEIVED","JOB_DUPLICATE"]
    at: int = Field(ge=0,le=9999999999999)
    details: DiagnosticDetails


def create_app(settings=None):
    settings = settings or Settings()
    store = Store(settings)
    connections = {}

    def available_devices():
        now=time.time()
        return {r['id'] for r in store.db.execute('SELECT * FROM devices') if r['id'] in connections and r['heartbeat'] and now-r['heartbeat']<settings.heartbeat_timeout and all(json.loads(r['telemetry'] or '{}').get(key,False) for key in ('ready','sim_ready','permission'))}

    @asynccontextmanager
    async def lifespan(app):
        async def maintenance():
            while True:
                store.maintain()
                store.pump(available_devices())
                await asyncio.sleep(5)
        task = asyncio.create_task(maintenance())
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        store.db.close()

    app = FastAPI(title="Nokia SMS Relay", version="0.1.0", lifespan=lifespan)
    app.state.store = store
    app.state.connections = connections

    @app.exception_handler(RequestValidationError)
    async def invalid(request, error):
        # FastAPI's default errors include raw inputs (including SMS text). Omit them.
        return JSONResponse(status_code=422, content={"detail": "INVALID_PAYLOAD"})

    @app.middleware("http")
    async def transport_and_size(request: Request, call_next):
        if request.url.scheme != "https" and not settings.allow_insecure_local:
            return JSONResponse(status_code=400, content={"detail": "HTTPS_REQUIRED"})
        # Stream-bound limit applies even to chunked requests with no Content-Length.
        bulk=request.url.path=="/v1/messages/bulk" and request.method=="POST"
        if bulk:
            try: caller(request)
            except HTTPException as error: return JSONResponse(status_code=error.status_code,content={"detail":error.detail})
        limit=524288 if bulk else 8192
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > limit:
                return JSONResponse(status_code=413, content={"detail": "PAYLOAD_TOO_LARGE"})
        request._body = bytes(body)
        return await call_next(request)

    def caller(request):
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or len(auth) > 300:
            raise HTTPException(401, "UNAUTHORIZED")
        hashed = digest(auth[7:])
        return store.authenticate_caller(hashed)

    @app.get("/health")
    async def health():
        store.db.execute("SELECT 1")
        return {"status": "ok", "protocol": 1}

    @app.post("/v1/messages", status_code=202)
    async def submit(request: Request, message: Message, idempotency_key: str | None = Header(None)):
        name, cfg = caller(request)
        device = message.device_id or settings.default_device
        if not cfg["devices"] or (device != "auto" and device not in cfg["devices"]):
            raise HTTPException(403, "DEVICE_FORBIDDEN")
        if settings.recipient_allowlist and message.to not in settings.recipient_allowlist:
            raise HTTPException(403, "RECIPIENT_FORBIDDEN")
        if idempotency_key is not None and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", idempotency_key):
            raise HTTPException(400, "INVALID_IDEMPOTENCY_KEY")
        payload_hash = hashlib.sha256(json.dumps([device, message.to, message.text], ensure_ascii=True).encode()).hexdigest()
        row = store.add(name, device, message.to, message.text, idempotency_key, payload_hash,cfg["devices"] if device=="auto" else None)
        if device=="auto":
            store.pump(available_devices()); row=store.get(row["id"])
        store.diagnostic("API_ACCEPTED",device,row["id"],caller=name,status=row["status"],recipient_hint=message.to[:4]+"*****"+message.to[-2:],text_chars=len(message.text))
        return {"id": row["id"], "status": row["status"]}

    @app.post('/v1/messages/bulk',status_code=202)
    async def submit_bulk(request: Request,message: BulkMessage,idempotency_key: str | None=Header(None)):
        name,cfg=caller(request)
        if not cfg['devices'] or (message.device_id!='auto' and message.device_id not in cfg['devices']): raise HTTPException(403,'DEVICE_FORBIDDEN')
        if idempotency_key is not None and not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',idempotency_key): raise HTTPException(400,'INVALID_IDEMPOTENCY_KEY')
        try: rendered=render(message.template,message.users)
        except (ValueError,KeyError): raise HTTPException(422,'INVALID_PAYLOAD') from None
        if settings.recipient_allowlist and any(phone not in settings.recipient_allowlist for phone,_ in rendered): raise HTTPException(403,'RECIPIENT_FORBIDDEN')
        payload_hash=hashlib.sha256(json.dumps([message.device_id,message.template,message.users],sort_keys=True,ensure_ascii=True).encode()).hexdigest()
        batch=store.add_bulk(name,message.device_id,rendered,idempotency_key,payload_hash,cfg['devices'])
        store.pump(available_devices())
        return JSONResponse(store.batch_view(batch,name),status_code=202,headers={'Cache-Control':'no-store'})

    @app.get('/v1/batches/{batch_id}')
    async def batch_status(request: Request,batch_id: str,offset: int=Query(0,ge=0),limit: int=Query(100,ge=1,le=100)):
        name,_=caller(request)
        return JSONResponse(store.batch_view(batch_id,name,offset,limit),headers={'Cache-Control':'no-store'})

    @app.get("/v1/messages/{msg_id}")
    async def status(request: Request, msg_id: str):
        name, cfg = caller(request)
        row = store.get(msg_id)
        if not row or row["caller"] != name:
            raise HTTPException(404, "NOT_FOUND")
        return {"id": row["id"], "device_id": row["device"], "status": row["status"], "error_code": row["error_code"], "created_at": iso(row["created"]), "updated_at": iso(row["updated"]), "history": [{"status": r["status"], "error_code": r["error_code"], "at": iso(r["at"])} for r in store.db.execute("SELECT status,error_code,at FROM audit WHERE message_id=? ORDER BY seq", (msg_id,))]}

    @app.get("/v1/messages/{msg_id}/logs")
    async def message_logs(request: Request,msg_id: str):
        name,_=caller(request)
        row=store.get(msg_id)
        if not row or row["caller"]!=name: raise HTTPException(404,"NOT_FOUND")
        return JSONResponse({"id":msg_id,"status":row["status"],"history":[{"status":r["status"],"error_code":r["error_code"],"at":iso(r["at"])} for r in store.db.execute("SELECT status,error_code,at FROM audit WHERE message_id=? ORDER BY seq",(msg_id,))],"logs":store.diagnostic_rows(msg_id)},headers={"Cache-Control":"no-store"})

    @app.get("/v1/devices")
    async def devices(request: Request):
        _, cfg = caller(request)
        if not cfg.get("admin", False):
            raise HTTPException(403, "ADMIN_REQUIRED")
        return [{"id": r["id"], "online": r["id"] in connections and bool(r["heartbeat"]) and time.time()-r["heartbeat"] < settings.heartbeat_timeout, "last_heartbeat": iso(r["heartbeat"]), "telemetry": json.loads(r["telemetry"] or "{}")} for r in store.db.execute("SELECT * FROM devices") if r["id"] in settings.devices]

    async def frame(ws):
        raw = await ws.receive_text()
        if len(raw.encode()) > settings.max_frame_bytes:
            raise ValueError("oversize")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("object required")
        return data

    @app.websocket("/ws/device")
    async def device_socket(ws: WebSocket):
        if ws.url.scheme != "wss" and not settings.allow_insecure_local:
            await ws.close(code=1008)
            return
        await ws.accept()
        device = None
        try:
            hello = Hello.model_validate(await asyncio.wait_for(frame(ws), 10))
            expected = settings.devices.get(hello.device_id)
            if not expected or not hmac.compare_digest(digest(hello.token), expected):
                await ws.close(code=1008, reason="AUTH_FAILED")
                return
            device = hello.device_id
            if device in connections:
                await ws.close(code=1013, reason="DEVICE_ALREADY_CONNECTED")
                device = None
                return
            connections[device] = ws
            await ws.send_json({"type": "hello_ack", "protocol": 1, "server_time": iso(time.time()), "send_interval_ms": max(1000, int(settings.min_send_interval*1000)), "max_inflight": settings.max_inflight, "diagnostic_protocol": 1})
            store.diagnostic("DEVICE_CONNECTED",device)
            ids = store.reconcile(device)
            for start in range(0, len(ids), 100):
                await ws.send_json({"type": "reconcile", "ids": ids[start:start+100]})
            last_heartbeat = time.monotonic()
            last_dispatch = 0.0
            ready = False
            while True:
                try:
                    data = await asyncio.wait_for(frame(ws), 0.5)
                except asyncio.TimeoutError:
                    data = None
                if data:
                    if data.get("type") == "heartbeat":
                        hb = Heartbeat.model_validate(data)
                        ready = hb.ready and hb.sim_ready and hb.permission
                        last_heartbeat = time.monotonic()
                        store.heartbeat(device, hb.model_dump(exclude={"type"}))
                        await ws.send_json({"type": "heartbeat_ack", "server_time": iso(time.time())})
                    elif data.get("type") == "sms_status":
                        event = Status.model_validate(data)
                        accepted = store.status(device, event.id, event.status, event.error_code)
                        await ws.send_json({"type": "status_ack", "id": event.id, "revision": event.revision, "accepted": accepted})
                    elif data.get("type") == "diagnostic":
                        event=Diagnostic.model_validate(data)
                        row=store.get(event.message_id)
                        accepted=bool(row and row["device"]==device)
                        if accepted:
                            store.diagnostic("PHONE_"+event.event,device,event.message_id,event.id,phone_at=event.at,**event.details.model_dump(exclude_none=True))
                        await ws.send_json({"type":"diagnostic_ack","id":event.id,"accepted":accepted})
                    else:
                        raise ValueError("unsupported operation")
                now = time.monotonic()
                if now-last_heartbeat > settings.heartbeat_timeout:
                    log.warning(json.dumps({"event": "device_offline", "device": device, "reason": "HEARTBEAT_EXPIRED"}))
                    await ws.close(code=1001, reason="HEARTBEAT_EXPIRED")
                    break
                if data: store.pump(available_devices())
                if ready and now-last_dispatch >= settings.min_send_interval:
                    row = store.next_job(device)
                    if row:
                        last_dispatch = now
                        await ws.send_json({"type": "send_sms", "id": row["id"], "to": row["recipient"], "text": row["body"], "attempt": row["attempt"]})
        except (ValidationError, ValueError, json.JSONDecodeError):
            store.diagnostic("PROTOCOL_REJECTED",device)
            await ws.close(code=1008, reason="INVALID_FRAME")
        except asyncio.TimeoutError:
            await ws.close(code=1008, reason="HELLO_TIMEOUT")
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            if device and connections.get(device) is ws:
                connections.pop(device, None)
                store.diagnostic("DEVICE_DISCONNECTED",device)

    from .updates import register_device_updates
    register_device_updates(app,settings,store)
    from .admin import register_admin
    register_admin(app, settings, store, connections)
    return app
