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

/** Bounded native plot. A missing sample leaves a gap instead of an invented slope. */
class BatteryGraphView(context: Context): View(context) {
    private val ink=Paint(Paint.ANTI_ALIAS_FLAG)
    private val green=Color.rgb(124,255,196)
    private val cyan=Color.rgb(104,210,255)
    private val dim=Color.rgb(103,140,129)
    private val grid=Color.rgb(31,61,51)
    private var samples=emptyList<BatterySample>()
    private var start=0L
    private var end=1L
    private var error=false
    fun update(values: List<BatterySample>, from: Long, to: Long) {
        samples=values; start=from; end=to; error=false
        contentDescription="Battery history, ${values.size} readings. "+(values.lastOrNull()?.let { "Latest battery ${it.percent} percent." } ?: "Waiting for the first sample.")
        invalidate()
    }
    fun unavailable() { error=true; invalidate() }
    private fun text(canvas: Canvas, value: String,x: Float,y: Float,size: Float,color: Int=dim) {
        ink.style=Paint.Style.FILL; ink.color=color; ink.textSize=size; ink.typeface=Typeface.MONOSPACE; canvas.drawText(value,x,y,ink)
    }
    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        if(width==0 || height==0) return
        val scale=minOf(width/760f,height/238f)
        canvas.save(); canvas.translate((width-760*scale)/2,(height-238*scale)/2); canvas.scale(scale,scale)
        val first=samples.firstOrNull(); val last=samples.lastOrNull()
        text(canvas,last?.let { "${it.percent}%" } ?: "--%",10f,29f,24f,green)
        val change=if(first!=null && last!=null && samples.size>1) last.percent-first.percent else null
        text(canvas,change?.let { "CHANGE ${if(it>0) "+" else ""}$it percentage points" } ?: "Waiting for more samples",104f,25f,12f)
        text(canvas,"— DISCHARGING",479f,25f,11f,green); text(canvas,"— CHARGING",626f,25f,11f,cyan)
        val left=44f; val right=744f; val top=48f; val bottom=195f
        fun x(at: Long)=left+(right-left)*((at-start).toDouble()/(end-start).coerceAtLeast(1)).toFloat().coerceIn(0f,1f)
        fun y(percent: Int)=bottom-(bottom-top)*percent/100f
        val format=SimpleDateFormat(if(end-start>86400000L) "dd MMM" else "HH:mm",Locale.US)
        for(value in 0..100 step 20) {
            ink.color=grid; ink.strokeWidth=1f; canvas.drawLine(left,y(value),right,y(value),ink)
            text(canvas,"$value%",0f,y(value)+4f,10f)
        }
        for(i in 0..4) {
            val at=start+(end-start)*i/4; val axis=x(at)
            ink.color=grid; ink.strokeWidth=1f; canvas.drawLine(axis,top,axis,bottom,ink)
            text(canvas,format.format(Date(at)),(axis-16).coerceIn(left-16,right-36),215f,10f)
        }
        // The 80/60 hardware thresholds remain visible throughout the selected window.
        text(canvas,"80",right-19,y(80)-3,9f,dim); text(canvas,"60",right-19,y(60)-3,9f,dim)
        samples.zipWithNext().forEach { (a,b) ->
            if(b.at-a.at<=BatteryHistory.MINUTE) {
                ink.color=if(a.charging) cyan else green; ink.strokeWidth=2f
                canvas.drawLine(x(a.at),y(a.percent),x(b.at),y(b.percent),ink)
            }
        }
        // Draw isolated readings too, including the first reading of a new installation.
        samples.forEach { point -> ink.color=if(point.charging) cyan else green; canvas.drawCircle(x(point.at),y(point.percent),1.8f,ink) }
        when {
            error -> text(canvas,"History unavailable · retrying",250f,125f,14f,green)
            samples.isEmpty() -> text(canvas,"No samples in this window · start the relay",174f,125f,12f,green)
            samples.size==1 -> text(canvas,"First reading saved · next sample in one minute",162f,125f,12f,green)
        }
        last?.let { text(canvas,"LAST SAMPLE "+SimpleDateFormat("dd MMM HH:mm",Locale.US).format(Date(it.at)),left,236f,10f) }
        canvas.restore()
    }
}
