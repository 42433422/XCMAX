package com.xiuci.xcagi.mobile.core.audit

import android.content.Intent
import android.net.Uri
import com.xiuci.xcagi.mobile.BuildConfig
import com.xiuci.xcagi.mobile.navigation.Routes

/** P-App 表面巡检：深链 / Intent 启动参数（Maestro · adb · CI）。 */
data class SurfaceAuditAuth(
    val accessToken: String,
    val refreshToken: String,
    val sessionId: String,
    val username: String,
    val userId: Int,
    val marketAccess: String,
    val marketRefresh: String,
)

data class SurfaceAuditLaunch(
    val enabled: Boolean,
    val route: String?,
    val fhdHost: String?,
    val fresh: Boolean,
    val skipUpdate: Boolean,
    val auth: SurfaceAuditAuth?,
)

/** 进程内巡检标志（MainActivity 写入、AppViewModel 读取，避免更新弹窗与 init 竞态）。 */
object SurfaceAuditRuntime {
    @Volatile
    var enabled: Boolean = false

    @Volatile
    var skipUpdate: Boolean = false

    fun apply(launch: SurfaceAuditLaunch) {
        enabled = launch.enabled
        skipUpdate = launch.enabled && launch.skipUpdate
    }

    fun clear() {
        enabled = false
        skipUpdate = false
    }
}

object SurfaceAudit {
    const val EXTRA_ENABLED = "surface_audit"
    const val EXTRA_ROUTE = "audit_route"
    const val EXTRA_FHD_HOST = "audit_fhd_host"
    const val EXTRA_FRESH = "audit_fresh"
    const val EXTRA_SKIP_UPDATE = "audit_skip_update"
    const val EXTRA_ACCESS = "audit_access_token"
    const val EXTRA_REFRESH = "audit_refresh_token"
    const val EXTRA_SESSION = "audit_session_id"
    const val EXTRA_USERNAME = "audit_username"
    const val EXTRA_USER_ID = "audit_user_id"
    const val EXTRA_MARKET_ACCESS = "audit_market_access"
    const val EXTRA_MARKET_REFRESH = "audit_market_refresh"

    /** 与 config/surface_audit_pages.json android_route 对齐的可导航路由。 */
    val navigableRoutes: Set<String> = setOf(
        Routes.LEGAL,
        Routes.CONNECT,
        Routes.CONNECT_PC,
        Routes.AUTH,
        Routes.REGISTER,
        Routes.HOME_HUB,
        Routes.CHAT,
        Routes.WORK,
        Routes.DISCOVER,
        Routes.WORKBENCH,
        Routes.PROFILE,
        Routes.IM,
        Routes.APPROVAL,
        Routes.ERP_OVERVIEW,
        Routes.ERP,
        Routes.ERP_TAB.replace("{tabIndex}", "{tab_index}"),
        Routes.BRIDGE,
        Routes.MARKET,
        Routes.MODS,
        Routes.MOD_WEB.replace("{modId}", "{mod_id}"),
        Routes.OCR,
        Routes.LONGTAIL,
        Routes.SETTINGS,
        Routes.ABOUT,
        Routes.SCAN_QR,
    )

    fun parseIntent(intent: Intent?): SurfaceAuditLaunch {
        if (!BuildConfig.DEBUG) return SurfaceAuditLaunch(false, null, null, false, false, null)
        if (intent == null) return SurfaceAuditLaunch(false, null, null, false, false, null)
        val fromExtra = intent.getBooleanExtra(EXTRA_ENABLED, false)
        val routeExtra = intent.getStringExtra(EXTRA_ROUTE)?.trim().orEmpty()
        val hostExtra = intent.getStringExtra(EXTRA_FHD_HOST)?.trim().orEmpty()
        val freshExtra = intent.getBooleanExtra(EXTRA_FRESH, false)
        val skipUpdateExtra = intent.getBooleanExtra(EXTRA_SKIP_UPDATE, true)

        val data: Uri? = intent.data
        val auth = parseAuth(intent)

        if (data != null && data.scheme == "xcagi" && data.host == "audit") {
            val segments = data.pathSegments
            val route = when {
                segments.size >= 2 && segments[0] == "nav" -> segments[1]
                segments.isNotEmpty() -> segments.last()
                else -> routeExtra
            }
            val fresh = freshExtra || data.getQueryParameter("fresh") == "1"
            val host = data.getQueryParameter("fhd_host")?.trim().orEmpty().ifBlank { hostExtra }
            return SurfaceAuditLaunch(
                enabled = true,
                route = normalizeRoute(route),
                fhdHost = host.ifBlank { null },
                fresh = fresh,
                skipUpdate = skipUpdateExtra,
                auth = auth,
            )
        }

        if (fromExtra || routeExtra.isNotBlank()) {
            return SurfaceAuditLaunch(
                enabled = fromExtra || routeExtra.isNotBlank(),
                route = normalizeRoute(routeExtra).takeIf { it.isNotBlank() },
                fhdHost = hostExtra.ifBlank { null },
                fresh = freshExtra,
                skipUpdate = skipUpdateExtra,
                auth = auth,
            )
        }
        return SurfaceAuditLaunch(false, null, null, false, false, null)
    }

    private fun parseAuth(intent: Intent): SurfaceAuditAuth? {
        val access = intent.getStringExtra(EXTRA_ACCESS)?.trim().orEmpty()
        if (access.isBlank()) return null
        return SurfaceAuditAuth(
            accessToken = access,
            refreshToken = intent.getStringExtra(EXTRA_REFRESH)?.trim().orEmpty(),
            sessionId = intent.getStringExtra(EXTRA_SESSION)?.trim().orEmpty(),
            username = intent.getStringExtra(EXTRA_USERNAME)?.trim().orEmpty().ifBlank { "admin" },
            userId = intent.getIntExtra(EXTRA_USER_ID, 1),
            marketAccess = intent.getStringExtra(EXTRA_MARKET_ACCESS)?.trim().orEmpty(),
            marketRefresh = intent.getStringExtra(EXTRA_MARKET_REFRESH)?.trim().orEmpty(),
        )
    }

    /** 将巡检 id（如 mod_web）映射为 NavHost route。 */
    fun normalizeRoute(raw: String?): String {
        val r = raw?.trim().orEmpty()
        if (r.isBlank()) return ""
        return when (r) {
            "im", "im_messenger" -> Routes.IM
            "erp_overview" -> Routes.ERP_OVERVIEW
            "erp_tab/0", "erp_customers" -> Routes.erpTab(0)
            "erp_tab/1", "erp_shipments" -> Routes.erpTab(1)
            "erp_tab/2", "erp_inventory" -> Routes.erpTab(2)
            "work" -> Routes.WORK
            "discover" -> Routes.DISCOVER
            "mod_web", "mod/{modId}", "mod/{mod_id}" -> Routes.MOD_WEB.replace("{modId}", "taiyangniao-pro")
            "splash" -> Routes.HOME_HUB
            else -> {
                if (r.startsWith("mod/")) r.replace("{mod_id}", "taiyangniao-pro")
                else r
            }
        }
    }

    fun needsFreshSession(route: String): Boolean =
        route in setOf(Routes.LEGAL, Routes.CONNECT, Routes.AUTH, Routes.REGISTER)
}
