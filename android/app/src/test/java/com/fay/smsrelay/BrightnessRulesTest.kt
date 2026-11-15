package com.fay.smsrelay

import org.junit.Assert.*
import org.junit.Test

class BrightnessRulesTest {
    @Test fun darkRoomsDimAndSunlightIsBounded() {
        assertEquals(.05f,BrightnessRules.level(0f),.001f)
        assertEquals(.05f,BrightnessRules.level(-10f),.001f)
        assertEquals(.05f,BrightnessRules.level(Float.NaN),.001f)
        assertEquals(1f,BrightnessRules.level(100000f),.001f)
        val levels=listOf(0f,1f,10f,100f,1000f,10000f).map(BrightnessRules::level)
        assertTrue(levels.zipWithNext().all { (a,b) -> b>a })
        assertTrue(levels.all { it in .05f..1f })
    }
}
