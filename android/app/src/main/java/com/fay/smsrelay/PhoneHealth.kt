package com.fay.smsrelay

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.telephony.SubscriptionManager
import android.telephony.TelephonyManager
import android.telephony.PhoneStateListener
import android.telephony.ServiceState

data class PhoneHealth(val ready: Boolean, val code: String, val subscription: Int, val sim: Boolean, val permission: Boolean, val signal: Int?, val signalLevel: Int? = null) {
    companion object {
        fun read(context: Context, configured: Int): PhoneHealth {
            val sms = context.checkSelfPermission(Manifest.permission.SEND_SMS) == PackageManager.PERMISSION_GRANTED
            val phone = context.checkSelfPermission(Manifest.permission.READ_PHONE_STATE) == PackageManager.PERMISSION_GRANTED
            if(!sms || !phone) return PhoneHealth(false,"PERMISSION_REQUIRED",-1,false,sms,null)
            return try {
                val subs = context.getSystemService(SubscriptionManager::class.java).activeSubscriptionInfoList.orEmpty()
                if(subs.isEmpty()) return PhoneHealth(false,"NO_SIM",-1,false,true,null)
                val default = SubscriptionManager.getDefaultSmsSubscriptionId()
                val chosen = if(configured >= 0) configured else if(subs.any { it.subscriptionId == default }) default else if(subs.size == 1) subs[0].subscriptionId else -1
                if(subs.none { it.subscriptionId == chosen }) return PhoneHealth(false,"SELECT_SIM",-1,true,true,null)
                val tm = context.getSystemService(TelephonyManager::class.java).createForSubscriptionId(chosen)
                val sim = tm.simState == TelephonyManager.SIM_STATE_READY
                PhoneMonitor.observe(context,tm,chosen)
                val registered = PhoneMonitor.state == ServiceState.STATE_IN_SERVICE
                val strength = tm.signalStrength?.cellSignalStrengths?.firstOrNull { it.dbm != Int.MAX_VALUE }
                PhoneHealth(sim && registered, if(!sim) "SIM_NOT_READY" else if(!registered) "NO_SERVICE" else "READY",chosen,sim,true,strength?.dbm,strength?.level)
            } catch (_: SecurityException) { PhoneHealth(false,"PERMISSION_REQUIRED",-1,false,sms,null) }
        }
    }
}

// Service-state callbacks provide registration health without requesting location.
@Suppress("DEPRECATION")
private object PhoneMonitor {
    @Volatile var state: Int? = null
    private var subscription = -1
    private var manager: TelephonyManager? = null
    private var listener: PhoneStateListener? = null
    @Synchronized fun observe(context: Context, tm: TelephonyManager, selected: Int) {
        if(subscription == selected) return
        if(context.checkSelfPermission(Manifest.permission.READ_PHONE_STATE) != PackageManager.PERMISSION_GRANTED) return
        listener?.let { manager?.listen(it,PhoneStateListener.LISTEN_NONE) }
        state = null
        val next = object: PhoneStateListener(context.mainExecutor) {
            override fun onServiceStateChanged(serviceState: ServiceState) { state = serviceState.state }
        }
        tm.listen(next,PhoneStateListener.LISTEN_SERVICE_STATE)
        subscription = selected; manager = tm; listener = next
    }
}
