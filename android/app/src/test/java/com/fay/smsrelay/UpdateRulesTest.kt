package com.fay.smsrelay

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.security.KeyPairGenerator
import java.security.Signature
import java.util.Base64

class UpdateRulesTest {
    private val key=KeyPairGenerator.getInstance("RSA").apply { initialize(2048) }.generateKeyPair()
    private fun payload()=JSONObject().put("package","com.fay.smsrelay").put("version_code",9).put("version_name","0.6.1").put("sha256","a".repeat(64)).put("size",3000)
    private fun signed(payload: JSONObject): JSONObject {
        val raw=payload.toString().toByteArray()
        val signature=Signature.getInstance("SHA256withRSA").run { initSign(key.private); update(raw); sign() }
        return JSONObject().put("payload",Base64.getEncoder().encodeToString(raw)).put("signature",Base64.getEncoder().encodeToString(signature))
    }
    private fun verify(envelope: JSONObject,current: Long=8)=UpdateRules.verify(envelope,current,Base64.getEncoder().encodeToString(key.public.encoded))
    @Test fun acceptsSignedNewRelease() { assertEquals(9L,verify(signed(payload())).code) }
    @Test fun rejectsTampering() { val envelope=signed(payload());envelope.put("payload",Base64.getEncoder().encodeToString(payload().put("version_code",99).toString().toByteArray()));assertThrows(IllegalArgumentException::class.java) { verify(envelope) } }
    @Test fun rejectsWrongSigner() { assertThrows(IllegalArgumentException::class.java) { UpdateRules.verify(signed(payload()),8) } }
    @Test fun rejectsDowngradeAndSameVersion() { for(code in listOf(9L,10L)) assertThrows(IllegalArgumentException::class.java) { verify(signed(payload()),code) } }
    @Test fun rejectsUntrustedMetadata() { for(data in listOf(payload().put("package","other"),payload().put("sha256","bad"),payload().put("size",20_000_001),payload().put("version_name","shell;command"))) assertThrows(IllegalArgumentException::class.java) { verify(signed(data)) } }
}
