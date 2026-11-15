from test_gateway import settings, client, submit
from fastapi.testclient import TestClient
from pydantic import SecretStr
from relay.app import create_app


def test_admin_auth_stats_and_cookie(settings):
    settings.allow_insecure_local=False
    settings.admin_password=SecretStr('test-admin-password-strong')
    settings.admin_session_secret=SecretStr('test-session-secret-32-characters-long')
    with TestClient(create_app(settings),base_url='https://testserver') as c:
        assert c.get('/admin').status_code==200
        assert c.get('/admin/stats').status_code==401
        assert c.post('/admin/login',json={'password':'wrong'}).status_code==401
        assert c.post('/admin/login',json={'password':settings.admin_password.get_secret_value()},headers={'Origin':'https://evil.example'}).status_code==403
        r=c.post('/admin/login',json={'password':settings.admin_password.get_secret_value()},headers={'Origin':'https://testserver'})
        assert r.status_code==200
        cookie=r.headers['set-cookie'];assert 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=strict' in cookie
        submit(c)
        r=c.get('/admin/stats');assert r.status_code==200
        assert r.json()['total']['queued']==1
        assert '+923001234567' not in r.text and 'Operational test' not in r.text
        assert r.headers['cache-control']=='no-store'
        assert c.post('/admin/logout',headers={'Origin':'https://testserver'}).status_code==200
        assert c.get('/admin/stats').status_code==401


def test_login_rate_limit_and_disabled(settings):
    with TestClient(create_app(settings)) as c:
        assert c.get('/admin').status_code==404
    settings.admin_password=SecretStr('test-admin-password-strong');settings.admin_session_secret=SecretStr('test-session-secret-32-characters-long')
    with TestClient(create_app(settings)) as c:
        for _ in range(5): assert c.post('/admin/login',json={'password':'wrong'}).status_code==401
        assert c.post('/admin/login',json={'password':'wrong'}).status_code==429
        c.cookies.set('relay_admin','tampered')
        assert c.get('/admin/stats').status_code==401


def admin_login(client, settings):
    from pydantic import SecretStr
    settings.admin_password = SecretStr('test-admin-password-strong')
    settings.admin_session_secret = SecretStr('test-session-secret-32-characters-long')
    assert client.post('/admin/login', json={'password': settings.admin_password.get_secret_value()}).status_code == 200


def test_tokens_require_admin_and_same_origin(settings):
    from test_gateway import AUTH
    with TestClient(create_app(settings), base_url='https://testserver') as c:
        admin_login(c, settings)
        payload={'name':'python','devices':['nokia-01']}
        assert c.post('/admin/tokens',json=payload).status_code==403
        assert c.post('/admin/tokens',json=payload,headers={'Origin':'https://evil.example'}).status_code==403
        assert c.post('/admin/tokens/env:b/revoke',json={},headers={'Origin':'https://evil.example'}).status_code==403
        assert c.post('/admin/tokens/env:b/revoke',content='{}',headers={'Origin':'https://testserver','Content-Type':'text/plain'}).status_code==415
        c.cookies.clear()
        assert c.get('/admin/tokens',headers=AUTH).status_code==401
        assert c.post('/admin/tokens',json=payload,headers={**AUTH,'Origin':'https://testserver'}).status_code==401
        assert c.post('/admin/tokens/env:b/revoke',json={},headers={'Origin':'https://testserver'}).status_code==401


def test_create_token_hash_only_scope_and_immediate_revoke(settings):
    from relay.config import digest
    import json
    settings.devices_json=json.dumps({**settings.devices,'other':'a'*64})
    app=create_app(settings)
    with TestClient(app,base_url='https://testserver') as c:
        admin_login(c,settings)
        origin={'Origin':'https://testserver'}
        assert c.post('/admin/tokens',json={'name':'bad','devices':[]},headers=origin).status_code==422
        assert c.post('/admin/tokens',json={'name':'bad','devices':['absent']},headers=origin).status_code==422
        assert c.post('/admin/tokens',json={'name':'bad','devices':['other','other']},headers=origin).status_code==422
        assert c.post('/admin/tokens',json={'name':'<script>','devices':['other']},headers=origin).status_code==422
        assert c.post('/admin/tokens',json={'name':'bad','devices':['other'],'admin':True},headers=origin).status_code==422
        r=c.post('/admin/tokens',json={'name':'python','devices':['other']},headers=origin)
        assert r.status_code==201 and r.headers['cache-control']=='no-store'
        token=r.json()['token']; token_id=r.json()['id']; auth={'Authorization':f'Bearer {token}'}
        assert len(token)>40
        assert c.post('/admin/tokens',json={'name':'python','devices':['other']},headers=origin).status_code==409
        listing=c.get('/admin/tokens');assert token not in listing.text and digest(token) not in listing.text
        assert app.state.store.db.execute('SELECT token_sha256 FROM api_tokens WHERE id=?',(token_id,)).fetchone()[0]==digest(token)
        assert c.post('/v1/messages',json={'to':'+923001234567','text':'Scoped test'},headers=auth).status_code==403
        job=c.post('/v1/messages',json={'to':'+923001234567','text':'Scoped test','device_id':'other'},headers=auth)
        assert job.status_code==202
        assert c.get('/v1/devices',headers=auth).status_code==403
        assert next(t for t in c.get('/admin/tokens').json()['tokens'] if t['id']==token_id)['last_used'] is not None
        assert c.post(f'/admin/tokens/{token_id}/revoke',json={},headers=origin).status_code==200
        assert c.post(f'/admin/tokens/{token_id}/revoke',json={},headers=origin).status_code==200
        assert app.state.store.get(job.json()['id'])['status']=='queued'
        assert c.get('/v1/messages/'+job.json()['id'],headers=auth).status_code==401
        assert c.post('/v1/messages',json={'to':'+923001234567','text':'Blocked'},headers=auth).status_code==401
        assert c.post('/admin/tokens/absent/revoke',json={},headers=origin).status_code==404
        assert app.state.store.db.execute("SELECT count(*) FROM token_audit WHERE token_id=? AND action='revoked'",(token_id,)).fetchone()[0]==1
        c.cookies.clear()
        assert c.get('/admin/tokens',headers=auth).status_code==401


def test_created_tokens_and_environment_revocations_survive_restart(settings):
    from test_gateway import AUTH
    origin={'Origin':'https://testserver'}
    with TestClient(create_app(settings),base_url='https://testserver') as c:
        admin_login(c,settings)
        created=c.post('/admin/tokens',json={'name':'persistent','devices':['nokia-01']},headers=origin).json()
        auth={'Authorization':f"Bearer {created['token']}"}
        assert c.post('/admin/tokens/env:b/revoke',json={},headers=origin).status_code==200
        assert submit(c).status_code==401
    with TestClient(create_app(settings),base_url='https://testserver') as c:
        assert c.post('/v1/messages',json={'to':'+923001234567','text':'Persistent token'},headers=auth).status_code==202
        assert c.post('/v1/messages',json={'to':'+923001234567','text':'Old env token'},headers=AUTH).status_code==401
        admin_login(c,settings)
        assert c.post(f"/admin/tokens/{created['id']}/revoke",json={},headers=origin).status_code==200
    with TestClient(create_app(settings),base_url='https://testserver') as c:
        assert c.post('/v1/messages',json={'to':'+923001234567','text':'Revoked'},headers=auth).status_code==401


def test_logout_invalidates_captured_session(settings):
    with TestClient(create_app(settings),base_url='https://testserver') as c:
        admin_login(c,settings)
        captured=c.cookies.get('relay_admin')
        assert c.post('/admin/logout',headers={'Origin':'https://testserver'}).status_code==200
        headers={'Cookie':f'relay_admin={captured}','Origin':'https://testserver'}
        assert c.get('/admin/stats',headers=headers).status_code==401
        assert c.post('/admin/tokens',json={'name':'replayed','devices':['nokia-01']},headers=headers).status_code==401


def test_password_change_invalidates_sessions_and_registry_checks_expiry(settings):
    with TestClient(create_app(settings),base_url='https://testserver') as c:
        admin_login(c,settings)
        settings.admin_password=SecretStr('different-admin-password-strong')
        assert c.get('/admin/stats').status_code==401
        assert c.post('/admin/login',json={'password':settings.admin_password.get_secret_value()}).status_code==200
        c.app.state.store.db.execute('UPDATE admin_sessions SET expires=0')
        assert c.get('/admin/tokens').status_code==401


def test_session_logout_persists_across_restart_and_csp_nonces(settings):
    with TestClient(create_app(settings),base_url='https://testserver') as c:
        admin_login(c,settings)
        first=c.get('/admin');second=c.get('/admin')
        assert 'unsafe-inline' not in first.headers['content-security-policy']
        assert first.headers['content-security-policy']!=second.headers['content-security-policy']
        import re
        nonce=re.search(r'<script nonce="([^"]+)"',first.text).group(1)
        assert 'nonce-'+nonce in first.headers['content-security-policy']
        assert '<style nonce="'+nonce+'">' in first.text
        captured=c.cookies.get('relay_admin')
        c.post('/admin/logout',headers={'Origin':'https://testserver'})
    with TestClient(create_app(settings),base_url='https://testserver') as c:
        assert c.get('/admin/tokens',headers={'Cookie':f'relay_admin={captured}'}).status_code==401
