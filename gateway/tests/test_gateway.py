import json
import time
import pytest
from fastapi.testclient import TestClient
from relay.app import create_app
from relay.config import Settings, digest
from relay.store import Store, advance

CALLER = "test-caller-credential-32-characters"
OTHER = "test-other-credential-32-characters"
ADMIN = "test-admin-credential-32-characters"
DEVICE = "test-device-credential-32-characters"
AUTH = {"Authorization": f"Bearer {CALLER}"}

@pytest.fixture
def settings(tmp_path):
    return Settings(database=str(tmp_path/"relay.sqlite3"), allow_insecure_local=True,
        callers_json=json.dumps({"b":{"token_sha256":digest(CALLER),"devices":["nokia-01"]},"c":{"token_sha256":digest(OTHER),"devices":["nokia-01"]},"admin":{"token_sha256":digest(ADMIN),"devices":["nokia-01"],"admin":True}}),
        devices_json=json.dumps({"nokia-01":digest(DEVICE)}), min_send_interval=0.1)

@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def submit(client, key=None, **changes):
    payload = {"to":"+923001234567","text":"Operational test",**changes}
    return client.post("/v1/messages", json=payload, headers={**AUTH, **({"Idempotency-Key":key} if key else {})})


def hello(ws, token=DEVICE):
    ws.send_json({"type":"hello","protocol":1,"device_id":"nokia-01","token":token})
    return ws.receive_json()


def heartbeat(ws, ready=True):
    ws.send_json({"type":"heartbeat","ready":ready,"battery":80,"charging":True,"sim_ready":ready,"permission":True,"app_version":"0.1.0","health_code":"READY" if ready else "NO_SIM"})
    assert ws.receive_json()["type"] == "heartbeat_ack"


def report(ws, msg_id, state, revision=1):
    ws.send_json({"type":"sms_status","id":msg_id,"status":state,"revision":revision})
    assert ws.receive_json() == {"type":"status_ack","id":msg_id,"revision":revision,"accepted":True}


def test_auth_scopes_and_status_privacy(client):
    assert client.post("/v1/messages",json={"to":"+923001234567","text":"x"}).status_code == 401
    msg_id=submit(client).json()["id"]
    assert client.get(f"/v1/messages/{msg_id}",headers={"Authorization":f"Bearer {OTHER}"}).status_code == 404
    result=client.get(f"/v1/messages/{msg_id}",headers=AUTH)
    assert result.status_code == 200
    assert "Operational test" not in result.text and "+923001234567" not in result.text
    assert client.get("/v1/devices",headers=AUTH).status_code == 403
    assert submit(client,device_id="rogue").status_code == 403

@pytest.mark.parametrize("changes",[{"to":"03001234567"},{"text":""},{"text":"a"*1601},{"text":"\x00secret"},{"text":"  "},{"extra":"oops"}])
def test_invalid_payloads_do_not_echo_content(client, changes):
    response=submit(client,**changes)
    assert response.status_code == 422
    assert response.json() == {"detail":"INVALID_PAYLOAD"}


def test_idempotency_is_scoped_and_conflict_checked(client):
    first=submit(client,"order:123")
    assert first.status_code == 202
    assert submit(client,"order:123").json() == first.json()
    assert submit(client,"order:123",text="changed").status_code == 409
    assert client.post("/v1/messages",json={"to":"+923001234567","text":"Operational test"},headers={"Authorization":f"Bearer {OTHER}","Idempotency-Key":"order:123"}).json()["id"] != first.json()["id"]
    assert client.post("/v1/messages",json={"to":"+923001234567","text":"x"},headers={**AUTH,"Idempotency-Key":"bad key"}).status_code == 400


def test_queue_rate_and_allowlist(settings):
    settings.queue_limit=1
    settings.recipient_allowlist=["+923001234567"]
    with TestClient(create_app(settings)) as c:
        assert submit(c,to="+923001234568").status_code == 403
        assert submit(c,"one").status_code == 202
        assert submit(c,"one").status_code == 202
        assert submit(c).status_code == 429
    settings.queue_limit=100; settings.rate_per_minute=1
    with TestClient(create_app(settings)) as c:
        assert submit(c).json()["detail"] == "RATE_LIMIT"


def test_frame_and_body_limits(client):
    assert client.post("/v1/messages",content=b"x"*9000,headers=AUTH).status_code == 413
    assert client.post("/v1/messages",content=iter([b"x"*5000,b"x"*5000]),headers=AUTH).status_code == 413
    with client.websocket_connect("/ws/device") as ws:
        ws.send_json({"type":"hello","protocol":1,"device_id":"nokia-01","token":"wrong-credential-xxxxxxxxx"})
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect): ws.receive_json()
    with client.websocket_connect("/ws/device") as ws:
        hello(ws)
        ws.send_json({"type":"execute_shell","command":"id"})
        with pytest.raises(WebSocketDisconnect): ws.receive_json()


def test_real_protocol_sent_only_on_device_callback(client):
    msg_id=submit(client).json()["id"]
    with client.websocket_connect("/ws/device") as ws:
        assert hello(ws)["type"] == "hello_ack"
        heartbeat(ws)
        job=ws.receive_json()
        assert job["type"] == "send_sms" and job["id"] == msg_id
        assert client.get(f"/v1/messages/{msg_id}",headers=AUTH).json()["status"] == "dispatched"
        report(ws,msg_id,"phone_received",1)
        report(ws,msg_id,"submitted_to_modem",2)
        report(ws,msg_id,"sent",3)
        report(ws,msg_id,"phone_received",1)
        result=client.get(f"/v1/messages/{msg_id}",headers=AUTH).json()
        assert result["status"] == "sent"
        assert client.app.state.store.get(msg_id)["body"] is None
        report(ws,msg_id,"delivered",4)
        assert client.get(f"/v1/messages/{msg_id}",headers=AUTH).json()["status"] == "delivered"


def test_no_sim_stays_queued_and_health_visible(client):
    msg_id=submit(client).json()["id"]
    with client.websocket_connect("/ws/device") as ws:
        hello(ws); heartbeat(ws,ready=False)
        devices=client.get("/v1/devices",headers={"Authorization":f"Bearer {ADMIN}"}).json()
        assert devices[0]["online"] and devices[0]["telemetry"]["health_code"] == "NO_SIM"
        assert client.app.state.store.get(msg_id)["status"] == "queued"
    assert not client.get("/v1/devices",headers={"Authorization":f"Bearer {ADMIN}"}).json()[0]["online"]


def test_restart_redelivery_same_id_and_reconciliation(settings):
    with TestClient(create_app(settings)) as c:
        msg_id=submit(c).json()["id"]
        with c.websocket_connect("/ws/device") as ws:
            hello(ws); heartbeat(ws)
            assert ws.receive_json()["id"] == msg_id
    with TestClient(create_app(settings)) as c:
        store=c.app.state.store
        store.db.execute("UPDATE messages SET dispatched=? WHERE id=?",(time.time()-60,msg_id))
        with c.websocket_connect("/ws/device") as ws:
            hello(ws); heartbeat(ws)
            assert ws.receive_json()["id"] == msg_id
            report(ws,msg_id,"submitted_to_modem",2)
        with c.websocket_connect("/ws/device") as ws:
            hello(ws)
            assert ws.receive_json() == {"type":"reconcile","ids":[msg_id]}
            report(ws,msg_id,"unknown",3)
            heartbeat(ws)
            assert store.next_job("nokia-01") is None
            report(ws,msg_id,"sent",4)
            assert store.get(msg_id)["status"] == "sent"


def test_callback_expiry_and_retention_keep_duplicate_guard(settings):
    store=Store(settings)
    row=store.add("b","nokia-01","+923001234567","secret","key","hash")
    job=store.next_job("nokia-01")
    store.status("nokia-01",job["id"],"submitted_to_modem",None)
    store.db.execute("UPDATE messages SET updated=? WHERE id=?",(time.time()-500,job["id"]))
    store.maintain()
    assert store.get(job["id"])["status"] == "unknown"
    assert store.next_job("nokia-01") is None
    assert store.add("b","nokia-01","+923001234567","secret","key","hash")["id"] == row["id"]
    store.db.close()


def test_status_cannot_mutate_other_device(settings):
    store=Store(settings)
    row=store.add("b","nokia-01","+923001234567","secret",None,"hash")
    assert not store.status("other-device",row["id"],"sent",None)
    assert store.get(row["id"])["status"] == "queued"
    store.db.close()


def test_production_requires_tls(settings):
    settings.allow_insecure_local=False
    with TestClient(create_app(settings)) as c:
        assert c.get("/health").json()["detail"] == "HTTPS_REQUIRED"
    with TestClient(create_app(settings),base_url="https://testserver") as c:
        assert c.get("/health").json()["status"] == "ok"

@pytest.mark.parametrize("old,new,expected",[("sent","dispatched","sent"),("sent","failed","sent"),("unknown","sent","sent"),("unknown","phone_received","unknown"),("failed","phone_received","failed"),("submitted_to_modem","delivered","delivered")])
def test_monotonic_state_rules(old,new,expected):
    assert advance(old,new) == expected


def test_one_second_pipeline_and_confirmation_window(settings):
    settings.min_send_interval=1
    settings.max_inflight=2
    with TestClient(create_app(settings)) as c:
        ids=[submit(c,f'pipeline-{i}').json()['id'] for i in range(3)]
        with c.websocket_connect('/ws/device') as ws:
            policy=hello(ws)
            assert policy['send_interval_ms']==1000 and policy['max_inflight']==2
            heartbeat(ws)
            first=ws.receive_json(); at=time.monotonic()
            second=ws.receive_json()
            assert first['id']==ids[0] and second['id']==ids[1]
            assert time.monotonic()-at>=0.9
            # The second dispatch does not wait for a sent callback from the first.
            assert c.app.state.store.get(ids[2])['status']=='queued'
            report(ws,ids[0],'submitted_to_modem',2)
            heartbeat(ws)
            assert c.app.state.store.get(ids[2])['status']=='queued'
            report(ws,ids[0],'sent',3)
            assert ws.receive_json()['id']==ids[2]


def test_full_window_redispatch_reuses_slot_and_uncertain_send_is_not_retried(settings):
    settings.max_inflight=1
    store=Store(settings)
    try:
        first=store.add('b','nokia-01','+923001234567','x','one','hash1')
        second=store.add('b','nokia-01','+923001234567','y','two','hash2')
        assert store.next_job('nokia-01')['id']==first['id']
        assert store.next_job('nokia-01') is None
        store.db.execute('UPDATE messages SET dispatched=? WHERE id=?',(time.time()-100,first['id']))
        assert store.next_job('nokia-01')['id']==first['id']
        store.status('nokia-01',first['id'],'submitted_to_modem',None)
        assert store.next_job('nokia-01') is None
        store.status('nokia-01',first['id'],'unknown','CALLBACK_TIMEOUT')
        assert store.next_job('nokia-01')['id']==second['id']
        assert store.get(first['id'])['status']=='unknown'
    finally:
        store.db.close()
