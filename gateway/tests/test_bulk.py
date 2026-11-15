import json
import sqlite3
import time
import pytest
from fastapi.testclient import TestClient
from relay.app import create_app
from relay.config import digest
from relay.store import Store
from test_gateway import settings,client,AUTH,OTHER,DEVICE,hello,heartbeat,report,submit

PAYLOAD={'template':'Hi {name}, your code is {code}.','users':[{'phone':'+923001234567','name':'Ali','code':'1234'},{'phone':'+923001234568','name':'Sara','code':'5678'}]}

def bulk(c,**payload):
    return c.post('/v1/messages/bulk',json={**PAYLOAD,**payload},headers={**AUTH,'Idempotency-Key':'bulk-test'})

def fleet(settings):
    settings.devices_json=json.dumps({'nokia-01':digest(DEVICE),'nokia-02':digest('second-device-credential-32-characters')})
    data=settings.callers;data['b']['devices']=['nokia-01','nokia-02'];settings.callers_json=json.dumps(data)


def test_offline_batch_atomic_idempotency_progress_and_privacy(client):
    r=bulk(client);assert r.status_code==202
    data=r.json();assert data['total']==2 and data['counts']=={'buffered':2}
    assert all(m['device_id'] is None for m in data['messages'])
    assert bulk(client).json()==data
    assert bulk(client,template='Different {name}').status_code==409
    assert client.get('/v1/batches/'+data['id']).status_code==401
    assert client.get('/v1/batches/'+data['id'],headers={'Authorization':f'Bearer {OTHER}'}).status_code==404
    result=client.get('/v1/batches/'+data['id'],params={'limit':1},headers=AUTH)
    assert result.headers['cache-control']=='no-store' and result.json()['next_offset']==1
    assert 'Ali' not in result.text and '+923001234567' not in result.text and 'your code' not in result.text
    assert client.get('/v1/batches/'+data['id'],params={'offset':1},headers=AUTH).json()['messages'][0]['index']==1
    assert client.get('/v1/batches/'+data['id'],params={'limit':101},headers=AUTH).status_code==422

@pytest.mark.parametrize('payload',[
    {'users':[]}, {'users':[{'name':'Ali'}]}, {'users':[{'phone':'03001234567','name':'Ali'}]},
    {'users':[{'phone':'+923001234567','name':123}]}, {'template':'{name.secret}'},
    {'template':'{name[0]}'}, {'template':'{name!r}'}, {'template':'{name:>10}'},
    {'template':'{missing}'}, {'template':'broken {'}, {'template':'\x00secret'},
    {'template':'{name}','users':[{'phone':'+923001234567','name':' '}]},
    {'users':[{'phone':'+923001234567','name':'a'*1600,'code':'x'}]},
    {'users':[PAYLOAD['users'][0],{'phone':'+923001234568','name':'Sara'}]},
])
def test_invalid_batch_has_no_partial_jobs_or_content_echo(client,payload):
    r=bulk(client,**payload);assert r.status_code==422 and r.json()=={'detail':'INVALID_PAYLOAD'}
    assert client.app.state.store.db.execute('SELECT count(*) FROM messages').fetchone()[0]==0
    assert client.app.state.store.db.execute('SELECT count(*) FROM batches').fetchone()[0]==0


def test_literal_values_not_recursively_evaluated(client):
    r=bulk(client,template='{{hello}} {name}',users=[{'phone':'+923001234567','name':'{code.__class__}'}])
    assert r.status_code==202
    assert client.app.state.store.get(r.json()['messages'][0]['id'])['body']=='{hello} {code.__class__}'


def test_scope_allowlist_and_body_bounds(client,settings):
    assert bulk(client,device_id='rogue').status_code==403
    settings.recipient_allowlist=['+923001234567']
    assert bulk(client).status_code==403
    settings.recipient_allowlist=[]
    users=[{'phone':'+923001234567','name':'Ali','code':str(i)} for i in range(200)]
    assert len(json.dumps({**PAYLOAD,'users':users}))>8192
    assert bulk(client,users=users).status_code==202
    assert client.post('/v1/messages/bulk',content=b'x'*524289,headers=AUTH).status_code==413
    assert client.post('/v1/messages/bulk',content=b'x'*9000).status_code==401
    assert bulk(client,users=users*6).status_code==422


def test_rate_and_queue_capacity_feed_large_backlog(settings):
    settings.queue_limit=1;settings.rate_per_minute=2
    store=Store(settings)
    try:
        batch=store.add_bulk('b','nokia-01',[(f'+92300123456{i}','hello') for i in range(3)],'batch','hash',['nokia-01'])
        store.pump({'nokia-01'})
        view=store.batch_view(batch,'b');assert view['counts']=={'buffered':2,'queued':1}
        first=store.next_job('nokia-01');assert store.next_job('nokia-01') is None
        store.status('nokia-01',first['id'],'sent',None);store.pump({'nokia-01'})
        second=store.next_job('nokia-01');store.status('nokia-01',second['id'],'sent',None)
        store.pump({'nokia-01'});assert store.batch_view(batch,'b')['counts']=={'buffered':1,'sent':2}
        store.db.execute('UPDATE rates SET at=?',(time.time()-61,));store.pump({'nokia-01'})
        third=store.next_job('nokia-01');store.status('nokia-01',third['id'],'failed','MODEM_ERROR_2')
        assert store.batch_view(batch,'b')['status']=='completed_with_errors'
        assert all(store.get(x['id'])['body'] is None for x in store.batch_view(batch,'b')['messages'])
    finally: store.db.close()


def test_hash_routing_membership_scope_and_no_reassignment_after_dispatch(settings):
    fleet(settings);store=Store(settings)
    try:
        phone='+923001234567';ids={'nokia-01','nokia-02'}
        chosen=Store.hash_device(phone,ids);other=(ids-{chosen}).pop()
        assert Store.hash_device(phone,list(reversed(sorted(ids))))==chosen
        batch=store.add_bulk('b','auto',[(phone,'one'),(phone,'two')],'batch','hash',ids)
        store.pump(ids);messages=store.batch_view(batch,'b')['messages']
        assert {m['device_id'] for m in messages}=={chosen}
        first=store.next_job(chosen);store.pump({other})
        assert store.get(first['id'])['device']==chosen # Already dispatched: pinned.
        assert store.get(messages[1]['id'])['device']==other # Unsubmitted: safe to move.
        store.status(chosen,first['id'],'unknown','CALLBACK_TIMEOUT')
        store.pump({other});assert store.get(first['id'])['device']==chosen
        assert store.next_job(other)['id']==messages[1]['id']
        restricted=store.add_bulk('c','auto',[(phone,'private')],'restricted','hash2',['nokia-01'])
        store.pump({'nokia-02'})
        assert store.batch_view(restricted,'c')['counts']=={'buffered':1}
    finally: store.db.close()


def test_single_auto_uses_same_hash_and_survives_restart(settings):
    fleet(settings)
    with TestClient(create_app(settings)) as c:
        id=submit(c,device_id='auto').json()['id']
        assert c.app.state.store.get(id)['device']=='auto'
    with TestClient(create_app(settings)) as c:
        store=c.app.state.store;store.pump({'nokia-01','nokia-02'})
        assert store.get(id)['device']==Store.hash_device('+923001234567',{'nokia-01','nokia-02'})
        assert submit(c,device_id='auto',device='illegal').status_code==422


def test_batch_restart_and_payload_expiry_preserve_idempotency(settings):
    store=Store(settings)
    id=store.add_bulk('b','auto',[('+923001234567','private')],'durable','hash',['nokia-01']);store.db.close()
    store=Store(settings)
    try:
        assert store.add_bulk('b','auto',[('+923001234567','private')],'durable','hash',['nokia-01'])==id
        assert store.batch_view(id,'b')['counts']=={'buffered':1}
        store.db.execute('UPDATE messages SET created=?',(time.time()-31*86400,));store.maintain()
        item=store.batch_view(id,'b')['messages'][0]
        assert item['status']=='failed' and item['error_code']=='EXPIRED'
        assert store.get(item['id'])['body'] is None
        assert store.add_bulk('b','auto',[('+923001234567','private')],'durable','hash',['nokia-01'])==id
    finally: store.db.close()


def test_per_caller_backlog_limit(client,settings):
    settings.bulk_pending_limit=2
    assert bulk(client).status_code==202
    assert client.post('/v1/messages/bulk',json=PAYLOAD,headers=AUTH).json()['detail']=='BULK_BACKLOG_FULL'
    assert submit(client).json()['detail']=='BULK_BACKLOG_FULL'


def test_real_websocket_one_at_a_time_batch_delivery(client):
    batch=bulk(client).json()
    with client.websocket_connect('/ws/device') as ws:
        assert hello(ws)['max_inflight']==1
        heartbeat(ws)
        first=ws.receive_json();assert first['type']=='send_sms' and first['text']=='Hi Ali, your code is 1234.'
        assert client.app.state.store.next_job('nokia-01') is None
        report(ws,first['id'],'sent')
        second=ws.receive_json();assert second['text']=='Hi Sara, your code is 5678.'
        report(ws,second['id'],'sent')
    assert client.get('/v1/batches/'+batch['id'],headers=AUTH).json()['status']=='completed'


def test_batch_insert_failure_rolls_back_every_item(client):
    db=client.app.state.store.db
    db.execute("CREATE TRIGGER fail_second BEFORE INSERT ON batch_items WHEN NEW.idx=1 BEGIN SELECT RAISE(ABORT,'simulated storage failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        client.app.state.store.add_bulk('b','auto',[('+923001234567','one'),('+923001234568','two')],'atomic','hash',['nokia-01'])
    assert db.execute('SELECT count(*) FROM messages').fetchone()[0]==0
    assert db.execute('SELECT count(*) FROM batches').fetchone()[0]==0
    assert db.execute('SELECT count(*) FROM audit').fetchone()[0]==0


def test_multi_device_websocket_hash_and_scope(settings):
    fleet(settings)
    with TestClient(create_app(settings)) as c:
        with c.websocket_connect('/ws/device') as one,c.websocket_connect('/ws/device') as two:
            hello(one);heartbeat(one)
            two.send_json({'type':'hello','protocol':1,'device_id':'nokia-02','token':'second-device-credential-32-characters'})
            assert two.receive_json()['type']=='hello_ack';heartbeat(two)
            # Select a number that hashes to the second phone in a two-device pool.
            phone=next('+92300123'+str(i).zfill(4) for i in range(100) if Store.hash_device('+92300123'+str(i).zfill(4),{'nokia-01','nokia-02'})=='nokia-02')
            payload={'device_id':'auto','template':'Hi {name}','users':[{'phone':phone,'name':'Ali'}]}
            result=c.post('/v1/messages/bulk',json=payload,headers=AUTH).json()
            assert result['messages'][0]['device_id']=='nokia-02'
            job=two.receive_json();assert job['id']==result['messages'][0]['id']
            assert c.get('/v1/batches/'+result['id'],headers=AUTH).json()['status']=='processing'
            report(two,job['id'],'sent')
            # The other caller may use only device 01, even when phone hash prefers 02.
            restricted=c.post('/v1/messages/bulk',json=payload,headers={'Authorization':f'Bearer {OTHER}'}).json()
            assert restricted['messages'][0]['device_id']=='nokia-01'
            job=one.receive_json();report(one,job['id'],'sent')


def test_hash_distribution_and_minimal_remapping():
    phones=['+92300123'+str(i).zfill(4) for i in range(100)]
    assignments={phone:Store.hash_device(phone,{'nokia-01','nokia-02'}) for phone in phones}
    assert set(assignments.values())=={'nokia-01','nokia-02'}
    for phone,device in assignments.items():
        expanded=Store.hash_device(phone,{'nokia-01','nokia-02','nokia-03'})
        assert expanded in {device,'nokia-03'}
