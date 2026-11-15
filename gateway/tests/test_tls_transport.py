"""Exercise a real HTTPS/WSS listener with certificate validation (no modem)."""
import json
import socket
import ssl
import subprocess
import threading
import time
import httpx
import uvicorn
from websockets.sync.client import connect
from relay.app import create_app
from relay.config import Settings, digest


def test_https_wss_with_verified_certificate(tmp_path):
    cert=tmp_path/"cert.pem"; key=tmp_path/"key.pem"
    subprocess.run(["openssl","req","-x509","-newkey","rsa:2048","-nodes","-days","1","-keyout",str(key),"-out",str(cert),"-subj","/CN=localhost","-addext","subjectAltName=DNS:localhost,IP:127.0.0.1"],check=True,capture_output=True)
    tls=ssl.create_default_context(cafile=str(cert))
    caller="tls-test-caller-credential-xxxxxxxx"
    device="tls-test-device-credential-xxxxxxxx"
    settings=Settings(database=str(tmp_path/"relay.db"),allow_insecure_local=False,
        callers_json=json.dumps({"b":{"token_sha256":digest(caller),"devices":["nokia-01"]}}),
        devices_json=json.dumps({"nokia-01":digest(device)}),min_send_interval=0.1)
    # Bind before starting Uvicorn to reserve a collision-free local port.
    listener=socket.socket(); listener.bind(("127.0.0.1",0)); port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(create_app(settings),ssl_certfile=str(cert),ssl_keyfile=str(key),log_level="error",ws_max_size=16384))
    thread=threading.Thread(target=lambda: server.run(sockets=[listener]),daemon=True); thread.start()
    deadline=time.monotonic()+10
    while not server.started and thread.is_alive() and time.monotonic()<deadline: time.sleep(0.01)
    assert server.started
    try:
        with httpx.Client(base_url=f"https://127.0.0.1:{port}",verify=tls,headers={"Authorization":f"Bearer {caller}"}) as client:
            assert client.get("/health").json()["status"] == "ok"
            response=client.post("/v1/messages",json={"to":"+923001234567","text":"TLS integration test"})
            assert response.status_code == 202
            msg_id=response.json()["id"]
            with connect(f"wss://127.0.0.1:{port}/ws/device",ssl=tls,max_size=16384) as ws:
                def send(data): ws.send(json.dumps(data))
                def receive(): return json.loads(ws.recv(timeout=3))
                send({"type":"hello","device_id":"nokia-01","token":device,"protocol":1})
                assert receive()["type"] == "hello_ack"
                send({"type":"heartbeat","ready":True,"battery":80,"charging":True,"sim_ready":True,"permission":True,"app_version":"test","health_code":"READY"})
                assert receive()["type"] == "heartbeat_ack"
                assert receive()["id"] == msg_id
                for revision,state in enumerate(["phone_received","submitted_to_modem","sent"],1):
                    send({"type":"sms_status","id":msg_id,"status":state,"revision":revision})
                    assert receive()["type"] == "status_ack"
                assert client.get(f"/v1/messages/{msg_id}").json()["status"] == "sent"
    finally:
        server.should_exit=True; thread.join(10); listener.close()
        assert not thread.is_alive()
