package com.fay.smsrelay

import android.content.Context
import android.content.ContextWrapper
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import java.util.UUID

/** Real Keystore encryption with isolated preferences; never changes live phone provisioning. */
@RunWith(AndroidJUnit4::class)
class ConfigCacheDeviceTest {
    private val base=InstrumentationRegistry.getInstrumentation().targetContext
    private val name="cache-test-${UUID.randomUUID()}"
    private val context=object: ContextWrapper(base) {
        override fun getApplicationContext(): Context=this
        override fun getSharedPreferences(n: String,mode: Int)=base.getSharedPreferences(name,mode)
    }
    @After fun cleanup() { base.deleteSharedPreferences(name) }
    @Test fun unchangedProvisioningReusesDecryptedObjectAndOtherWriterInvalidatesIt() {
        val reader=Config(context); val writer=Config(context)
        val first=RelayConfig("wss://relay.example.com/ws/device","test-device","test-secret-0123456789",-1)
        writer.save(first)
        val loaded=reader.load()
        assertEquals(first,loaded)
        repeat(20) { assertSame(loaded,reader.load()) }
        // Display preference changes must not trigger another Keystore decrypt.
        writer.brightness=20
        assertSame(loaded,reader.load())
        val changed=first.copy(token="rotated-test-secret-0123456789",subscription=3)
        writer.save(changed)
        assertEquals(changed,reader.load())
        assertNotSame(loaded,reader.load())
    }
    @Test fun removedAndCorruptCredentialsCannotReturnStaleCachedSecrets() {
        val reader=Config(context); val writer=Config(context)
        assertNull(reader.load())
        writer.save(RelayConfig("wss://relay.example.com/ws/device","test-device","test-secret-0123456789",-1))
        assertNotNull(reader.load())
        base.getSharedPreferences(name,Context.MODE_PRIVATE).edit().remove("secret").commit()
        assertNull(reader.load())
        base.getSharedPreferences(name,Context.MODE_PRIVATE).edit().putString("secret","invalid").commit()
        assertNull(reader.load()); assertNull(reader.load())
    }
}
