package com.xiuci.xcagi.mobile

import androidx.test.ext.junit.rules.ActivityScenarioRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertNotNull
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * 发版 smoke：主 Activity 可启动（与 test_mobile_api.py API 契约互补，非替代）。
 */
@RunWith(AndroidJUnit4::class)
class LoginSmokeTest {

    @get:Rule
    val activityRule = ActivityScenarioRule(MainActivity::class.java)

    @Test
    fun mainActivityLaunches() {
        activityRule.scenario.onActivity { activity ->
            assertNotNull(activity)
        }
    }
}
