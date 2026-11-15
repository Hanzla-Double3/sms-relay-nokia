package com.fay.smsrelay

import android.content.Intent
import android.os.BatteryManager

object PowerState {
    fun charging(battery: Intent?): Boolean {
        if(ChargeControl.state=="PAUSED_TO_60") return false
        val status=battery?.getIntExtra(BatteryManager.EXTRA_STATUS,-1) ?: -1
        return status==BatteryManager.BATTERY_STATUS_CHARGING || (status==BatteryManager.BATTERY_STATUS_FULL && (battery?.getIntExtra(BatteryManager.EXTRA_PLUGGED,0) ?: 0)!=0)
    }
}
