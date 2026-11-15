package com.fay.smsrelay
import org.junit.Assert.*
import org.junit.Test
class RelayRulesTest {
    @Test fun noRegressionAfterSent() { assertEquals("sent",RelayRules.advance("sent","submitted_to_modem")); assertEquals("sent",RelayRules.advance("sent","unknown")) }
    @Test fun crashBoundaryIsUnknown() { assertEquals("unknown",RelayRules.recover("submitted_to_modem")); assertEquals("phone_received",RelayRules.recover("phone_received")) }
    @Test fun unknownCanBeResolvedByCallbacks() { assertEquals("sent",RelayRules.advance("unknown","sent")); assertEquals("unknown",RelayRules.advance("unknown","phone_received")) }
    @Test fun multipartWaitsForEveryPart() { assertNull(RelayRules.aggregate(listOf(-1,null),listOf(false,false))); assertEquals("sent",RelayRules.aggregate(listOf(-1,-1),listOf(false,false))) }
    @Test fun partialFailureIsNotRetryable() { assertEquals("unknown",RelayRules.aggregate(listOf(-1,1),listOf(false,false))); assertEquals("unknown",RelayRules.aggregate(listOf(null,1),listOf(false,false))); assertEquals("failed",RelayRules.aggregate(listOf(1,2),listOf(false,false))) }
    @Test fun deliveryCanPrecedeSent() { assertEquals("delivered",RelayRules.aggregate(listOf(null,null),listOf(true,true))); assertEquals("delivered",RelayRules.advance("submitted_to_modem","delivered")) }
    @Test fun backoffIsBoundedWithJitter() { assertTrue(RelayRules.reconnectDelay(50,1.0) <= 75000); assertTrue(RelayRules.reconnectDelay(0,0.0) >= 750) }
    @Test fun recipientsAreMasked() { assertEquals("+923*****67",RelayRules.masked("+923001234567")); assertEquals("***",RelayRules.masked("123")) }
}
