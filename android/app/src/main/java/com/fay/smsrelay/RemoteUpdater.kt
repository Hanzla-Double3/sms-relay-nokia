package com.fay.smsrelay

import android.content.Context
import android.content.pm.PackageManager
import android.os.SystemClock
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Downloads use a separate worker; root receives only fixed paths and a validated SHA256. */
class RemoteUpdater(private val context: Context,private val ledger: Ledger) {
    companion object { @Volatile var state="CHECKS EVERY 15 MINUTES"; @Volatile var checkNow=false }
    private val worker=Executors.newSingleThreadExecutor()
    private val client=OkHttpClient.Builder().followRedirects(false).followSslRedirects(false)
        .connectTimeout(15,TimeUnit.SECONDS).readTimeout(30,TimeUnit.SECONDS).callTimeout(120,TimeUnit.SECONDS).build()
    private var nextCheck=0L
    @Volatile private var busy=false
    @Volatile private var staged: AppRelease?=null
    @Volatile private var closed=false
    private val apk=File(context.filesDir,"verified-update.apk")
    private val result=File(context.filesDir,"update-result")
    fun tick(config: RelayConfig,beginInstall: ((()->Unit))->Boolean) {
        if(closed || busy) return
        staged?.let { release ->
            busy=true
            if(beginInstall { launchInstaller(release) }) staged=null else busy=false
            return
        }
        val now=SystemClock.elapsedRealtime()
        if(!checkNow && now<nextCheck) return
        checkNow=false; nextCheck=now+15*60*1000; busy=true
        worker.execute {
            try { fetch(config) } catch (_: Exception) { state="UPDATE CHECK FAILED"; ledger.log("[UPDATE] Check or verification failed; keeping installed version"); apk.delete() }
            finally { busy=false }
        }
    }
    private fun request(config: RelayConfig,path: String): Request {
        val base=config.url.replaceFirst("wss://","https://").replaceFirst("ws://","http://").toHttpUrl()
        require(base.isHttps) { "Updates require HTTPS" }
        val url=base.newBuilder().encodedPath(path).query(null).addQueryParameter("device",config.device)
        if(path=="/v1/device/update") url.addQueryParameter("version_code",BuildConfig.VERSION_CODE.toString())
        return Request.Builder().url(url.build()).header("Authorization","Bearer ${config.token}").build()
    }
    private fun fetch(config: RelayConfig) {
        val release=client.newCall(request(config,"/v1/device/update")).execute().use { response ->
            if(response.code==204) { state="UP TO DATE / NO REQUEST"; return }
            require(response.code==200)
            val input=response.body!!.byteStream().use { stream ->
                val buffer=ByteArray(8193); var n=0
                while(n<buffer.size) { val read=stream.read(buffer,n,buffer.size-n); if(read<0) break; n+=read }
                buffer.copyOf(n)
            }
            require(input.size<=8192)
            UpdateRules.verify(JSONObject(String(input,Charsets.UTF_8)),BuildConfig.VERSION_CODE.toLong())
        }
        state="DOWNLOADING ${release.name}"
        client.newCall(request(config,"/v1/device/update/apk")).execute().use { response ->
            require(response.code==200)
            response.body!!.byteStream().use { input -> apk.outputStream().use { output ->
                val buffer=ByteArray(32768); var size=0L
                while(true) { val n=input.read(buffer); if(n<0) break; size+=n; require(size<=release.size); output.write(buffer,0,n) }
                require(size==release.size)
            } }
        }
        val digest=MessageDigest.getInstance("SHA-256")
        apk.inputStream().use { stream -> val buffer=ByteArray(32768); while(true) { val n=stream.read(buffer); if(n<0) break; digest.update(buffer,0,n) } }
        val hash=digest.digest().joinToString("") { "%02x".format(it) }
        require(hash==release.hash)
        val flags=PackageManager.GET_SIGNING_CERTIFICATES
        val archive=context.packageManager.getPackageArchiveInfo(apk.path,flags) ?: error("Invalid APK")
        val installed=context.packageManager.getPackageInfo(context.packageName,flags)
        require(archive.packageName==context.packageName && archive.longVersionCode==release.code)
        val current=installed.signingInfo!!.apkContentsSigners.map { it.toByteArray().toList() }.toSet()
        require(current.isNotEmpty() && archive.signingInfo!!.apkContentsSigners.map { it.toByteArray().toList() }.toSet()==current) { "APK signing identity changed" }
        if(closed) { apk.delete(); return }
        staged=release; state="${release.name} VERIFIED · WAITING FOR IDLE"
        ledger.log("[UPDATE] ${release.name} signature, hash and APK signer verified")
    }
    private fun launchInstaller(release: AppRelease) {
        worker.execute {
            try {
                result.delete()
                // No device/server strings are interpolated into a privileged command.
                val script=File(context.filesDir,"install-verified-update.sh")
                script.writeText("""
                    #!/system/bin/sh
                    apk='${apk.path}'
                    result='${result.path}'
                    staged=''
                    fail() { [ -z "${'$'}staged" ] || rm -f "${'$'}staged"; printf 'FAILED\n' > "${'$'}result"; chmod 644 "${'$'}result"; exit 1; }
                    [ "${'$'}(sha256sum "${'$'}apk" | cut -d ' ' -f 1)" = '${release.hash}' ] || fail
                    staged=$(mktemp /data/local/tmp/fay-sms-relay-update.XXXXXX) || fail
                    cp "${'$'}apk" "${'$'}staged" || fail
                    chmod 600 "${'$'}staged"
                    command -v timeout >/dev/null || fail
                    timeout 30 pm install -r "${'$'}staged" > '${context.filesDir}/install-result' 2>&1 || fail
                    rm -f "${'$'}staged" "${'$'}apk"
                    printf 'SUCCESS\n' > "${'$'}result"
                    chmod 644 "${'$'}result"
                    am start-foreground-service -n com.fay.smsrelay/.RelayService
                    am start -n com.fay.smsrelay/.MainActivity
                """.trimIndent())
                state="INSTALLING ${release.name}"
                val process=Runtime.getRuntime().exec(arrayOf("su","-c","nohup sh '${script.path}' >/dev/null 2>&1 </dev/null &"))
                if(!process.waitFor(10,TimeUnit.SECONDS)) { process.destroyForcibly(); error("Root permission timeout") }
                require(process.exitValue()==0)
                // Replacement kills this process; a surviving process means install failed/stalled.
                Thread.sleep(45000)
                state="INSTALL FAILED / RETRY LATER"
                ledger.log("[UPDATE] Installation did not replace app; retry later")
            } catch (_: Exception) { state="ROOT INSTALL FAILED"; ledger.log("[UPDATE] Root installation failed; keeping installed version") }
            finally { RelayRuntime.executor.execute { onInstallFailed?.invoke() }; busy=false; nextCheck=SystemClock.elapsedRealtime()+15*60*1000 }
        }
    }
    var onInstallFailed: (()->Unit)?=null
    fun close() { closed=true; client.dispatcher.cancelAll(); worker.shutdownNow() }
}
