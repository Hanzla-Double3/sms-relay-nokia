package com.fay.smsrelay

import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.os.BatteryManager

data class BatterySample(val at: Long, val percent: Int, val charging: Boolean, val plugged: Boolean)

/** Separate bounded telemetry database; SMS duplicate guards are never migrated or pruned. */
class BatteryHistory internal constructor(context: Context, name: String="battery.db"):
    SQLiteOpenHelper(context.applicationContext,name,null,1) {
    companion object {
        const val MINUTE=60000L
        const val RETENTION=7*24*60*MINUTE
        const val MAX_ROWS=10081
        @Volatile private var instance: BatteryHistory?=null
        fun get(context: Context): BatteryHistory = instance ?: synchronized(this) {
            instance ?: BatteryHistory(context).also { instance=it }
        }
    }
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE samples(at INTEGER PRIMARY KEY, percent INTEGER NOT NULL CHECK(percent BETWEEN 0 AND 100), charging INTEGER NOT NULL, plugged INTEGER NOT NULL)")
    }
    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) { error("Unsupported battery history migration") }
    fun sample(context: Context) {
        val intent=context.registerReceiver(null,IntentFilter(Intent.ACTION_BATTERY_CHANGED)) ?: return
        val level=intent.getIntExtra(BatteryManager.EXTRA_LEVEL,-1)
        val scale=intent.getIntExtra(BatteryManager.EXTRA_SCALE,-1)
        if(level<0 || scale<=0 || level>scale) return
        record(BatterySample(System.currentTimeMillis(),(level.toLong()*100/scale).toInt(),PowerState.charging(intent),intent.getIntExtra(BatteryManager.EXTRA_PLUGGED,0)!=0))
    }
    @Synchronized fun record(sample: BatterySample) {
        require(sample.at>=0 && sample.percent in 0..100)
        val minute=sample.at/MINUTE*MINUTE
        val db=writableDatabase
        db.beginTransaction()
        try {
            // Clock rollback removes future readings; do not invent missing samples.
            db.delete("samples","at<? OR at>?",arrayOf((minute-RETENTION).toString(),minute.toString()))
            db.insertWithOnConflict("samples",null,ContentValues().apply {
                put("at",minute); put("percent",sample.percent); put("charging",if(sample.charging) 1 else 0); put("plugged",if(sample.plugged) 1 else 0)
            },SQLiteDatabase.CONFLICT_IGNORE)
            db.execSQL("DELETE FROM samples WHERE at NOT IN (SELECT at FROM samples ORDER BY at DESC LIMIT $MAX_ROWS)")
            db.setTransactionSuccessful()
        } finally { db.endTransaction() }
    }
    @Synchronized fun read(since: Long, now: Long=System.currentTimeMillis()): List<BatterySample> {
        val result=ArrayList<BatterySample>()
        readableDatabase.rawQuery("SELECT at,percent,charging,plugged FROM samples WHERE at>=? AND at<=? ORDER BY at LIMIT $MAX_ROWS",arrayOf(maxOf(since,now-RETENTION).toString(),now.toString())).use { c ->
            while(c.moveToNext()) result.add(BatterySample(c.getLong(0),c.getInt(1),c.getInt(2)!=0,c.getInt(3)!=0))
        }
        return result
    }
}
