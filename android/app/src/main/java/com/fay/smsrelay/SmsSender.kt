package com.fay.smsrelay

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.telephony.SmsManager
import org.json.JSONObject

class SmsSender(private val context: Context, private val ledger: Ledger) {
    fun send(job: Job, subscription: Int,signal: Int?=null) {
        if(job.state != "phone_received" || job.to == null || job.text == null) return
        @Suppress("DEPRECATION") val manager = SmsManager.getSmsManagerForSubscriptionId(subscription)
        val parts = manager.divideMessage(job.text)
        if(parts.size !in 1..16) { ledger.transition(job.id,"failed","TOO_MANY_SEGMENTS"); return }
        val sent = ArrayList<PendingIntent>(); val delivered = ArrayList<PendingIntent>()
        parts.indices.forEach { idx ->
            sent.add(callback(job.id,idx,"sent")); delivered.add(callback(job.id,idx,"delivered"))
        }
        ledger.prepareSubmission(job.id,parts.size)
        ledger.diagnostic(job.id,"MODEM_SUBMIT",JSONObject().put("parts",parts.size).put("subscription",subscription).put("text_chars",job.text.codePointCount(0,job.text.length)).also { if(signal!=null) it.put("signal_dbm",signal) })
        try {
            if(parts.size == 1) manager.sendTextMessage(job.to,null,parts[0],sent[0],delivered[0])
            else manager.sendMultipartTextMessage(job.to,null,parts,sent,delivered)
            // Submission state is not sent success. Only sent callbacks can establish that.
        } catch (_: SecurityException) { ledger.diagnostic(job.id,"SUBMISSION_ERROR"); ledger.transition(job.id,"failed","PERMISSION_DENIED")
        } catch (_: IllegalArgumentException) { ledger.diagnostic(job.id,"SUBMISSION_ERROR"); ledger.transition(job.id,"failed","INVALID_SMS")
        } catch (_: Exception) { ledger.diagnostic(job.id,"SUBMISSION_ERROR"); ledger.transition(job.id,"unknown","SUBMISSION_EXCEPTION")
        } finally { ledger.scrub(job.id) }
    }
    private fun callback(id: String, idx: Int, kind: String): PendingIntent {
        val intent = Intent(context,SmsResultReceiver::class.java).setAction("com.fay.smsrelay.$kind")
            .setData(Uri.parse("smsrelay://callback/$id/$kind/$idx")).putExtra("id",id).putExtra("part",idx).putExtra("kind",kind)
        // Framework callbacks need sent radio errors and delivery PDU fill-in extras. Explicit private receiver.
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or if(Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0
        return PendingIntent.getBroadcast(context,0,intent,flags)
    }
}
