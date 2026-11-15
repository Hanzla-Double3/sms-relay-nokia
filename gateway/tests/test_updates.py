import base64
import json
from fastapi.testclient import TestClient
from relay.app import create_app
from relay import updates
from test_gateway import settings,DEVICE,AUTH
from test_admin import admin_login


def test_update_auth_request_offline_and_completion(settings,tmp_path,monkeypatch):
    directory=tmp_path/'release';directory.mkdir()
    payload=dict(version_code=8,version_name='0.6.0',size=3,sha256='a'*64)
    envelope=dict(payload=base64.b64encode(json.dumps(payload).encode()).decode(),signature='test')
    (directory/'manifest.json').write_text(json.dumps(envelope));(directory/'relay.apk').write_bytes(b'apk')
    monkeypatch.setattr(updates,'RELEASE_DIR',directory)
    with TestClient(create_app(settings),base_url='https://testserver') as c:
        auth={'Authorization':f'Bearer {DEVICE}'}
        url='/v1/device/update?device=nokia-01&version_code=5'
        assert c.get(url).status_code==401
        assert c.get(url,headers=AUTH).status_code==401 # API caller cannot impersonate device.
        assert c.get(url,headers=auth).status_code==204
        assert c.get('/admin/updates').status_code==404
        admin_login(c,settings)
        assert c.post('/admin/devices/nokia-01/update',json={}).status_code==403
        assert c.post('/admin/devices/missing/update',json={},headers={'Origin':'https://testserver'}).status_code==404
        assert c.post('/admin/devices/nokia-01/update',json={},headers={'Origin':'https://testserver'}).status_code==200
        assert c.get('/admin/updates').json()['requests'][0]['device']=='nokia-01'
        r=c.get(url,headers=auth);assert r.json()==envelope and r.headers['cache-control']=='no-store'
        assert c.get('/v1/device/update/apk?device=nokia-01',headers=auth).content==b'apk'
        assert c.get('/v1/device/update/apk?device=nokia-01').status_code==401
        assert c.get(url.replace('version_code=5','version_code=8'),headers=auth).status_code==204
        assert c.get('/admin/updates').json()['requests']==[]


def test_missing_release(settings,tmp_path,monkeypatch):
    monkeypatch.setattr(updates,'RELEASE_DIR',tmp_path)
    with TestClient(create_app(settings),base_url='https://testserver') as c:
        admin_login(c,settings)
        assert c.post('/admin/devices/nokia-01/update',json={},headers={'Origin':'https://testserver'}).status_code==409
        assert c.get('/v1/device/update/apk?device=nokia-01',headers={'Authorization':f'Bearer {DEVICE}'}).status_code==404
