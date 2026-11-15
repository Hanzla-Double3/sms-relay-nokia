package com.fay.smsrelay

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

data class RelayConfig(val url: String, val device: String, val token: String, val subscription: Int = -1)

class Config(private val context: Context) {
    private val prefs = context.getSharedPreferences("relay_config", Context.MODE_PRIVATE)
    private data class Provisioning(val secret: String?, val url: String, val device: String, val subscription: Int)
    private var cachedFields: Provisioning?=null
    private var cachedConfig: RelayConfig?=null
    var enabled: Boolean
        get() = prefs.getBoolean("enabled", false)
        set(value) { prefs.edit().putBoolean("enabled", value).commit() }
    var awake: Boolean
        get() = prefs.getBoolean("awake", false)
        set(value) { prefs.edit().putBoolean("awake", value).apply() }
    var brightness: Int
        get() = prefs.getInt("brightness", 40).coerceIn(5,100)
        set(value) { prefs.edit().putInt("brightness", value.coerceIn(5,100)).apply() }
    var adaptiveBrightness: Boolean
        get() = prefs.getBoolean("adaptive_brightness", false)
        set(value) { prefs.edit().putBoolean("adaptive_brightness",value).apply() }
    var chargeLimit: Boolean
        get() = prefs.getBoolean("charge_limit", true)
        set(value) { prefs.edit().putBoolean("charge_limit",value).commit() }
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey("relay_config", null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder("relay_config", KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    fun validate(config: RelayConfig) {
        val parsed = config.url.replaceFirst("wss://", "https://").replaceFirst("ws://", "http://").toHttpUrlOrNull()
        require(parsed != null && parsed.encodedPath == "/ws/device" && parsed.username.isEmpty() && parsed.password.isEmpty() && parsed.query == null && parsed.fragment == null) { "Use a WebSocket URL ending /ws/device, without credentials or query." }
        require(config.url.startsWith("wss://") || (BuildConfig.DEBUG && config.url.startsWith("ws://") && parsed.host in setOf("127.0.0.1", "localhost"))) { "WSS is required. Debug builds permit loopback only." }
        require(config.device.matches(Regex("[A-Za-z0-9_-]{1,64}"))) { "Invalid device ID." }
        require(config.token.length in 16..256 && config.token.all { it.code in 33..126 }) { "Token must be 16–256 printable characters." }
        require(config.subscription >= -1) { "Invalid subscription ID." }
    }
    fun save(config: RelayConfig) {
        validate(config)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val secret = Base64.encodeToString(cipher.iv + cipher.doFinal(config.token.toByteArray()), Base64.NO_WRAP)
        check(prefs.edit().putString("url", config.url).putString("device", config.device).putString("secret", secret).putInt("sub",config.subscription).commit())
    }
    @Synchronized fun load(): RelayConfig? {
        val fields=Provisioning(prefs.getString("secret",null),prefs.getString("url","") ?: "",prefs.getString("device","") ?: "",prefs.getInt("sub",-1))
        if(fields==cachedFields) return cachedConfig
        cachedFields=fields
        cachedConfig=try {
            val secret=fields.secret
            if(secret==null) { cachedConfig=null; return null }
            val bytes=Base64.decode(secret,Base64.NO_WRAP)
            val cipher=Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE,key(),GCMParameterSpec(128,bytes.copyOfRange(0,12))) }
            RelayConfig(fields.url,fields.device,String(cipher.doFinal(bytes.copyOfRange(12,bytes.size))),fields.subscription)
        } catch (_: Exception) { null }
        return cachedConfig
    }
}
