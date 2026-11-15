package com.fay.smsrelay

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class BootReceiver: BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if(intent.action !in setOf(Intent.ACTION_BOOT_COMPLETED,Intent.ACTION_MY_PACKAGE_REPLACED)) return
        if(!Config(context).enabled) return
        try { context.startForegroundService(Intent(context,RelayService::class.java)) }
        catch (_: Exception) { Ledger.get(context).log("[BOOT] Startup restricted; open app and Start") }
    }
}
