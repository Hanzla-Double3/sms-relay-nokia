import json
import hmac
import secrets
import hashlib
import os
import sqlite3
import time
import uuid
from pathlib import Path
from fastapi import HTTPException
from .diagnostics import emit

RANK = {"buffered": -1, "queued": 0, "dispatched": 1, "phone_received": 2, "submitted_to_modem": 3, "sent": 4, "delivered": 5}
DEVICE_STATES = {"phone_received", "submitted_to_modem", "sent", "delivered", "failed", "unknown"}
TERMINAL = {"sent", "delivered", "failed", "unknown"}


def advance(current, incoming):
    if incoming == current:
        return current
    if current == "delivered":
        return current
    if incoming == "delivered":
        return incoming  # A receipt can arrive before the sent callback.
    if current == "sent":
        return current
    if current == "failed":
        return current
    if current == "unknown":
        return incoming if incoming in {"sent", "delivered", "failed"} else current
    if incoming in {"unknown", "failed"}:
        return incoming
    return incoming if RANK[incoming] > RANK[current] else current


class Store:
    def __init__(self, settings):
        self.settings = settings
        Path(settings.database).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(settings.database, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
        os.chmod(settings.database, 0o600)
        self.db = sqlite3.connect(settings.database, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=FULL;
        PRAGMA secure_delete=ON;
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS messages (
          id TEXT PRIMARY KEY, caller TEXT NOT NULL, device TEXT NOT NULL,
          recipient TEXT, body TEXT, payload_hash TEXT NOT NULL,
          idem TEXT, status TEXT NOT NULL, error_code TEXT,
          created REAL NOT NULL, updated REAL NOT NULL,
          dispatched REAL, attempt INTEGER NOT NULL DEFAULT 0,
          UNIQUE(caller, idem));
        CREATE INDEX IF NOT EXISTS jobs ON messages(device,status,created);
        CREATE TABLE IF NOT EXISTS audit (
          seq INTEGER PRIMARY KEY, message_id TEXT NOT NULL REFERENCES messages(id),
          status TEXT NOT NULL, error_code TEXT, at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS audit_message ON audit(message_id);
        CREATE TABLE IF NOT EXISTS diagnostics(seq INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, device TEXT, message_id TEXT, event TEXT NOT NULL, details TEXT NOT NULL, source_id TEXT, UNIQUE(device,source_id));
        CREATE INDEX IF NOT EXISTS diagnostic_message ON diagnostics(message_id,seq);
        CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY,caller TEXT NOT NULL,device TEXT NOT NULL,payload_hash TEXT NOT NULL,idem TEXT,created REAL NOT NULL,total INTEGER NOT NULL,UNIQUE(caller,idem));
        CREATE TABLE IF NOT EXISTS batch_items(batch_id TEXT NOT NULL REFERENCES batches(id),idx INTEGER NOT NULL,message_id TEXT NOT NULL UNIQUE REFERENCES messages(id),PRIMARY KEY(batch_id,idx));
        CREATE TABLE IF NOT EXISTS update_requests(device TEXT PRIMARY KEY, requested REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS rates(caller TEXT NOT NULL, at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, heartbeat REAL, telemetry TEXT);
        CREATE TABLE IF NOT EXISTS api_tokens (
          id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, token_sha256 TEXT NOT NULL UNIQUE,
          devices TEXT NOT NULL, admin INTEGER NOT NULL DEFAULT 0,
          source TEXT NOT NULL, created REAL NOT NULL, last_used REAL, revoked REAL);
        CREATE TABLE IF NOT EXISTS admin_sessions(nonce_sha256 TEXT PRIMARY KEY, expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS token_audit (
          seq INTEGER PRIMARY KEY, token_id TEXT NOT NULL REFERENCES api_tokens(id),
          action TEXT NOT NULL, at REAL NOT NULL);

        ''')
        # Additive migration preserves old jobs, caller keys and duplicate guards.
        if 'routing_devices' not in {r['name'] for r in self.db.execute('PRAGMA table_info(messages)')}:
            self.db.execute('ALTER TABLE messages ADD COLUMN routing_devices TEXT')
        self.db.execute("CREATE INDEX IF NOT EXISTS buffered_jobs ON messages(status,created)")
        self.db.execute('CREATE INDEX IF NOT EXISTS caller_rates ON rates(caller,at)')
        self.db.execute('CREATE INDEX IF NOT EXISTS caller_jobs ON messages(caller,status)')
        # Import old environment credentials once. A restart must never resurrect a revocation.
        for name, cfg in settings.callers.items():
            token_id = "env:" + name
            now = time.time()
            self.db.execute("BEGIN IMMEDIATE")
            try:
                result = self.db.execute("INSERT OR IGNORE INTO api_tokens(id,name,token_sha256,devices,admin,source,created) VALUES(?,?,?,?,?,'environment',?)",
                    (token_id,name,cfg["token_sha256"],json.dumps(cfg["devices"]),bool(cfg.get("admin",False)),now))
                if result.rowcount:
                    self.db.execute("INSERT INTO token_audit(token_id,action,at) VALUES(?,'imported',?)",(token_id,now))
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
        for device in settings.devices:
            self.db.execute("INSERT OR IGNORE INTO devices(id) VALUES (?)", (device,))

    def diagnostic(self,event,device=None,message_id=None,source_id=None,**details):
        try:
            now=time.time()
            result=self.db.execute("INSERT OR IGNORE INTO diagnostics(at,device,message_id,event,details,source_id) VALUES(?,?,?,?,?,?)",(now,device,message_id,event,json.dumps(details),source_id))
            if result.rowcount:
                self.db.execute("DELETE FROM diagnostics WHERE at<?",(now-7*86400,))
                self.db.execute("DELETE FROM diagnostics WHERE seq<=COALESCE((SELECT seq FROM diagnostics ORDER BY seq DESC LIMIT 1 OFFSET 9999),0)-1")
                emit(dict(at=now,event=event,device=device,message_id=message_id,**details))
        except (sqlite3.Error, OSError):
            # Logging must never turn a committed send or callback into a failure.
            pass

    def diagnostic_rows(self,message_id=None,limit=200):
        sql="SELECT at,device,message_id,event,details FROM diagnostics"
        args=[]
        if message_id: sql+=" WHERE message_id=?"; args.append(message_id)
        sql+=" ORDER BY seq DESC LIMIT ?"; args.append(limit)
        return [dict(at=r['at'],device=r['device'],message_id=r['message_id'],event=r['event'],details=json.loads(r['details'])) for r in reversed(self.db.execute(sql,args).fetchall())]

    def authenticate_caller(self, hashed):
        row = self.db.execute("SELECT * FROM api_tokens WHERE token_sha256=?",(hashed,)).fetchone()
        if not row or not hmac.compare_digest(row["token_sha256"],hashed) or row["revoked"] is not None:
            raise HTTPException(401,"UNAUTHORIZED")
        now = time.time()
        self.db.execute("UPDATE api_tokens SET last_used=? WHERE id=? AND (last_used IS NULL OR last_used<?)",(now,row["id"],now-60))
        scopes = [device for device in json.loads(row["devices"]) if device in self.settings.devices]
        return row["name"], {"devices":scopes,"admin":bool(row["admin"])}

    def tokens(self):
        return [{"id":r["id"],"name":r["name"],"devices":json.loads(r["devices"]),"admin":bool(r["admin"]),
                 "source":r["source"],"created":r["created"],"last_used":r["last_used"],"revoked":r["revoked"]}
                for r in self.db.execute("SELECT id,name,devices,admin,source,created,last_used,revoked FROM api_tokens ORDER BY created DESC,id")]

    def create_token(self, name, devices):
        if not devices or len(devices)!=len(set(devices)) or any(d not in self.settings.devices for d in devices):
            raise HTTPException(422,"INVALID_DEVICE_SCOPE")
        token = "fay_sms_" + secrets.token_urlsafe(32)
        token_id = "tok_" + uuid.uuid4().hex
        now = time.time()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute("INSERT INTO api_tokens(id,name,token_sha256,devices,source,created) VALUES(?,?,?,?,'dashboard',?)",
                (token_id,name,hashlib.sha256(token.encode()).hexdigest(),json.dumps(devices),now))
            self.db.execute("INSERT INTO token_audit(token_id,action,at) VALUES(?,'created',?)",(token_id,now))
            self.db.execute("COMMIT")
        except sqlite3.IntegrityError:
            self.db.execute("ROLLBACK")
            raise HTTPException(409,"TOKEN_NAME_EXISTS")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return {"id":token_id,"name":name,"devices":devices,"token":token}

    def revoke_token(self, token_id):
        now = time.time()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if not self.db.execute("SELECT 1 FROM api_tokens WHERE id=?",(token_id,)).fetchone():
                raise HTTPException(404,"TOKEN_NOT_FOUND")
            result = self.db.execute("UPDATE api_tokens SET revoked=? WHERE id=? AND revoked IS NULL",(now,token_id))
            if result.rowcount:
                self.db.execute("INSERT INTO token_audit(token_id,action,at) VALUES(?,'revoked',?)",(token_id,now))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def add(self, caller, device, recipient, body, idem, payload_hash, scope=None):
        now = time.time()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if idem:
                old = self.db.execute("SELECT * FROM messages WHERE caller=? AND idem=?", (caller, idem)).fetchone()
                if old:
                    if old["payload_hash"] != payload_hash:
                        raise HTTPException(409, "IDEMPOTENCY_CONFLICT")
                    self.db.execute("COMMIT")
                    return dict(old)
            self.db.execute("DELETE FROM rates WHERE at < ?", (now - 60,))
            if self.db.execute("SELECT count(*) FROM rates WHERE caller=?", (caller,)).fetchone()[0] >= self.settings.rate_per_minute:
                raise HTTPException(429, "RATE_LIMIT")
            if self.db.execute("SELECT count(*) FROM messages WHERE caller=? AND status NOT IN ('sent','delivered','failed','unknown')",(caller,)).fetchone()[0]>=self.settings.bulk_pending_limit:
                raise HTTPException(429,'BULK_BACKLOG_FULL')
            count = self.db.execute("SELECT count(*) FROM messages WHERE device=? AND status NOT IN ('sent','delivered','failed','unknown')", (device,)).fetchone()[0]
            if count >= self.settings.queue_limit:
                raise HTTPException(429, "QUEUE_FULL")
            msg_id = "sms_" + uuid.uuid4().hex
            self.db.execute("INSERT INTO messages(id,caller,device,recipient,body,payload_hash,idem,status,created,updated) VALUES(?,?,?,?,?,?,?,'queued',?,?)", (msg_id, caller, device, recipient, body, payload_hash, idem, now, now))
            if scope is not None: self.db.execute("UPDATE messages SET routing_devices=? WHERE id=?",(json.dumps(sorted(scope)),msg_id))
            self.db.execute("INSERT INTO audit(message_id,status,at) VALUES (?,'queued',?)", (msg_id, now))
            self.db.execute("INSERT INTO rates VALUES (?,?)", (caller, now))
            self.db.execute("COMMIT")
            return dict(self.db.execute("SELECT * FROM messages WHERE id=?", (msg_id,)).fetchone())
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def add_bulk(self,caller,device,rendered,idem,payload_hash,scope):
        now=time.time()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if idem:
                old=self.db.execute('SELECT * FROM batches WHERE caller=? AND idem=?',(caller,idem)).fetchone()
                if old:
                    if old['payload_hash']!=payload_hash: raise HTTPException(409,'IDEMPOTENCY_CONFLICT')
                    self.db.execute('COMMIT'); return old['id']
            if self.db.execute('SELECT count(*) FROM batches WHERE caller=? AND created>?',(caller,now-60)).fetchone()[0]>=self.settings.rate_per_minute:
                raise HTTPException(429,'RATE_LIMIT')
            # Bound the durable backlog per caller, including ordinary active jobs.
            pending=self.db.execute("SELECT count(*) FROM messages WHERE caller=? AND status NOT IN ('sent','delivered','failed','unknown')",(caller,)).fetchone()[0]
            if pending+len(rendered)>self.settings.bulk_pending_limit: raise HTTPException(429,'BULK_BACKLOG_FULL')
            batch='batch_'+uuid.uuid4().hex
            self.db.execute('INSERT INTO batches VALUES(?,?,?,?,?,?,?)',(batch,caller,device,payload_hash,idem,now,len(rendered)))
            for index,(recipient,body) in enumerate(rendered):
                id='sms_'+uuid.uuid4().hex
                body_hash=hashlib.sha256(json.dumps([device,recipient,body],ensure_ascii=True).encode()).hexdigest()
                self.db.execute("INSERT INTO messages(id,caller,device,recipient,body,payload_hash,status,created,updated,routing_devices) VALUES(?,?,?,?,?,?,'buffered',?,?,?)",(id,caller,device,recipient,body,body_hash,now,now,json.dumps(sorted(scope)) if device=='auto' else None))
                self.db.execute("INSERT INTO audit(message_id,status,at) VALUES(?,'buffered',?)",(id,now))
                self.db.execute('INSERT INTO batch_items VALUES(?,?,?)',(batch,index,id))
            self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction: self.db.execute('ROLLBACK')
            raise
        self.diagnostic('BULK_ACCEPTED',None,batch,caller=caller,total=len(rendered),routing=device)
        return batch

    @staticmethod
    def hash_device(recipient,devices):
        # Rendezvous hashing: membership/order independent, stable per recipient.
        return max(devices,key=lambda device:(hashlib.sha256((recipient+'\0'+device).encode()).digest(),device)) if devices else None

    def pump(self,available):
        """Only unsubmitted auto jobs may move; a dispatched ID remains pinned forever."""
        now=time.time()
        available=set(available)&set(self.settings.devices)
        if not available: return
        self.db.execute('BEGIN IMMEDIATE')
        changes=[]
        try:
            self.db.execute('DELETE FROM rates WHERE at<?',(now-60,))
            # Reassign only queued automatic jobs whose old device is unavailable.
            for row in self.db.execute("SELECT * FROM messages WHERE status='queued' AND routing_devices IS NOT NULL").fetchall():
                if row['device'] in available: continue
                scope=set(json.loads(row['routing_devices']))&available
                target=self.hash_device(row['recipient'],scope)
                if target and self.db.execute("SELECT count(*) FROM messages WHERE device=? AND status IN ('queued','dispatched','phone_received','submitted_to_modem')",(target,)).fetchone()[0]<self.settings.queue_limit:
                    self.db.execute('UPDATE messages SET device=?,updated=? WHERE id=?',(target,now,row['id']))
                    changes.append(('AUTO_ROUTED',target,row['id'],row['device']))
            # FIFO inside each caller's durable backlog; limited promotion batches keep ticks short.
            rates={r['caller']:r['n'] for r in self.db.execute('SELECT caller,count(*) n FROM rates GROUP BY caller')}
            available_ids=sorted(available)
            placeholders=','.join('?' for _ in available_ids)
            sql=f"SELECT * FROM messages m WHERE status='buffered' AND (device IN ({placeholders}) OR EXISTS (SELECT 1 FROM json_each(m.routing_devices) s WHERE s.value IN ({placeholders})))"
            args=available_ids+available_ids
            blocked=[caller for caller,count in rates.items() if count>=self.settings.rate_per_minute]
            if blocked:
                sql+=" AND caller NOT IN ("+','.join('?' for _ in blocked)+")"; args+=blocked
            rows=self.db.execute(sql+' ORDER BY created,rowid LIMIT 10000',args).fetchall()
            queues={r['device']:r['n'] for r in self.db.execute("SELECT device,count(*) n FROM messages WHERE status IN ('queued','dispatched','phone_received','submitted_to_modem') GROUP BY device")}
            promoted=0
            for row in rows:
                if rates.get(row['caller'],0)>=self.settings.rate_per_minute: continue
                target=row['device']
                if row['routing_devices'] is not None:
                    target=self.hash_device(row['recipient'],set(json.loads(row['routing_devices']))&available)
                if not target or target not in self.settings.devices or queues.get(target,0)>=self.settings.queue_limit: continue
                self.db.execute("UPDATE messages SET status='queued',device=?,updated=? WHERE id=?",(target,now,row['id']))
                self.db.execute("INSERT INTO audit(message_id,status,at) VALUES(?,'queued',?)",(row['id'],now))
                self.db.execute('INSERT INTO rates VALUES(?,?)',(row['caller'],now))
                rates[row['caller']]=rates.get(row['caller'],0)+1; queues[target]=queues.get(target,0)+1
                changes.append(('BULK_QUEUED',target,row['id'],row['device']))
                promoted+=1
                if promoted>=100: break
            self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction: self.db.execute('ROLLBACK')
            raise
        for event,target,id,previous in changes:
            self.diagnostic(event,target,id,previous_device=previous)

    def batch_view(self,batch,caller,offset=0,limit=100):
        row=self.db.execute('SELECT * FROM batches WHERE id=? AND caller=?',(batch,caller)).fetchone()
        if not row: raise HTTPException(404,'NOT_FOUND')
        counts={r['status']:r['n'] for r in self.db.execute('SELECT m.status,count(*) n FROM batch_items i JOIN messages m ON m.id=i.message_id WHERE i.batch_id=? GROUP BY m.status',(batch,))}
        pending=sum(counts.get(state,0) for state in ('buffered','queued','dispatched','phone_received','submitted_to_modem'))
        active=sum(counts.get(state,0) for state in ('dispatched','phone_received','submitted_to_modem'))
        state='processing' if pending and (active or pending!=row['total']) else 'queued' if pending else 'needs_review' if counts.get('unknown') else 'completed_with_errors' if counts.get('failed') else 'completed'
        items=[{'index':r['idx'],'id':r['id'],'device_id':None if r['device']=='auto' else r['device'],'status':r['status'],'error_code':r['error_code']} for r in self.db.execute('SELECT i.idx,m.id,m.device,m.status,m.error_code FROM batch_items i JOIN messages m ON m.id=i.message_id WHERE i.batch_id=? ORDER BY i.idx LIMIT ? OFFSET ?',(batch,limit,offset))]
        return dict(id=batch,status=state,total=row['total'],pending=pending,counts=counts,messages=items,next_offset=offset+len(items) if offset+len(items)<row['total'] else None)

    def next_job(self, device):
        now = time.time()
        row = self.db.execute("SELECT * FROM messages WHERE device=? AND (status='queued' OR (status='dispatched' AND dispatched<?)) ORDER BY created,rowid LIMIT 1", (device, now-self.settings.redispatch_seconds)).fetchone()
        if not row:
            return None
        # Bound jobs awaiting handset/modem confirmation. Redispatching the same ID
        # consumes its existing slot rather than requiring a new one.
        active = self.db.execute("SELECT count(*) FROM messages WHERE device=? AND id!=? AND status IN ('dispatched','phone_received','submitted_to_modem')", (device,row["id"])).fetchone()[0]
        if active >= self.settings.max_inflight:
            return None
        # Commit BEFORE writing to the socket. Redispatch only these two states, with the same id.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute("UPDATE messages SET status='dispatched',dispatched=?,updated=?,attempt=attempt+1 WHERE id=?", (now, now, row["id"]))
            self.db.execute("INSERT INTO audit(message_id,status,at) VALUES (?,'dispatched',?)", (row["id"], now))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        self.diagnostic("DISPATCH",device,row["id"],attempt=row["attempt"]+1)
        return dict(self.db.execute("SELECT * FROM messages WHERE id=?", (row["id"],)).fetchone())

    def status(self, device, msg_id, state, error):
        row = self.db.execute("SELECT * FROM messages WHERE id=? AND device=?", (msg_id, device)).fetchone()
        if not row:
            return False
        new = advance(row["status"], state)
        now = time.time()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            # Record only changed outcomes; duplicate reconnect reports do not grow history.
            if new != row["status"]:
                self.db.execute("INSERT INTO audit(message_id,status,error_code,at) VALUES (?,?,?,?)", (msg_id, new, error, now))
                self.db.execute("UPDATE messages SET status=?,error_code=?,updated=? WHERE id=?", (new, error if new in {"failed","unknown"} else None, now, msg_id))
            if new in TERMINAL:
                self.db.execute("UPDATE messages SET recipient=NULL,body=NULL WHERE id=?", (msg_id,))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        if new != row["status"]:
            self.diagnostic("STATUS_CHANGED",device,msg_id,previous=row["status"],status=new,error_code=error)
        return True

    def maintain(self):
        self.db.execute("DELETE FROM admin_sessions WHERE expires<=?",(time.time(),))
        now = time.time()
        self.db.execute("DELETE FROM diagnostics WHERE at<?",(now-7*86400,))
        # Callback silence is ambiguity, never a resend trigger.
        for row in self.db.execute("SELECT id,device FROM messages WHERE status IN ('phone_received','submitted_to_modem') AND updated<?", (now-self.settings.reconciliation_seconds,)).fetchall():
            self.status(row["device"], row["id"], "unknown", "CALLBACK_TIMEOUT")
        # Scrub old queued payloads; keep small idempotency tombstones indefinitely.
        for row in self.db.execute("SELECT id,device FROM messages WHERE body IS NOT NULL AND created<?", (now-self.settings.retention_days*86400,)).fetchall():
            self.status(row["device"], row["id"], "failed" if self.get(row["id"])["status"] in {"queued","buffered"} else "unknown", "EXPIRED")
        self.db.execute("DELETE FROM audit WHERE at<? AND seq NOT IN (SELECT max(seq) FROM audit GROUP BY message_id)", (now-self.settings.retention_days*86400,))

    def get(self, msg_id):
        row = self.db.execute("SELECT * FROM messages WHERE id=?", (msg_id,)).fetchone()
        return dict(row) if row else None

    def reconcile(self, device):
        return [r[0] for r in self.db.execute("SELECT id FROM messages WHERE device=? AND status IN ('phone_received','submitted_to_modem') ORDER BY created", (device,))]

    def heartbeat(self, device, telemetry):
        self.db.execute("UPDATE devices SET heartbeat=?,telemetry=? WHERE id=?", (time.time(), json.dumps(telemetry), device))
