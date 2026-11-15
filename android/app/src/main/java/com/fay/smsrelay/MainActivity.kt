package com.fay.smsrelay

import android.app.Activity
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.View
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.Button
import android.graphics.Color
import android.graphics.Typeface

class MainActivity : Activity() {
    private val main = Handler(Looper.getMainLooper())
    private lateinit var dashboard: DashboardView
    private lateinit var config: Config
    private lateinit var brightness: AmbientBrightness
    private var visible = false
    private var updating = false
    private var lastStatus = 0L
    private val refresh = object : Runnable {
        override fun run() {
            val now=SystemClock.elapsedRealtime()
            if(lastStatus==0L || now-lastStatus>=5000) { lastStatus=now; update() }
            dashboard.invalidate() // Only the clock/battery blink need a one-second redraw.
            if(visible) main.postDelayed(this,1000)
        }
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        config = Config(this)
        brightness = AmbientBrightness(this,config)
        @Suppress("DEPRECATION")
        window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_FULLSCREEN or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
        dashboard = DashboardView(this)
        val root = FrameLayout(this).apply { addView(dashboard) }
        val more = Button(this).apply {
            text = "MORE INFO  ›"; textSize = 11f; typeface = Typeface.MONOSPACE
            setTextColor(Color.rgb(124,255,196)); setBackgroundColor(Color.rgb(16,32,29))
            contentDescription = "More info and relay controls"
            setOnClickListener { startActivity(Intent(this@MainActivity,MoreInfoActivity::class.java)) }
        }
        val density = resources.displayMetrics.density
        root.addView(more,FrameLayout.LayoutParams((150*density).toInt(),(48*density).toInt(),android.view.Gravity.TOP or android.view.Gravity.RIGHT).apply {
            topMargin=(12*density).toInt(); rightMargin=(20*density).toInt()
        })
        val history=Button(this).apply {
            text="BATTERY GRAPH"; textSize=10f; typeface=Typeface.MONOSPACE
            setTextColor(Color.rgb(124,255,196)); setBackgroundColor(Color.rgb(16,32,29))
            contentDescription="Battery history graph"
            setOnClickListener { startActivity(Intent(this@MainActivity,BatteryGraphActivity::class.java)) }
        }
        root.addView(history,FrameLayout.LayoutParams((140*density).toInt(),(48*density).toInt(),android.view.Gravity.TOP or android.view.Gravity.RIGHT).apply {
            topMargin=(12*density).toInt(); rightMargin=(180*density).toInt()
        })
        setContentView(root)
    }
    override fun onResume() {
        super.onResume(); visible = true; lastStatus=0L
        if(config.awake) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        brightness.start()
        if(config.enabled) startForegroundService(Intent(this,RelayService::class.java))
        main.post(refresh)
    }
    override fun onPause() { brightness.stop(); visible=false; main.removeCallbacks(refresh); super.onPause() }
    private fun update() {
        if(updating) return
        updating=true
        val conf=config.load()
        val battery=registerReceiver(null,IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val percent=(battery?.getIntExtra(BatteryManager.EXTRA_LEVEL,0) ?: 0)*100/(battery?.getIntExtra(BatteryManager.EXTRA_SCALE,100) ?: 100).coerceAtLeast(1)
        val charging=PowerState.charging(battery)
        RelayRuntime.executor.execute {
            try {
                val health=PhoneHealth.read(this,conf?.subscription ?: -1)
                val ledger=Ledger.get(this)
                val recent=ledger.logs().takeLast(1)
                val lastSent=ledger.lastSent()
                main.post {
                    updating=false
                    if(visible) dashboard.update(conf?.device ?: "UNCONFIGURED",RelayRuntime.connection,health,percent,charging,recent,lastSent)
                }
            } catch (_: Exception) { main.post { updating=false; if(visible) dashboard.unavailable() } }
        }
    }
}
