package com.fay.smsrelay

import android.content.Context
import android.os.Build
import java.util.concurrent.Executors

/** Local-only fixed hardware control; no server payload can reach this root command. */
object ChargeControl {
    @Volatile var state="OFF"
        private set
    private val worker=Executors.newSingleThreadExecutor()
    private var process: Process?=null
    private var attempted=false
    private var generation=0
    @Synchronized fun sync(context: Context, retry: Boolean=false) {
        val config=Config(context)
        if(!config.enabled || !config.chargeLimit) { stop(); return }
        if(process!=null || (attempted && !retry)) return
        attempted=true
        if(Build.MODEL!="Nokia 2.2" || Build.HARDWARE!="mt6761") { state="UNSUPPORTED"; return }
        state="WAITING_FOR_ROOT"
        val epoch=++generation
        val script=context.resources.openRawResource(R.raw.charge_guardian).bufferedReader().use { it.readText() }
            .replace("__APP_PID__",android.os.Process.myPid().toString())
        try {
            val child=Runtime.getRuntime().exec(arrayOf("su","-c",script))
            process=child
            worker.execute {
                var failed=false
                try {
                    child.inputStream.bufferedReader().useLines { lines -> lines.forEach { value ->
                        synchronized(this) {
                            if(epoch==generation && value in setOf("CHARGING_LIMITED","PAUSED_TO_60","UNSUPPORTED","CONTROL_ERROR","CONTROL_BUSY","ROOT_REQUIRED")) {
                                state=value; failed=value !in setOf("CHARGING_LIMITED","PAUSED_TO_60")
                            }
                        }
                    } }
                    child.waitFor()
                } catch (_: Exception) { failed=true }
                finally { synchronized(this) {
                    if(epoch==generation) { process=null; if(!failed) state="ROOT_REQUIRED" }
                } }
            }
        } catch (_: Exception) { process=null; state="ROOT_REQUIRED" }
    }
    @Synchronized fun stop() {
        generation++
        process?.let { child ->
            try { child.outputStream.write("STOP\n".toByteArray()); child.outputStream.flush(); child.outputStream.close() } catch (_: Exception) { }
        }
        process=null; attempted=false; state="OFF"
    }
}
