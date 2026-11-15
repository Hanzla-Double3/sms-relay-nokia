package com.fay.smsrelay

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.view.View
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Small native instrument panel: no bitmap assets, animation loop or growing event buffer. */
class DashboardView(context: Context) : View(context) {
    private val ink=Paint(Paint.ANTI_ALIAS_FLAG)
    private val green=Color.rgb(124,255,196)
    private val red=Color.rgb(255,105,115)
    private val dim=Color.rgb(103,140,129)
    private val line=Color.rgb(31,61,51)
    private var device="NOKIA // RELAY"
    private var connection="STARTING"
    private var health: PhoneHealth?=null
    private var battery=0
    private var charging=false
    private var recent=emptyList<Pair<Long,String>>()
    private var lastSent: Pair<Long,String>?=null
    private val sentFormat=SimpleDateFormat("dd MMM HH:mm:ss",Locale.US)
    private val timeFormat=SimpleDateFormat("HH:mm",Locale.US)
    private val secondsFormat=SimpleDateFormat("ss",Locale.US)
    private val dateFormat=SimpleDateFormat("EEE  ·  dd MMM yyyy",Locale.US)
    private val logFormat=SimpleDateFormat("HH:mm:ss",Locale.US)
    fun update(id: String, state: String, phone: PhoneHealth, percent: Int, plugged: Boolean, logs: List<Pair<Long,String>>, sent: Pair<Long,String>?) {
        device=id; connection=state; health=phone; battery=percent.coerceIn(0,100); charging=plugged; recent=logs; lastSent=sent
        contentDescription="SMS relay. $connection. ${phone.code}. Battery $battery percent, ${if(charging) "charging" else "not charging"}. Signal ${phone.signalLevel ?: "unknown"} of four."
    }
    fun unavailable() { connection="STATUS UNAVAILABLE" }
    private fun text(c: Canvas,value: String,x: Float,y: Float,size: Float,color: Int=green,bold: Boolean=false) {
        ink.color=color; ink.style=Paint.Style.FILL; ink.typeface=Typeface.create("monospace",if(bold) Typeface.BOLD else Typeface.NORMAL); ink.textSize=size
        c.drawText(value,x,y,ink)
    }
    private fun stroke(c: Canvas,x: Float,y: Float,x2: Float,y2: Float,color: Int=line,width: Float=1f) {
        ink.color=color; ink.strokeWidth=width; c.drawLine(x,y,x2,y2,ink)
    }
    private fun panel(c: Canvas,x: Float,y: Float,w: Float,h: Float) {
        ink.style=Paint.Style.FILL; ink.color=Color.rgb(11,24,22); c.drawRoundRect(x,y,x+w,y+h,10f,10f,ink)
        ink.style=Paint.Style.STROKE; ink.strokeWidth=1f; ink.color=line; c.drawRoundRect(x,y,x+w,y+h,10f,10f,ink); ink.style=Paint.Style.FILL
    }
    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        canvas.drawColor(Color.rgb(6,15,14))
        // A uniform coordinate system fits either landscape direction and the Nokia's display.
        val scale=minOf(width/800f,height/360f)
        canvas.save(); canvas.translate((width-800*scale)/2,(height-360*scale)/2); canvas.scale(scale,scale)
        for(x in 0..800 step 32) stroke(canvas,x.toFloat(),0f,x.toFloat(),360f,Color.rgb(10,24,20))
        for(y in 0..360 step 32) stroke(canvas,0f,y.toFloat(),800f,y.toFloat(),Color.rgb(10,24,20))
        text(canvas,"FAY // SMS RELAY",24f,32f,16f,bold=true)
        text(canvas,"${device.take(32)}  /  v${BuildConfig.VERSION_NAME}",24f,53f,10f,dim)
        stroke(canvas,24f,68f,776f,68f)
        val now=Date()
        text(canvas,timeFormat.format(now),22f,181f,104f,bold=true)
        text(canvas,secondsFormat.format(now),343f,180f,29f,dim)
        text(canvas,dateFormat.format(now).uppercase(Locale.US),28f,218f,14f,dim)
        val connected=connection=="CONNECTED"
        val connectionColor=if(connected) green else red
        ink.color=connectionColor; canvas.drawCircle(35f,251f,5f,ink)
        text(canvas,if(connected) "CONNECTED" else "OFFLINE",50f,257f,20f,connectionColor,true)
        text(canvas,if(connected) "SECURE SERVER LINK" else connection.take(32),28f,278f,10f,dim)
        panel(canvas,421f,87f,171f,99f)
        text(canvas,"CELLULAR",437f,108f,10f,dim)
        val bars=health?.signalLevel?.coerceIn(0,4) ?: 0
        for(i in 0..3) {
            ink.color=if(health?.ready==true && i<bars) green else line
            val h=9f+i*7f; canvas.drawRoundRect(438f+i*13,151f-h,446f+i*13,151f,2f,2f,ink)
        }
        text(canvas,health?.signal?.let { "$it dBm" } ?: "-- dBm",501f,146f,12f)
        text(canvas,(health?.code ?: "CHECKING").replace('_',' '),437f,173f,10f,if(health?.ready==true) green else red)
        panel(canvas,604f,87f,172f,99f)
        text(canvas,"POWER",620f,108f,10f,dim)
        // Blink the battery outline while unplugged; polling stops when the Activity is hidden.
        val powerColor=if(battery<=15) red else green
        ink.color=if(!charging && now.time/1000%2==0L) dim else powerColor
        ink.style=Paint.Style.STROKE; ink.strokeWidth=2f
        canvas.drawRoundRect(620f,124f,663f,146f,3f,3f,ink)
        ink.style=Paint.Style.FILL; canvas.drawRect(665f,130f,668f,140f,ink)
        canvas.drawRect(624f,128f,624f+35f*battery/100,142f,ink)
        text(canvas,"$battery%",681f,145f,23f,powerColor,true)
        val powerLabel=when(ChargeControl.state) {
            "PAUSED_TO_60" -> "PAUSED → 60%"
            "ROOT_REQUIRED","WAITING_FOR_ROOT" -> "ROOT REQUIRED"
            "CONTROL_ERROR","CONTROL_BUSY","UNSUPPORTED" -> "LIMIT UNAVAILABLE"
            else -> if(charging) "⚡ CHARGING" else "ON BATTERY"
        }
        text(canvas,powerLabel,620f,173f,10f,powerColor)
        panel(canvas,421f,198f,355f,82f)
        text(canvas,"RELAY STATUS",437f,220f,10f,dim)
        text(canvas,when { !connected -> "WAITING FOR SERVER"; health?.ready==true -> "READY TO SEND"; else -> "PHONE NEEDS ATTENTION" },437f,246f,17f,if(connected && health?.ready==true) green else red,true)
        text(canvas,"PING ${if(connected) "${RelayRuntime.lastPingMs} ms" else "--"}  ·  OUTBOUND WSS",437f,266f,10f,dim)
        stroke(canvas,24f,296f,776f,296f)
        text(canvas,"LATEST EVENT",24f,322f,10f,dim)
        recent.takeLast(1).forEach { (at,event) -> text(canvas,logFormat.format(Date(at))+"  "+event.take(71),151f,322f,11f,dim) }
        if(recent.isEmpty()) text(canvas,"No recent events",151f,322f,10f,dim)
        text(canvas,"LAST SENT",24f,347f,10f,dim)
        text(canvas,lastSent?.let { sentFormat.format(Date(it.first))+"  ·  …"+it.second.takeLast(12) } ?: "No confirmed sends yet",151f,347f,11f,if(lastSent!=null) green else dim)
        canvas.restore()
    }
}
