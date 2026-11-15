package com.fay.smsrelay

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.os.BatteryManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.Settings
import android.text.InputType
import android.view.View
import android.view.WindowManager
import android.widget.*
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MoreInfoActivity: Activity() {
    private val main = Handler(Looper.getMainLooper())
    private lateinit var config: Config
    private lateinit var brightness: AmbientBrightness
    private lateinit var status: TextView
    private lateinit var logText: TextView
    private var visible = false
    private var lastLogs = ""
    private var updating = false
    private val green = Color.rgb(124,255,196)
    private val refresh = object: Runnable { override fun run() { update(); if(visible) main.postDelayed(this,5000) } }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        config = Config(this)
        brightness = AmbientBrightness(this,config)
        @Suppress("DEPRECATION")
        window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_FULLSCREEN or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(16),dp(12),dp(16),dp(16)); setBackgroundColor(Color.rgb(8,15,21)) }
        val header = LinearLayout(this).apply { gravity=android.view.Gravity.CENTER_VERTICAL }
        header.addView(label("RELAY // MORE INFO",19f),LinearLayout.LayoutParams(0,dp(56),1f))
        header.addView(button("← Dashboard") { finish() },LinearLayout.LayoutParams(dp(170),dp(48)))
        root.addView(header)
        status = label("STARTUP • checking ledger and phone…",13f)
        logText = label("",11f)
        val controls = LinearLayout(this)
        controls.addView(button("Start") { startRelay() },LinearLayout.LayoutParams(0,dp(48),1f))
        controls.addView(button("Reconnect") { if(config.enabled) startForegroundService(Intent(this,RelayService::class.java).setAction("RECONNECT")) },LinearLayout.LayoutParams(0,dp(48),1.4f))
        controls.addView(button("Stop") { config.enabled = false; stopService(Intent(this,RelayService::class.java)) },LinearLayout.LayoutParams(0,dp(48),1f))
        root.addView(controls)
        val second = LinearLayout(this)
        second.addView(button("Configure") { configure() },LinearLayout.LayoutParams(0,dp(48),1.3f))
        second.addView(button("Battery") { startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)) },LinearLayout.LayoutParams(0,dp(48),1f))
        second.addView(button("Check update") { RemoteUpdater.checkNow=true; Toast.makeText(this,"Checking shortly; updates must be requested in admin",Toast.LENGTH_LONG).show() },LinearLayout.LayoutParams(0,dp(48),1f))
        root.addView(second)
        root.addView(button("Battery history graph") { startActivity(Intent(this,BatteryGraphActivity::class.java)) })
        root.addView(Switch(this).apply {
            text = "Keep screen awake (visible screen only)"; setTextColor(green); textSize = 12f; isChecked = config.awake
            setOnCheckedChangeListener { _, checked -> config.awake = checked; applyAwake() }
        })
        root.addView(label("Screen brightness",12f))
        val slider = SeekBar(this).apply { max = 100; progress = config.brightness; contentDescription = "Screen brightness"; setOnSeekBarChangeListener(object: SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(bar: SeekBar?, value: Int, fromUser: Boolean) { if(fromUser) { config.brightness = value; applyBrightness() } }
            override fun onStartTrackingTouch(bar: SeekBar?) {}
            override fun onStopTrackingTouch(bar: SeekBar?) {}
        }) }
        slider.isEnabled=!config.adaptiveBrightness
        root.addView(Switch(this).apply {
            text=if(brightness.supported) "Adaptive brightness · ambient light sensor" else "Adaptive brightness · sensor unavailable"
            setTextColor(green); textSize=12f; isChecked=config.adaptiveBrightness; isEnabled=brightness.supported
            setOnCheckedChangeListener { _,checked -> config.adaptiveBrightness=checked; slider.isEnabled=!checked; brightness.update() }
        })
        root.addView(slider)
        root.addView(Switch(this).apply {
            text="Charge limit · pause at 80%, resume at 60% (root)"; setTextColor(green); textSize=12f; isChecked=config.chargeLimit
            setOnCheckedChangeListener { _,checked -> config.chargeLimit=checked; ChargeControl.sync(this@MoreInfoActivity,true) }
        })
        root.addView(button("Retry charging root access") { ChargeControl.sync(this,true) })
        root.addView(label("Charge limit needs Magisk root permission and an active relay service.\nStopping the relay restores normal charging.",11f))
        root.addView(label("APP ${BuildConfig.VERSION_NAME} / REMOTE UPDATES",15f))
        root.addView(label("Admin requests install verified releases when idle. Checks every 15 minutes; root required.",11f))
        root.addView(label("DEVICE / LEDGER",15f))
        root.addView(status)
        root.addView(label("LOG / LAST HOUR · latest 100 events",15f))
        root.addView(logText)
        setContentView(ScrollView(this).apply { addView(root) }); applyAwake(); applyBrightness()
    }
    private fun dp(value: Int) = (value*resources.displayMetrics.density).toInt()
    private fun label(value: String, size: Float) = TextView(this).apply { text=value; textSize=size; setTextColor(green); typeface=Typeface.MONOSPACE; setPadding(0,5,0,5) }
    private fun button(value: String, action: (View)->Unit) = Button(this).apply { text=value; textSize=12f; isAllCaps=false; typeface=Typeface.MONOSPACE; setTextColor(green)
        val normal=android.graphics.drawable.GradientDrawable().apply { setColor(Color.rgb(16,32,29)); cornerRadius=dp(6).toFloat(); setStroke(dp(1),Color.rgb(37,69,54)) }
        val pressed=android.graphics.drawable.GradientDrawable().apply { setColor(Color.rgb(28,61,47)); cornerRadius=dp(6).toFloat(); setStroke(dp(1),green) }
        background=android.graphics.drawable.StateListDrawable().apply { addState(intArrayOf(android.R.attr.state_pressed),pressed); addState(intArrayOf(),normal) }
        setOnClickListener(action) }
    private fun applyBrightness() { brightness.update() }
    private fun applyAwake() { if(config.awake) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
    private fun startRelay() {
        if(config.load() == null) { configure(); return }
        config.enabled = true
        val needed = mutableListOf(Manifest.permission.SEND_SMS, Manifest.permission.READ_PHONE_STATE)
        if(Build.VERSION.SDK_INT >= 33) needed.add(Manifest.permission.POST_NOTIFICATIONS)
        val missing = needed.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if(missing.isNotEmpty()) requestPermissions(missing.toTypedArray(),7)
        else startForegroundService(Intent(this,RelayService::class.java))
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode,permissions,grantResults)
        if(requestCode == 7 && config.enabled) startForegroundService(Intent(this,RelayService::class.java))
    }
    private fun configure() {
        val current = config.load()
        val form = LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; setPadding(30,12,30,12) }
        fun field(hintText: String, value: String, secret: Boolean = false): EditText = EditText(this).apply {
            hint=hintText; setText(value); isSingleLine=true
            inputType=if(secret) InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD else InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            form.addView(this)
        }
        val url=field("wss://host/ws/device",current?.url ?: "wss://relay.example.com/ws/device")
        val device=field("Device ID",current?.device ?: "nokia-01")
        val token=field(if(current == null) "Device token" else "New token (blank keeps current)","",true)
        val subscription=field("Subscription ID (-1 = default)",(current?.subscription ?: -1).toString())
        form.addView(label("READ_PHONE_STATE checks SIM selection and health.\nNo incoming SMS or phone number access.\nDebug USB URL: ws://127.0.0.1:8080/ws/device",11f))
        val dialog = AlertDialog.Builder(this).setTitle("Local device provisioning").setView(ScrollView(this).apply { addView(form) }).setNegativeButton("Cancel",null).setPositiveButton("Save",null).create()
        dialog.setOnShowListener { dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
            try {
                val next = RelayConfig(url.text.toString().trim(),device.text.toString().trim(),token.text.toString().ifBlank { current?.token ?: "" },subscription.text.toString().toInt())
                require(current == null || current.device == next.device || Ledger.get(this).counts().isEmpty()) { "Device ID cannot change while the ledger holds jobs." }
                config.save(next)
                if(config.enabled) startForegroundService(Intent(this,RelayService::class.java).setAction("RECONNECT"))
                dialog.dismiss()
            } catch (error: Exception) { Toast.makeText(this,error.message ?: "Invalid configuration",Toast.LENGTH_LONG).show() }
        } }
        dialog.show()
    }
    override fun onResume() { super.onResume(); brightness.start(); visible=true; main.post(refresh) }
    override fun onPause() { brightness.stop(); visible=false; main.removeCallbacks(refresh); super.onPause() }
    private fun update() {
        if(updating) return
        updating = true
        val conf=config.load()
        val health=PhoneHealth.read(this,conf?.subscription ?: -1)
        val battery=registerReceiver(null,IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val percent=((battery?.getIntExtra(BatteryManager.EXTRA_LEVEL,0) ?: 0)*100/(battery?.getIntExtra(BatteryManager.EXTRA_SCALE,100) ?: 100).coerceAtLeast(1))
        val charging=PowerState.charging(battery)
        val uptime=if(RelayRuntime.startedAt == 0L) 0 else (SystemClock.elapsedRealtime()-RelayRuntime.startedAt)/1000
        val power=getSystemService(android.os.PowerManager::class.java)
        RelayRuntime.executor.execute {
            try {
            val ledger=Ledger.get(this)
            val counts=ledger.counts()
            val logs=ledger.logs().joinToString("\n") { (at,event) -> SimpleDateFormat("HH:mm:ss",Locale.US).format(Date(at))+"  "+event }
            val summary="DEVICE    ${conf?.device ?: "UNCONFIGURED"} [${RelayRuntime.connection}]\n"+
                "SERVER    ${conf?.url ?: "Configure to connect"}\n"+
                "HEALTH    ${health.code} · SUB ${health.subscription}\n"+
                "SIGNAL    ${health.signal?.let { "$it dBm" } ?: "--"}   BATTERY $percent% ${if(charging) "+ charging" else ""}\n"+
                "UPDATE    ${RemoteUpdater.state}\n"+
                "CHARGER   ${ChargeControl.state} · 80% / 60%\n"+
                "UPTIME    ${uptime/3600}h ${(uptime/60)%60}m   PING ${RelayRuntime.lastPingMs}ms\n"+
                "LEDGER    QUEUED ${counts["phone_received"] ?: 0}  SENT ${(counts["sent"] ?: 0)+(counts["delivered"] ?: 0)}\n"+
                "          FAILED ${counts["failed"] ?: 0}  UNKNOWN ${counts["unknown"] ?: 0}\n"+
                "STARTUP   ${if(config.enabled) "ENABLED" else "STOPPED"} · BATTERY ${if(power.isIgnoringBatteryOptimizations(packageName)) "EXEMPT" else "OPTIMIZED"}"
            main.post {
                updating = false
                if(visible) {
                    status.text=summary
                    if(logs != lastLogs) { logText.text=logs; lastLogs=logs }
                }
            }
            } catch (_: Exception) { main.post { updating = false; if(visible) status.text="STARTUP ERROR • local ledger unavailable" } }
        }
    }
}
