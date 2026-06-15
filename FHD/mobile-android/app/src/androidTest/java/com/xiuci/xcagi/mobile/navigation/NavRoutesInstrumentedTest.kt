package com.xiuci.xcagi.mobile.navigation

import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

/** 真机/模拟器：底栏 4 Tab 路由常量稳定。 */
@RunWith(AndroidJUnit4::class)
class NavRoutesInstrumentedTest {

    @Test
    fun bottomNavRoutes_areStable() {
        val tabs = listOf(Routes.CHAT, Routes.WORK, Routes.DISCOVER, Routes.PROFILE)
        assertEquals(4, tabs.size)
        assertEquals("chat", Routes.CHAT)
        assertEquals("work", Routes.WORK)
        assertEquals("discover", Routes.DISCOVER)
        assertEquals("profile", Routes.PROFILE)
    }
}
