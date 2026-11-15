package com.fay.smsrelay

import android.app.Activity
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.SystemClock
import kotlin.math.abs
import kotlin.math.log10

object BrightnessRules {
    fun level(lux: Float): Float = if(!lux.isFinite()) .05f else (.05f+log10(1f+lux.coerceAtLeast(0f))*.2375f).coerceIn(.05f,1f)
}

/** Per-window ambient light control. No system-settings permission or background sampling. */
class AmbientBrightness(private val activity: Activity, private val config: Config): SensorEventListener {
    private val sensors=activity.getSystemService(SensorManager::class.java)
    private val light=sensors.getDefaultSensor(Sensor.TYPE_LIGHT)
    val supported get()=light!=null
    private var active=false
    private var registered=false
    private var smoothed=Float.NaN
    private var lastApplied=0L
    fun start() { active=true; update() }
    fun stop() { active=false; sensors.unregisterListener(this); registered=false; smoothed=Float.NaN; lastApplied=0 }
    fun update() {
        if(active && config.adaptiveBrightness && light!=null) {
            if(!registered) registered=sensors.registerListener(this,light,SensorManager.SENSOR_DELAY_NORMAL)
        } else {
            sensors.unregisterListener(this); registered=false; smoothed=Float.NaN
        }
        if(!registered) activity.window.attributes=activity.window.attributes.apply { screenBrightness=config.brightness/100f }
    }
    override fun onSensorChanged(event: SensorEvent) {
        if(!active || !config.adaptiveBrightness || event.values.isEmpty() || !event.values[0].isFinite()) return
        val target=BrightnessRules.level(event.values[0])
        smoothed=if(smoothed.isNaN()) target else smoothed*.7f+target*.3f
        val now=SystemClock.elapsedRealtime()
        if(lastApplied==0L || (now-lastApplied>=1500 && abs(activity.window.attributes.screenBrightness-smoothed)>=.02f)) {
            activity.window.attributes=activity.window.attributes.apply { screenBrightness=smoothed }
            lastApplied=now
        }
    }
    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
}
