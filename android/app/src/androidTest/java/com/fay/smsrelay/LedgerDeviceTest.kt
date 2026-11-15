package com.fay.smsrelay

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class LedgerDeviceTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private lateinit var ledger: Ledger
    private lateinit var name: String
    private val id = "sms_" + UUID.randomUUID().toString().replace("-","")
    @Before fun setup() { name="test-${UUID.randomUUID()}.db"; ledger=Ledger(context,name) }
    @After fun cleanup() { ledger.close(); context.deleteDatabase(name) }
    @Test fun duplicateAndCrashGuardSurviveDatabaseReopening() {
        assertTrue(ledger.receive(id,"+923001234567","Private test body"))
        assertFalse(ledger.receive(id,"+923001234567","Private test body"))
        assertEquals(1,ledger.pending().size)
        ledger.prepareSubmission(id,2)
        ledger.close(); ledger=Ledger(context,name); ledger.recover()
        assertEquals("unknown",ledger.get(id)?.state)
        assertNull(ledger.get(id)?.text)
        assertTrue(ledger.pending().isEmpty())
        assertFalse(ledger.receive(id,"+923001234567","Do not send again"))
    }
    @Test fun multipartCallbacksAndOldAckCannotLoseLatestState() {
        ledger.receive(id,"+923001234567","Private test body"); ledger.prepareSubmission(id,2)
        val before=ledger.get(id)!!.revision
        ledger.callback(id,0,"sent",-1,false)
        assertEquals("submitted_to_modem",ledger.get(id)?.state)
        ledger.callback(id,1,"sent",-1,false)
        assertEquals("sent",ledger.get(id)?.state)
        ledger.acknowledge(id,before)
        assertEquals(1,ledger.dirty().size)
        ledger.acknowledge(id,ledger.get(id)!!.revision)
        assertTrue(ledger.dirty().isEmpty())
        ledger.callback(id,0,"sent",1,false) // Duplicate error cannot overwrite success.
        assertEquals("sent",ledger.get(id)?.state)
    }
    @Test fun receivedJobsResumeButUnknownDoesNot() {
        ledger.receive(id,"+923001234567","Private test body")
        ledger.recover()
        assertEquals(1,ledger.pending().size)
        ledger.transition(id,"unknown","TEST_BOUNDARY")
        assertTrue(ledger.pending().isEmpty())
        assertNull(ledger.get(id)?.to)
    }
    @Test fun logsAreBoundedAndScrubbedStateStaysAsTombstone() {
        repeat(510) { ledger.log("[TEST] event") }
        assertEquals(500,ledger.readableDatabase.rawQuery("SELECT count(*) FROM logs",null).use { it.moveToFirst(); it.getInt(0) })
        ledger.missing(id)
        assertEquals("unknown",ledger.get(id)?.state)
        assertEquals("LEDGER_MISSING",ledger.get(id)?.error)
    }
    @Test fun idleLogReadsExpireOldEventsWithoutDeletingSmsGuards() {
        ledger.missing(id)
        ledger.writableDatabase.execSQL("DELETE FROM logs")
        val now=System.currentTimeMillis()
        ledger.writableDatabase.execSQL("INSERT INTO logs(at,event) VALUES(?,?)",arrayOf<Any>(now-3600001L,"expired"))
        ledger.writableDatabase.execSQL("INSERT INTO logs(at,event) VALUES(?,?)",arrayOf<Any>(now-1800000L,"recent"))
        assertEquals(listOf("recent"),ledger.logs().map { it.second })
        assertEquals(1,ledger.readableDatabase.rawQuery("SELECT count(*) FROM logs",null).use { it.moveToFirst(); it.getInt(0) })
        assertEquals("unknown",ledger.get(id)?.state)
        assertFalse(ledger.receive(id,"+923001234567","Never send duplicate"))
        ledger.writableDatabase.execSQL("UPDATE logs SET at=?",arrayOf<Any>(now-3600001L))
        ledger.expire()
        assertTrue(ledger.logs().isEmpty())
    }

    @Test fun lastSentSurvivesLogExpiryAndLateDeliveryDoesNotChangeItsTime() {
        assertNull(ledger.lastSent())
        ledger.receive(id,"+923001234567","Private test body")
        ledger.prepareSubmission(id,1)
        assertNull(ledger.lastSent())
        ledger.callback(id,0,"sent",-1,false)
        val sent=ledger.lastSent()
        assertEquals(id,sent?.second)
        ledger.writableDatabase.execSQL("DELETE FROM logs")
        ledger.callback(id,0,"delivery",-1,true)
        assertEquals(sent,ledger.lastSent())
        ledger.close(); ledger=Ledger(context,name)
        assertEquals(sent,ledger.lastSent())
    }
    @Test fun versionOneUpgradePreservesDuplicateGuardsAndOldConfirmedSend() {
        ledger.close(); context.deleteDatabase(name)
        android.database.sqlite.SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath(name),null).use { db ->
            db.execSQL("CREATE TABLE jobs(id TEXT PRIMARY KEY, recipient TEXT, body TEXT, state TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, dirty INTEGER NOT NULL DEFAULT 1, error TEXT, updated INTEGER NOT NULL)")
            db.execSQL("CREATE TABLE parts(job TEXT NOT NULL REFERENCES jobs(id), idx INTEGER NOT NULL, sent INTEGER, delivered INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(job,idx))")
            db.execSQL("CREATE TABLE logs(seq INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL, event TEXT NOT NULL)")
            db.execSQL("INSERT INTO jobs(id,state,updated) VALUES(?,?,?)",arrayOf<Any>(id,"sent",123456L))
            db.version=1
        }
        ledger=Ledger(context,name)
        assertEquals(123456L to id,ledger.lastSent())
        assertFalse(ledger.receive(id,"+923001234567","Never send duplicate"))
        assertEquals("sent",ledger.get(id)?.state)
    }

    @Test fun diagnosticOutboxAcknowledgesExpiresAndKeepsGuards() {
        ledger.receive(id,"+923001234567","Private test body")
        val received=ledger.diagnosticOutbox().single()
        assertFalse(received.toString().contains("Private test body"))
        assertFalse(received.toString().contains("+923001234567"))
        ledger.diagnosticAck(received.getString("id"))
        assertTrue(ledger.diagnosticOutbox().isEmpty())
        ledger.diagnostic(id,"MODEM_CALLBACK",org.json.JSONObject().put("result",-1).put("part",0))
        ledger.close();ledger=Ledger(context,name)
        assertEquals("MODEM_CALLBACK",ledger.diagnosticOutbox().single().getString("event"))
        ledger.writableDatabase.execSQL("UPDATE diagnostics SET at=?",arrayOf<Any>(System.currentTimeMillis()-3600001L))
        ledger.expire()
        assertTrue(ledger.diagnosticOutbox().isEmpty())
        assertFalse(ledger.receive(id,"+923001234567","Never duplicate"))
    }
    @Test fun diagnosticRingIsBoundedIndependentlyOfSmsLedger() {
        repeat(510) { ledger.diagnostic(id,"MODEM_CALLBACK") }
        assertEquals(500,ledger.readableDatabase.rawQuery("SELECT count(*) FROM diagnostics",null).use { it.moveToFirst();it.getInt(0) })
    }

}
