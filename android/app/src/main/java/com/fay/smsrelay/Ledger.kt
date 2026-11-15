package com.fay.smsrelay

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONObject

data class Job(val id: String, val to: String?, val text: String?, val state: String, val revision: Int, val error: String?, val updated: Long)

class Ledger internal constructor(context: Context, databaseName: String = "relay.db"): SQLiteOpenHelper(context.applicationContext, databaseName, null, 3) {
    companion object {
        @Volatile private var instance: Ledger? = null
        fun get(context: Context): Ledger = instance ?: synchronized(this) { instance ?: Ledger(context).also { instance = it } }
    }
    override fun onConfigure(db: SQLiteDatabase) { db.execSQL("PRAGMA synchronous=FULL"); db.rawQuery("PRAGMA secure_delete=ON",null).use { it.moveToFirst() }; db.setForeignKeyConstraintsEnabled(true) }
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE jobs(id TEXT PRIMARY KEY, recipient TEXT, body TEXT, state TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, dirty INTEGER NOT NULL DEFAULT 1, error TEXT, updated INTEGER NOT NULL, sent_at INTEGER)")
        db.execSQL("CREATE TABLE parts(job TEXT NOT NULL REFERENCES jobs(id), idx INTEGER NOT NULL, sent INTEGER, delivered INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(job,idx))")
        db.execSQL("CREATE TABLE logs(seq INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL, event TEXT NOT NULL)")
        createDiagnostics(db)
    }
    private fun createDiagnostics(db: SQLiteDatabase) { db.execSQL("CREATE TABLE diagnostics(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, at INTEGER NOT NULL, job TEXT NOT NULL, event TEXT NOT NULL, details TEXT NOT NULL, uploaded INTEGER NOT NULL DEFAULT 0)") }
    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        check(oldVersion in 1..2 && newVersion==3) { "Unsupported ledger migration" }
        if(oldVersion==1) db.execSQL("ALTER TABLE jobs ADD COLUMN sent_at INTEGER")
        createDiagnostics(db)
    }
    @Synchronized fun diagnostic(job: String,event: String,details: JSONObject=JSONObject()) {
        try {
        pruneDiagnostics()
        writableDatabase.insertOrThrow("diagnostics",null,ContentValues().apply {
            put("id","diag_"+java.util.UUID.randomUUID().toString().replace("-","")); put("at",System.currentTimeMillis()); put("job",job); put("event",event); put("details",details.toString())
        })
        writableDatabase.execSQL("DELETE FROM diagnostics WHERE seq NOT IN (SELECT seq FROM diagnostics ORDER BY seq DESC LIMIT 500)")
        log("[$event] $job $details")
        } catch (_: Exception) { /* Diagnostics must not interrupt durable SMS state changes. */ }
    }

    private fun pruneDiagnostics() { writableDatabase.execSQL("DELETE FROM diagnostics WHERE at<?",arrayOf(System.currentTimeMillis()-3600000L)) }
    @Synchronized fun diagnosticOutbox(): List<JSONObject> {
        pruneDiagnostics()
        val result=mutableListOf<JSONObject>()
        readableDatabase.rawQuery("SELECT id,at,job,event,details FROM diagnostics WHERE uploaded=0 ORDER BY seq LIMIT 20",null).use { c ->
            while(c.moveToNext()) result.add(JSONObject().put("type","diagnostic").put("id",c.getString(0)).put("at",c.getLong(1)).put("message_id",c.getString(2)).put("event",c.getString(3)).put("details",JSONObject(c.getString(4))))
        }
        return result
    }
    @Synchronized fun diagnosticAck(id: String) { writableDatabase.execSQL("UPDATE diagnostics SET uploaded=1 WHERE id=?",arrayOf(id)) }
    private fun row(cursor: android.database.Cursor): Job = Job(cursor.getString(0), cursor.getString(1), cursor.getString(2), cursor.getString(3), cursor.getInt(4), cursor.getString(5), cursor.getLong(6))
    @Synchronized fun get(id: String): Job? = readableDatabase.rawQuery("SELECT id,recipient,body,state,revision,error,updated FROM jobs WHERE id=?", arrayOf(id)).use { if(it.moveToFirst()) row(it) else null }
    @Synchronized fun receive(id: String, to: String, text: String): Boolean {
        val result = writableDatabase.insertWithOnConflict("jobs", null, ContentValues().apply {
            put("id",id); put("recipient",to); put("body",text); put("state","phone_received"); put("updated",System.currentTimeMillis())
        }, SQLiteDatabase.CONFLICT_IGNORE)
        if(result == -1L) { diagnostic(id,"JOB_DUPLICATE"); markDirty(id); return false }
        diagnostic(id,"JOB_RECEIVED")
        return true
    }
    @Synchronized fun transition(id: String, next: String, error: String? = null) {
        val old = get(id) ?: return
        val state = RelayRules.advance(old.state, next)
        if(state == old.state) return
        writableDatabase.update("jobs", ContentValues().apply {
            put("state",state); if(state in setOf("sent","delivered") && old.state !in setOf("sent","delivered")) put("sent_at",System.currentTimeMillis()); put("revision",old.revision+1); put("dirty",1); put("updated",System.currentTimeMillis())
            if(state in setOf("failed","unknown")) put("error",error) else putNull("error")
            if(state in RelayRules.terminal) { putNull("recipient"); putNull("body") }
        }, "id=?", arrayOf(id))
        log("[${state.uppercase()}] $id" + (if(error != null) " $error" else ""))
    }
    @Synchronized fun prepareSubmission(id: String, count: Int) {
        val db = writableDatabase
        db.beginTransaction()
        try {
            check(get(id)?.state == "phone_received")
            repeat(count) { idx -> db.insertOrThrow("parts",null,ContentValues().apply { put("job",id); put("idx",idx) }) }
            // Durable guard BEFORE SmsManager. A crash after this point is UNKNOWN on recovery.
            transition(id,"submitted_to_modem")
            db.setTransactionSuccessful()
        } finally { db.endTransaction() }
    }
    @Synchronized fun scrub(id: String) { writableDatabase.execSQL("UPDATE jobs SET recipient=NULL,body=NULL WHERE id=?", arrayOf(id)) }
    @Synchronized fun callback(id: String, index: Int, kind: String, result: Int, deliveredOk: Boolean) {
        val values = ContentValues().apply { if(kind == "sent") put("sent",result) else if(deliveredOk) put("delivered",1) }
        if(values.size() == 0) return
        // Duplicate callbacks cannot overwrite the first known per-part result.
        writableDatabase.update("parts", values, "job=? AND idx=?" + (if(kind == "sent") " AND sent IS NULL" else ""), arrayOf(id,index.toString()))
        val sent = mutableListOf<Int?>(); val delivered = mutableListOf<Boolean>()
        readableDatabase.rawQuery("SELECT sent,delivered FROM parts WHERE job=? ORDER BY idx",arrayOf(id)).use { c ->
            while(c.moveToNext()) { sent.add(if(c.isNull(0)) null else c.getInt(0)); delivered.add(c.getInt(1)==1) }
        }
        val state = RelayRules.aggregate(sent,delivered) ?: return
        val code = if(state == "unknown") "PARTIAL_OR_PENDING" else if(state == "failed") when(sent.firstOrNull()) {
            android.telephony.SmsManager.RESULT_ERROR_NO_SERVICE -> "NO_SERVICE"
            android.telephony.SmsManager.RESULT_ERROR_RADIO_OFF -> "RADIO_OFF"
            android.telephony.SmsManager.RESULT_ERROR_NULL_PDU -> "NULL_PDU"
            else -> "MODEM_REJECTED"
        } else null
        transition(id,state,code)
    }
    @Synchronized fun recover() {
        readableDatabase.rawQuery("SELECT id FROM jobs WHERE state='submitted_to_modem'",null).use { c -> while(c.moveToNext()) transition(c.getString(0),"unknown","PROCESS_RESTART") }
    }
    @Synchronized fun expire() {
        val deadline = (System.currentTimeMillis()-300000).toString()
        readableDatabase.rawQuery("SELECT id FROM jobs WHERE state='submitted_to_modem' AND updated<?",arrayOf(deadline)).use { c -> while(c.moveToNext()) transition(c.getString(0),"unknown","CALLBACK_TIMEOUT") }
        readableDatabase.rawQuery("SELECT id FROM jobs WHERE state='phone_received' AND updated<?",arrayOf(deadline)).use { c -> while(c.moveToNext()) transition(c.getString(0),"failed","NOT_SUBMITTED_TIMEOUT") }
        writableDatabase.execSQL("DELETE FROM logs WHERE at<?", arrayOf(System.currentTimeMillis()-3600000L))
        pruneDiagnostics()
    }
    @Synchronized fun markDirty(id: String) { writableDatabase.execSQL("UPDATE jobs SET dirty=1 WHERE id=?", arrayOf(id)) }
    @Synchronized fun replay() { writableDatabase.execSQL("UPDATE jobs SET dirty=1") }
    @Synchronized fun acknowledge(id: String, revision: Int) { writableDatabase.execSQL("UPDATE jobs SET dirty=0 WHERE id=? AND revision=?",arrayOf<Any>(id,revision)) }
    @Synchronized fun dirty(): List<JSONObject> {
        val result = mutableListOf<JSONObject>()
        readableDatabase.rawQuery("SELECT id,recipient,body,state,revision,error,updated FROM jobs WHERE dirty=1 ORDER BY updated LIMIT 100",null).use { c ->
            while(c.moveToNext()) { val j = row(c); result.add(JSONObject().put("type","sms_status").put("id",j.id).put("status",j.state).put("revision",j.revision).also { if(j.error != null) it.put("error_code",j.error) }) }
        }
        return result
    }
    @Synchronized fun pending(): List<Job> {
        val result = mutableListOf<Job>()
        readableDatabase.rawQuery("SELECT id,recipient,body,state,revision,error,updated FROM jobs WHERE state='phone_received' ORDER BY updated",null).use { c -> while(c.moveToNext()) result.add(row(c)) }
        return result
    }
    @Synchronized fun missing(id: String) {
        writableDatabase.insertWithOnConflict("jobs", null, ContentValues().apply { put("id",id); put("state","unknown"); put("error","LEDGER_MISSING"); put("updated",System.currentTimeMillis()) }, SQLiteDatabase.CONFLICT_IGNORE)
        markDirty(id)
    }
    @Synchronized fun log(event: String) {
        pruneLogs()
        writableDatabase.insert("logs",null,ContentValues().apply { put("at",System.currentTimeMillis()); put("event",event.take(180)) })
        writableDatabase.execSQL("DELETE FROM logs WHERE seq NOT IN (SELECT seq FROM logs ORDER BY seq DESC LIMIT 500)")
    }
    private fun pruneLogs() { pruneDiagnostics(); writableDatabase.execSQL("DELETE FROM logs WHERE at<?", arrayOf(System.currentTimeMillis()-3600000L)) }
    @Synchronized fun logs(): List<Pair<Long,String>> {
        pruneLogs()
        val result = mutableListOf<Pair<Long,String>>()
        readableDatabase.rawQuery("SELECT at,event FROM logs ORDER BY seq DESC LIMIT 100",null).use { c -> while(c.moveToNext()) result.add(c.getLong(0) to c.getString(1)) }
        return result.reversed()
    }
    @Synchronized fun lastSent(): Pair<Long,String>? = readableDatabase.rawQuery(
        "SELECT COALESCE(sent_at,updated),id FROM jobs WHERE state IN ('sent','delivered') ORDER BY COALESCE(sent_at,updated) DESC LIMIT 1",null
    ).use { if(it.moveToFirst()) it.getLong(0) to it.getString(1) else null }
    @Synchronized fun inFlight(): Int = readableDatabase.rawQuery("SELECT count(*) FROM jobs WHERE state='submitted_to_modem'",null).use { it.moveToFirst(); it.getInt(0) }
    @Synchronized fun counts(): Map<String,Int> {
        val result = mutableMapOf<String,Int>()
        readableDatabase.rawQuery("SELECT state,count(*) FROM jobs GROUP BY state",null).use { c -> while(c.moveToNext()) result[c.getString(0)] = c.getInt(1) }
        return result
    }
}
