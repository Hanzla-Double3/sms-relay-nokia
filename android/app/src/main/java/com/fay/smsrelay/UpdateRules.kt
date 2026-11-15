package com.fay.smsrelay

import org.json.JSONObject
import java.security.KeyFactory
import java.security.Signature
import java.security.spec.X509EncodedKeySpec
import java.util.Base64

data class AppRelease(val code: Long,val name: String,val hash: String,val size: Long)

object UpdateRules {
    const val PUBLIC_KEY="MIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEA7VtnWWDnobqXy6vQyaLlxL2d64F6GqnB/wYfS0wTj4hUf1OqReP3deDrzqb9Svfy+zcqWNUuH3ALpSLVwnrQpInYWK1Ka/qx0lvRCIK3sHvoTGRcO9BlJa4iIx/CEDblJeRaAteG1k4/hYhOEHZVTounop1OvZdym6/yZIpHRg4IWJZMWddnMdjyILTYr8TadE2cz83ynqfcik2Utj2JjuJP9EEXYifDVXmquNV5lNHW/IFfoEskMf//ASvewWYjcL6ueVnj2vrMk02pW8d8SXTwlKA/Kc/1Bu25rfNYM+1QOhrMAu9YV7GVcDeYpgc9QPa32W2CmRZzf/yqmh+1ZFLsmWQJmz5TmhFipPGlOXO3UcD1YS657JhTzlkiIuGiTTKUhBtakVTlNBM71nEt8eyTu4RLl/IIWKcra0DrP1U0Z7VnwEYEUExRq4cqp0xhzTk5KRuNTzzdCvqyY57CqZ8ywU4DrEDivUi9+sLNICxntIB/AjiQ7wqOUkq3KOFHAgMBAAE="
    fun verify(envelope: JSONObject,currentCode: Long,publicKey: String=PUBLIC_KEY): AppRelease {
        require(envelope.toString().length<=8192)
        val payload=Base64.getDecoder().decode(envelope.getString("payload"))
        val signature=Base64.getDecoder().decode(envelope.getString("signature"))
        val key=KeyFactory.getInstance("RSA").generatePublic(X509EncodedKeySpec(Base64.getDecoder().decode(publicKey)))
        require(try { Signature.getInstance("SHA256withRSA").run { initVerify(key); update(payload); verify(signature) } } catch (_: java.security.SignatureException) { false }) { "Invalid release signature" }
        val data=JSONObject(String(payload,Charsets.UTF_8))
        require(data.getString("package")=="com.fay.smsrelay")
        val release=AppRelease(data.getLong("version_code"),data.getString("version_name"),data.getString("sha256"),data.getLong("size"))
        require(release.code>currentCode && release.code<=Int.MAX_VALUE && release.name.matches(Regex("[0-9]+\\.[0-9]+\\.[0-9]+")))
        require(release.hash.matches(Regex("[a-f0-9]{64}")) && release.size in 1..20_000_000)
        return release
    }
}
