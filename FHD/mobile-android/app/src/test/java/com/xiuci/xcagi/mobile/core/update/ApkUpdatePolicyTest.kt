package com.xiuci.xcagi.mobile.core.update

import java.io.DataOutputStream
import org.junit.Assert.assertEquals
import org.junit.Assert.fail
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class ApkUpdatePolicyTest {
    @get:Rule
    val tmp = TemporaryFolder()

    @Test
    fun validateDownloadUrlAcceptsHttpsApk() {
        val url =
                ApkUpdatePolicy.validateDownloadUrl(
                        " https://xiu-ci.com/download/enterprise/XCAGI-Enterprise-Android-11.apk "
                )

        assertEquals(
                "https://xiu-ci.com/download/enterprise/XCAGI-Enterprise-Android-11.apk",
                url,
        )
    }

    @Test
    fun validateDownloadUrlRejectsNonApkSchemesAndFiles() {
        assertInvalid("file:///sdcard/update.apk")
        assertInvalid("https://xiu-ci.com/download/update.zip")
        assertInvalid("https:///download/update.apk")
        assertInvalid("")
    }

    @Test
    fun apkFileNameRemovesUnsafePathCharacters() {
        assertEquals(
                "XCAGI-Android-11.0.0-beta.._evil.apk",
                ApkUpdatePolicy.apkFileName("11.0.0-beta../evil"),
        )
    }

    @Test
    fun deltaPatchCanRebuildTargetFromCopyAndDataCommands() {
        val old = tmp.newFile("old.apk").apply { writeBytes("abcdef123456".toByteArray()) }
        val patch = tmp.newFile("delta.xcapkdiff")
        val out = tmp.newFile("new.apk").apply { delete() }

        DataOutputStream(patch.outputStream()).use { stream ->
            stream.write("XCAGIDLT1".toByteArray())
            stream.writeByte(0)
            stream.writeLong(0)
            stream.writeInt(3)
            stream.writeByte(1)
            stream.writeInt(3)
            stream.write("XYZ".toByteArray())
            stream.writeByte(0)
            stream.writeLong(6)
            stream.writeInt(6)
            stream.writeByte(2)
        }

        XcagiDeltaPatch.apply(old, patch, out)

        assertEquals("abcXYZ123456", out.readText())
    }

    private fun assertInvalid(raw: String) {
        try {
            ApkUpdatePolicy.validateDownloadUrl(raw)
            fail("Expected invalid APK update URL: $raw")
        } catch (_: IllegalArgumentException) {
        }
    }
}
