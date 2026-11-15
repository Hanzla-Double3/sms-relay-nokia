package com.fay.smsrelay

import org.json.JSONObject

/** Authenticated server policy; old servers retain the existing five-second pacing. */
data class SendPolicy(val intervalMs: Long=5000, val maxInFlight: Int=10) {
    init { require(intervalMs in 1000..60000 && maxInFlight in 1..10) }
    // A full window waits for callbacks or maintenance, not another busy polling loop.
    fun waitMillis(now: Long, lastSubmission: Long?, inFlight: Int): Long? =
        if(inFlight>=maxInFlight) null else lastSubmission?.let { (intervalMs-(now-it)).coerceAtLeast(0) } ?: 0
    companion object {
        fun fromHello(data: JSONObject): SendPolicy {
            val interval=if(data.has("send_interval_ms")) data.getLong("send_interval_ms") else 5000L
            val limit=if(data.has("max_inflight")) data.getLong("max_inflight") else 10L
            require(limit in 1..10)
            return SendPolicy(interval,limit.toInt())
        }
    }
}
