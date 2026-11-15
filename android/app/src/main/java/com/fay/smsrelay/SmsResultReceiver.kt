package com.fay.smsrelay

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.telephony.SmsMessage
import java.util.concurrent.Executors
import org.json.JSONObject

object RelayRuntime {
    val executor = Executors.newSingleThreadScheduledExecutor()
    @Volatile var connection = "STOPPED"
    @Volatile var startedAt = 0L
    @Volatile var lastPingMs = 0L
    @Volatile var onSmsStatusChanged: (() -> Unit)? = null
}

class SmsResultReceiver: BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val id = intent.getStringExtra("id") ?: return
        val kind = intent.getStringExtra("kind") ?: return
        val idx = intent.getIntExtra("part",-1)
        if(!id.matches(Regex("sms_[a-f0-9]{32}")) || kind !in setOf("sent","delivered") || idx !in 0..15) return
        val code = resultCode
        val pdu = intent.getByteArrayExtra("pdu")
        val report=if(kind=="delivered" && pdu!=null) try { SmsMessage.createFromPdu(pdu,intent.getStringExtra("format") ?: "3gpp") } catch (_: Exception) { null } else null
        val deliveryOk=kind=="delivered" && code==android.app.Activity.RESULT_OK && report!=null && report.status in 0..31
        val details=JSONObject().put("part",idx).put("result",code)
        if(intent.hasExtra("errorCode")) details.put("radio_error",intent.getIntExtra("errorCode",-1))
        if(kind=="delivered") {
            details.put("has_pdu",pdu!=null).put("pdu_decoded",report!=null)
            report?.let { details.put("delivery_status",it.status) }
        }
        val pending = goAsync()
        RelayRuntime.executor.execute {
            try {
                val ledger=Ledger.get(context)
                ledger.diagnostic(id,if(kind=="sent") "MODEM_CALLBACK" else "DELIVERY_CALLBACK",details)
                ledger.callback(id,idx,kind,code,deliveryOk)
                RelayRuntime.onSmsStatusChanged?.invoke()
            } finally { pending.finish() }
        }
    }
}
