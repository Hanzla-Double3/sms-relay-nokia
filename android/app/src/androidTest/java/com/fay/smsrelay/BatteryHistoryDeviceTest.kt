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
class BatteryHistoryDeviceTest {
    private val context=InstrumentationRegistry.getInstrumentation().targetContext
    private lateinit var history: BatteryHistory
    private lateinit var name: String
    private val now=2000000000L/BatteryHistory.MINUTE*BatteryHistory.MINUTE
    @Before fun setup() { name="battery-test-${UUID.randomUUID()}.db"; history=BatteryHistory(context,name) }
    @After fun cleanup() { history.close(); context.deleteDatabase(name) }
    @Test fun oneReadingPerMinuteSurvivesRestartAndPreservesChargingState() {
        history.record(BatterySample(now+1000,80,false,true))
        history.record(BatterySample(now+45000,79,true,true))
        history.record(BatterySample(now+60000,79,false,false))
        history.close(); history=BatteryHistory(context,name)
        val values=history.read(now,now+120000)
        assertEquals(2,values.size)
        assertEquals(BatterySample(now,80,false,true),values[0])
        assertEquals(BatterySample(now+60000,79,false,false),values[1])
    }
    @Test fun retentionAndWindowBoundsDoNotInventMissingSamples() {
        history.record(BatterySample(now,90,false,true))
        val later=now+BatteryHistory.RETENTION
        history.record(BatterySample(later,60,true,true))
        assertEquals(2,history.read(now,later).size)
        history.record(BatterySample(later+60000,61,true,true))
        val values=history.read(0,later+60000)
        assertEquals(listOf(later,later+60000),values.map { it.at })
        assertEquals(1,history.read(later+60000,later+60000).size)
        assertTrue(history.read(later+120000,later+120000).isEmpty())
    }
    @Test fun clockRollbackRemovesFutureSamplesAndInvalidReadingsAreRejected() {
        history.record(BatterySample(now+60000,70,false,true))
        history.record(BatterySample(now,71,false,true))
        assertEquals(listOf(now),history.read(0,now+60000).map { it.at })
        try { history.record(BatterySample(now+60000,101,false,true)); fail("Invalid battery reading accepted") } catch (_: IllegalArgumentException) { }
        assertEquals(1,history.read(0,now+60000).size)
    }
}
