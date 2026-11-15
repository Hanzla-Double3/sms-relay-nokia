package com.fay.smsrelay

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.os.BatteryManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.os.SystemClock
import okhttp3.*
import org.json.JSONObject
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import kotlin.random.Random

class RelayService: Service() {
    private val executor = RelayRuntime.executor
    private lateinit var ledger: Ledger
    private lateinit var configStore: Config
    private val client = OkHttpClient.Builder().pingInterval(20,TimeUnit.SECONDS).connectTimeout(15,TimeUnit.SECONDS).build()
    private var socket: WebSocket? = null
    private var generation = 0
    private var authenticated = false
    private var diagnosticProtocol=false
    private lateinit var updater: RemoteUpdater
    private var installingUpdate=false
    @Volatile private var stopping = false
    private var attempt = 0
    private var retryAt = 0L
    private var connectedAt = 0L
    private var lastAck = 0L
    private var lastHeartbeat = 0L
    private var lastSubmission: Long? = null
    private var sendPolicy=SendPolicy()
    private var submissionTimer: ScheduledFuture<*>? = null
    private var lastMaintenance = 0L
    private var lastBatterySample = 0L
    private var timer: ScheduledFuture<*>? = null
    private var activeConfig: RelayConfig? = null
    private lateinit var wake: PowerManager.WakeLock

    override fun onCreate() {
        super.onCreate()
        configStore = Config(this)
        ledger = Ledger.get(this)
        updater=RemoteUpdater(this,ledger).apply { onInstallFailed={ installingUpdate=false; guardedTick() } }
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("relay","SMS Relay",NotificationManager.IMPORTANCE_LOW))
        val notification = notification("Starting")
        if(Build.VERSION.SDK_INT >= 34) startForeground(1,notification,ServiceInfo.FOREGROUND_SERVICE_TYPE_REMOTE_MESSAGING) else startForeground(1,notification)
        wake = getSystemService(PowerManager::class.java).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"smsrelay:events").apply { setReferenceCounted(false) }
        ChargeControl.sync(this)
        RelayRuntime.startedAt = SystemClock.elapsedRealtime()
        executor.execute {
            ledger.recover()
            RelayRuntime.onSmsStatusChanged={ guardedTick() }
            ledger.log("[BOOT] Ledger recovered; no ambiguous resends")
            timer = executor.scheduleWithFixedDelay({ guardedTick() },0,5,TimeUnit.SECONDS)
        }
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        ChargeControl.sync(this)
        executor.execute {
            if(!configStore.enabled) { stopping = true; stopSelf(); return@execute }
            if(intent?.action == "RECONNECT") { disconnect(); retryAt = 0; attempt = 0 }
        }
        return START_STICKY
    }
    private fun notification(state: String): Notification {
        val open = PendingIntent.getActivity(this,0,Intent(this,MainActivity::class.java),PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this,"relay").setSmallIcon(android.R.drawable.stat_notify_chat)
            .setContentTitle("SMS Relay • $state").setContentText("Outbound relay · tap to monitor")
            .setContentIntent(open).setOngoing(true).build()
    }
    private fun show(state: String) {
        if(RelayRuntime.connection != state) {
            RelayRuntime.connection = state
            getSystemService(NotificationManager::class.java).notify(1,notification(state))
            ledger.log("[WS] $state")
        }
    }
    private fun guardedTick() {
        if(stopping) return
        wake.acquire(60000)
        try { tick() } catch (_: Exception) { ledger.log("[ERR] Recovery cycle failed"); disconnect(); backoff() }
        finally { if(wake.isHeld) wake.release() }
    }
    private fun tick() {
        if(!configStore.enabled) { stopping = true; stopSelf(); return }
        if(installingUpdate) return
        val sampleNow=SystemClock.elapsedRealtime()
        if(lastBatterySample==0L || sampleNow-lastBatterySample>=BatteryHistory.MINUTE) {
            try { BatteryHistory.get(this).sample(this) } catch (_: Exception) { /* Telemetry must not interrupt the SMS relay. */ }
            lastBatterySample=sampleNow
        }
        val config = configStore.load()
        if(config == null) { show("CONFIG REQUIRED"); return }
        if(activeConfig != config) { configStore.validate(config); disconnect(); activeConfig = config; retryAt = 0 }
        val now = SystemClock.elapsedRealtime()
        if(now-lastMaintenance >= 60000) { ledger.expire(); lastMaintenance = now }
        if(socket == null && now >= retryAt) connect(config)
        if(socket != null && now-lastAck > 75000) { disconnect(); backoff(); return }
        if(!authenticated) return
        if(now-connectedAt > 60000) attempt = 0
        if(now-lastHeartbeat >= 20000) heartbeat(config)
        flush()
        updater.tick(config) { launch ->
            if(ledger.pending().isNotEmpty() || ledger.inFlight()>0 || ledger.dirty().isNotEmpty()) false
            else { installingUpdate=true; heartbeat(config); ledger.log("[UPDATE] Idle; pausing new submissions for installation"); launch(); true }
        }
        if(!installingUpdate) submitPending(config)
    }
    private fun scheduleSubmission(delay: Long) {
        submissionTimer?.cancel(false)
        submissionTimer=executor.schedule({ submissionTimer=null; guardedTick() },delay,TimeUnit.MILLISECONDS)
    }
    private fun submitPending(config: RelayConfig) {
        submissionTimer?.cancel(false); submissionTimer=null
        val job=ledger.pending().firstOrNull() ?: return
        val delay=sendPolicy.waitMillis(SystemClock.elapsedRealtime(),lastSubmission,ledger.inFlight()) ?: return
        if(delay>0) { scheduleSubmission(delay); return }
        val health=PhoneHealth.read(this,config.subscription)
        if(!health.ready) return
        SmsSender(this,ledger).send(job,health.subscription,health.signal)
        lastSubmission=SystemClock.elapsedRealtime()
        flush()
        if(ledger.pending().isNotEmpty()) scheduleSubmission(sendPolicy.intervalMs)
    }
    private fun heartbeat(config: RelayConfig) {
        val health = PhoneHealth.read(this,config.subscription)
        val battery = registerReceiver(null,IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = battery?.getIntExtra(BatteryManager.EXTRA_LEVEL,0) ?: 0
        val scale = battery?.getIntExtra(BatteryManager.EXTRA_SCALE,100) ?: 100
        val charging = PowerState.charging(battery)
        val msg = JSONObject().put("type","heartbeat").put("ready",!installingUpdate && health.ready && ledger.pending().size < 100)
            .put("battery",(level*100/scale.coerceAtLeast(1)).coerceIn(0,100)).put("charging",charging)
            .put("sim_ready",health.sim).put("permission",health.permission).put("health_code",health.code).put("app_version",BuildConfig.VERSION_NAME)
        socket?.send(msg.toString())
        lastHeartbeat = SystemClock.elapsedRealtime()
    }
    private fun flush() {
        if(!authenticated) return
        ledger.dirty().forEach { socket?.send(it.toString()) }
        if(diagnosticProtocol) ledger.diagnosticOutbox().forEach { socket?.send(it.toString()) }
    }
    private fun connect(config: RelayConfig) {
        show("CONNECTING")
        val epoch = ++generation
        lastAck = SystemClock.elapsedRealtime()
        socket = client.newWebSocket(Request.Builder().url(config.url).build(),object: WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) { executor.execute {
                if(epoch != generation || stopping) { ws.cancel(); return@execute }
                ws.send(JSONObject().put("type","hello").put("device_id",config.device).put("token",config.token).put("protocol",1).toString())
            } }
            override fun onMessage(ws: WebSocket, text: String) { executor.execute {
                if(epoch != generation || stopping) return@execute
                try {
                    require(text.toByteArray().size <= 16384)
                    val data = JSONObject(text)
                    when(data.getString("type")) {
                        "hello_ack" -> {
                            require(data.getInt("protocol") == 1 && !authenticated)
                            sendPolicy=SendPolicy.fromHello(data)
                            diagnosticProtocol=data.optInt("diagnostic_protocol",0)==1
                            authenticated = true; connectedAt = SystemClock.elapsedRealtime(); lastAck = connectedAt
                            ledger.replay(); show("CONNECTED"); heartbeat(config); flush(); tick()
                        }
                        "heartbeat_ack" -> { require(authenticated); lastAck = SystemClock.elapsedRealtime(); RelayRuntime.lastPingMs = (lastAck-lastHeartbeat).coerceAtLeast(0) }
                        "diagnostic_ack" -> {
                            require(authenticated && diagnosticProtocol)
                            val id=data.getString("id"); require(id.matches(Regex("diag_[a-f0-9]{32}")))
                            ledger.diagnosticAck(id)
                        }
                        "status_ack" -> {
                            require(authenticated)
                            // Unknown server IDs are retired from the outbox but kept as duplicate guards.
                            ledger.acknowledge(data.getString("id"),data.getInt("revision"))
                            if(!data.getBoolean("accepted")) ledger.log("[SYNC] Server has retired a ledger ID")
                        }
                        "reconcile" -> {
                            require(authenticated)
                            val ids = data.getJSONArray("ids"); require(ids.length() <= 100)
                            repeat(ids.length()) { idx ->
                                val id = ids.getString(idx); require(id.matches(Regex("sms_[a-f0-9]{32}")))
                                if(ledger.get(id) == null) ledger.missing(id) else ledger.markDirty(id)
                            }
                            flush()
                        }
                        "send_sms" -> {
                            require(authenticated)
                            val id = data.getString("id"); val to = data.getString("to"); val body = data.getString("text")
                            require(id.matches(Regex("sms_[a-f0-9]{32}")) && to.matches(Regex("\\+[1-9][0-9]{7,14}")) && body.codePointCount(0,body.length) in 1..1600 && body.isNotBlank())
                            require(body.none { (it.code < 32 && it !in "\n\r\t") })
                            ledger.receive(id,to,body)
                            // Received is durable and reported before the submission guard.
                            flush()
                            tick()
                        }
                        else -> error("Unsupported operation")
                    }
                } catch (_: Exception) { ledger.log("[ERR] Invalid protocol or processing failure"); disconnect(); backoff() }
            } }
            override fun onFailure(ws: WebSocket, error: Throwable, response: Response?) { executor.execute { if(epoch == generation && !stopping) { disconnect(); backoff() } } }
            override fun onClosed(ws: WebSocket, code: Int, reason: String) { executor.execute { if(epoch == generation && !stopping) { disconnect(); backoff() } } }
            override fun onClosing(ws: WebSocket, code: Int, reason: String) { ws.close(code,null) }
        })
    }
    private fun disconnect() {
        submissionTimer?.cancel(false); submissionTimer=null
        generation++; authenticated = false; diagnosticProtocol=false
        socket?.cancel(); socket = null
    }
    private fun backoff() {
        val delay = RelayRules.reconnectDelay(attempt++,Random.nextDouble())
        retryAt = SystemClock.elapsedRealtime()+delay
        show("RECONNECT ${delay/1000}s")
    }
    override fun onDestroy() {
        updater.close()
        ChargeControl.stop()
        stopping = true
        executor.execute { timer?.cancel(false); RelayRuntime.onSmsStatusChanged=null; disconnect(); RelayRuntime.connection = "STOPPED"; ledger.log("[WS] STOPPED"); getSystemService(NotificationManager::class.java).cancel(1); client.dispatcher.executorService.shutdown(); client.connectionPool.evictAll(); if(wake.isHeld) wake.release() }
        super.onDestroy()
    }
    override fun onBind(intent: Intent?): IBinder? = null
}
