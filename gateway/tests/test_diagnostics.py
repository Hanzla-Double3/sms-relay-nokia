import json
import time
import pytest
from pydantic import ValidationError
from relay.app import Diagnostic
from test_gateway import settings,client,submit,hello,AUTH,OTHER
from test_admin import admin_login


def test_phone_diagnostic_deduplication_and_caller_scope(client):
    msg=submit(client).json()['id']
    data={'type':'diagnostic','id':'diag_'+'a'*32,'message_id':msg,'event':'DELIVERY_CALLBACK','at':123,'details':{'part':0,'result':-1,'has_pdu':True,'pdu_decoded':True,'delivery_status':64,'radio_error':-10}}
    with client.websocket_connect('/ws/device') as ws:
        assert hello(ws)['diagnostic_protocol']==1
        for _ in range(2):
            ws.send_json(data)
            assert ws.receive_json()=={'type':'diagnostic_ack','id':data['id'],'accepted':True}
        ws.send_json({**data,'id':'diag_'+'b'*32,'message_id':'sms_'+'f'*32})
        assert ws.receive_json()['accepted'] is False
    r=client.get(f'/v1/messages/{msg}/logs',headers=AUTH)
    assert r.status_code==200 and r.headers['cache-control']=='no-store'
    logs=r.json()['logs']
    assert len([x for x in logs if x['event']=='PHONE_DELIVERY_CALLBACK'])==1
    assert r.json()['status']=='queued' # A failure diagnostic cannot claim a successful delivery.
    assert 'Operational test' not in r.text and '+923001234567' not in r.text
    assert client.get(f'/v1/messages/{msg}/logs').status_code==401
    assert client.get(f'/v1/messages/{msg}/logs',headers={'Authorization':f'Bearer {OTHER}'}).status_code==404

@pytest.mark.parametrize('extra',[{'body':'private'},{'token':'private'},{'pdu':'private'},{'phone':'+923001234567'}])
def test_unstructured_private_data_rejected(extra):
    with pytest.raises(ValidationError):
        Diagnostic.model_validate({'type':'diagnostic','id':'diag_'+'a'*32,'message_id':'sms_'+'a'*32,'event':'MODEM_CALLBACK','at':1,'details':extra})


def test_log_storage_failure_does_not_fail_committed_submission(client):
    client.app.state.store.db.execute('DROP TABLE diagnostics')
    r=submit(client)
    assert r.status_code==202
    assert client.get('/v1/messages/'+r.json()['id'],headers=AUTH).json()['status']=='queued'
    # Restore table for the lifespan maintenance task.
    client.app.state.store.db.execute('CREATE TABLE diagnostics(seq INTEGER PRIMARY KEY AUTOINCREMENT,at REAL,device TEXT,message_id TEXT,event TEXT,details TEXT,source_id TEXT,UNIQUE(device,source_id))')


def test_diagnostic_retention_and_cap(client):
    store=client.app.state.store
    store.db.executemany('INSERT INTO diagnostics(at,event,details) VALUES(?,?,?)',[(time.time(),'TEST','{}')]*10002)
    store.db.execute('INSERT INTO diagnostics(at,event,details) VALUES(?,?,?)',(time.time()-8*86400,'OLD','{}'))
    store.diagnostic('NEW')
    assert store.db.execute('SELECT count(*) FROM diagnostics').fetchone()[0]==10000
    assert not store.db.execute("SELECT 1 FROM diagnostics WHERE event='OLD'").fetchone()


def test_admin_log_access(client,settings):
    assert client.get('/admin/logs').status_code==404 # Disabled until configured.
    admin_login(client,settings)
    submit(client)
    assert client.get('/admin/logs').json()['logs'][-1]['event']=='API_ACCEPTED'
    assert client.get('/admin/logs?message_id=bad').status_code==422
    client.cookies.clear()
    assert client.get('/admin/logs',headers=AUTH).status_code==401
