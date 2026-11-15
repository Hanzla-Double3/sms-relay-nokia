package com.fay.smsrelay

import android.app.Activity
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

class BatteryGraphActivity: Activity() {
    private val main=Handler(Looper.getMainLooper())
    private lateinit var config: Config
    private lateinit var brightness: AmbientBrightness
    private lateinit var graph: BatteryGraphView
    private val ranges=listOf("1 HOUR" to 3600000L,"6 HOURS" to 21600000L,"24 HOURS" to 86400000L,"7 DAYS" to BatteryHistory.RETENTION)
    private val buttons=mutableListOf<Button>()
    private var range=86400000L
    private var visible=false
    private var loading=false
    private val refresh=object: Runnable { override fun run() { load(); if(visible) main.postDelayed(this,BatteryHistory.MINUTE) } }
    private val green=Color.rgb(124,255,196)
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        config=Config(this); brightness=AmbientBrightness(this,config)
        range=savedInstanceState?.getLong("range",range)?.takeIf { value -> ranges.any { it.second==value } } ?: range
        @Suppress("DEPRECATION")
        window.decorView.systemUiVisibility=View.SYSTEM_UI_FLAG_FULLSCREEN or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
        val root=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; setPadding(dp(18),dp(10),dp(18),dp(10)); setBackgroundColor(Color.rgb(6,15,14)) }
        val header=LinearLayout(this).apply { gravity=Gravity.CENTER_VERTICAL }
        header.addView(TextView(this).apply { text="POWER // BATTERY HISTORY"; textSize=17f; setTextColor(green); typeface=Typeface.MONOSPACE },LinearLayout.LayoutParams(0,dp(46),1f))
        header.addView(button("← Back") { finish() },LinearLayout.LayoutParams(dp(115),dp(46)))
        root.addView(header)
        val controls=LinearLayout(this)
        ranges.forEach { (label,duration) ->
            val btn=button(label) { range=duration; updateButtons(); load() }; buttons.add(btn)
            controls.addView(btn,LinearLayout.LayoutParams(0,dp(42),1f).apply { marginEnd=dp(5) })
        }
        root.addView(controls)
        graph=BatteryGraphView(this)
        root.addView(graph,LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,0,1f))
        root.addView(TextView(this).apply {
            text="1 sample / minute · 7 days stored locally · gaps = relay stopped / missing readings"
            textSize=10f; typeface=Typeface.MONOSPACE; setTextColor(Color.rgb(103,140,129)); setPadding(0,dp(3),0,0)
        })
        setContentView(root); updateButtons()
    }
    private fun dp(value: Int)=(value*resources.displayMetrics.density).toInt()
    private fun button(label: String, action: () -> Unit)=Button(this).apply {
        text=label; textSize=11f; isAllCaps=false; typeface=Typeface.MONOSPACE; setTextColor(green)
        setBackgroundColor(Color.rgb(16,32,29)); setOnClickListener { action() }
    }
    private fun updateButtons() { buttons.forEachIndexed { index,button -> button.setTextColor(if(ranges[index].second==range) Color.rgb(6,15,14) else green); button.setBackgroundColor(if(ranges[index].second==range) green else Color.rgb(16,32,29)) } }
    private fun load() {
        if(loading) return
        loading=true
        val selected=range; val now=System.currentTimeMillis()
        RelayRuntime.executor.execute {
            try {
                val samples=BatteryHistory.get(this).read(now-selected,now)
                main.post { loading=false; if(visible) { if(selected==range) graph.update(samples,now-selected,now) else load() } }
            } catch (_: Exception) { main.post { loading=false; if(visible) graph.unavailable() } }
        }
    }
    override fun onResume() {
        super.onResume(); visible=true; brightness.start()
        if(config.awake) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        main.post(refresh)
    }
    override fun onPause() { visible=false; main.removeCallbacks(refresh); brightness.stop(); super.onPause() }
    override fun onSaveInstanceState(outState: Bundle) { outState.putLong("range",range); super.onSaveInstanceState(outState) }
}
