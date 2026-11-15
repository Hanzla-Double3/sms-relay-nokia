package com.fay.smsrelay

object RelayRules {
    private val ranks = mapOf("phone_received" to 2, "submitted_to_modem" to 3, "sent" to 4, "delivered" to 5)
    val terminal = setOf("sent", "delivered", "failed", "unknown")
    fun advance(old: String, next: String): String = when {
        old == "delivered" -> old
        next == "delivered" -> next
        old == "sent" || old == "failed" -> old
        old == "unknown" -> if (next in setOf("sent", "delivered", "failed")) next else old
        next == "failed" || next == "unknown" -> next
        (ranks[next] ?: 0) > (ranks[old] ?: 0) -> next
        else -> old
    }
    // Any mix of successful and failed parts is partial/ambiguous, not safely retryable.
    fun aggregate(sent: List<Int?>, delivered: List<Boolean>): String? = when {
        delivered.isNotEmpty() && delivered.all { it } -> "delivered"
        sent.any { it != null && it != -1 } -> if (sent.all { it != null && it != -1 }) "failed" else "unknown"
        sent.isNotEmpty() && sent.all { it == -1 } -> "sent" // Activity.RESULT_OK
        else -> null
    }
    fun recover(state: String): String = if (state == "submitted_to_modem") "unknown" else state
    fun reconnectDelay(attempt: Int, jitter: Double): Long = ((1000L shl attempt.coerceIn(0, 6)).coerceAtMost(60000) * (0.75 + jitter.coerceIn(0.0,1.0)*0.5)).toLong()
    fun masked(number: String): String = if (number.length > 6) number.take(4) + "*****" + number.takeLast(2) else "***"
}
