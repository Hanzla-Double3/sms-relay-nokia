package com.fay.smsrelay

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class SendPolicyTest {
    @Test fun fastPacingAllowsOverlapWithoutWaitingForPreviousConfirmation() {
        val policy=SendPolicy(1000,10)
        assertEquals(0L,policy.waitMillis(10000,null,0))
        assertEquals(1000L,policy.waitMillis(10000,10000,1))
        assertEquals(600L,policy.waitMillis(10400,10000,1))
        assertEquals(0L,policy.waitMillis(11000,10000,1))
        assertNull(policy.waitMillis(11000,10000,10))
        assertEquals(0L,policy.waitMillis(11000,10000,9))
    }
    @Test fun oldServersKeepFiveSecondsAndInvalidPoliciesAreRejected() {
        assertEquals(SendPolicy(),SendPolicy.fromHello(JSONObject()))
        assertEquals(SendPolicy(1000,4),SendPolicy.fromHello(JSONObject().put("send_interval_ms",1000).put("max_inflight",4)))
        for(interval in listOf(0L,999L,60001L)) {
            try { SendPolicy(interval); fail("Unsafe interval") } catch (_: IllegalArgumentException) { }
        }
        for(limit in listOf(0L,11L,4294967306L)) {
            try { SendPolicy.fromHello(JSONObject().put("max_inflight",limit)); fail("Unsafe window") } catch (_: IllegalArgumentException) { }
        }
    }
}
