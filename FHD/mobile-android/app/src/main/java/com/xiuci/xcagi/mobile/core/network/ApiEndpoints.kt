package com.xiuci.xcagi.mobile.core.network

/**
 * API 端点常量表。
 *
 * 所有 `api/mobile/v1/...` 路径集中于此，端点变更时只需修改本文件。
 * Retrofit 注解中使用 `@GET(ApiEndpoints.HEALTH)` 替代硬编码字符串。
 */
object ApiEndpoints {
    const val BASE = "api/mobile/v1"

    // 健康检查
    const val HEALTH = "$BASE/health"

    // 认证
    const val AUTH_LOGIN = "$BASE/auth/login"
    const val AUTH_LOGIN_WITH_PHONE_CODE = "$BASE/auth/login-with-phone-code"
    const val AUTH_QR_CONFIRM = "$BASE/auth/qr/confirm"
    const val AUTH_OIDC_EXCHANGE = "$BASE/auth/oidc/exchange"
    const val AUTH_REFRESH = "$BASE/auth/refresh"

    // 主机发现
    const val HOST_DISCOVER_HINT = "$BASE/host/discover-hint"

    // 用户信息
    const val ME = "$BASE/me"

    // 审批
    const val APPROVAL_REQUESTS = "$BASE/approval/requests"

    // 客户
    const val CUSTOMERS = "$BASE/customers"

    // 发货
    const val SHIPMENTS = "$BASE/shipments"

    // 服务桥
    const val SERVICE_BRIDGE_REQUESTS = "$BASE/service-bridge/requests"
    const val SERVICE_BRIDGE_REQUESTS_RESPOND = "$BASE/service-bridge/requests/{id}/respond"

    // MOD
    const val MODS = "$BASE/mods"
    const val PLATFORM_SHELL = "$BASE/platform-shell"

    // 首页
    const val HOME = "$BASE/home"
    const val ADMIN_HOME = "$BASE/admin/home"

    // 同步
    const val SYNC_STATUS = "$BASE/sync/status"
    const val SYNC_PULL = "$BASE/sync/pull"
    const val SYNC_PUSH = "$BASE/sync/push"
    const val SYNC_CONFLICTS = "$BASE/sync/conflicts"

    // 设备
    const val DEVICES_REGISTER = "$BASE/devices/register"

    // 配对
    const val PAIRING_EXCHANGE = "$BASE/pairing/exchange"
    const val PAIRING_ISSUE = "$BASE/pairing/issue"

    // 中继
    const val RELAY_MOBILE_CONFIRM = "$BASE/relay/mobile/confirm"
    const val RELAY_MOBILE_CONFIRM_CODE = "$BASE/relay/mobile/confirm-code"
    const val RELAY_MOBILE_DESKTOPS = "$BASE/relay/mobile/desktops"
    const val RELAY_TASKS = "$BASE/relay/tasks"
    const val RELAY_TASKS_DETAIL = "$BASE/relay/tasks/{taskId}"

    // 客服
    const val CS_INFO = "$BASE/cs/info"
    const val CS_MESSAGES = "$BASE/cs/messages"

    // 管理员
    const val ADMIN_CODEX_SUPER_EMPLOYEE_MESSAGES = "$BASE/admin/codex-super-employee/messages"
}
