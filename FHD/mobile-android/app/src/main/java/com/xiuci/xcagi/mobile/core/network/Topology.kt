// CI SSOT: generated from config/service_topology.yaml — DO NOT EDIT BY HAND
// 改拓扑请编辑该 yaml 后运行: python scripts/dev/service_topology_ssot.py generate --apply

package com.xiuci.xcagi.mobile.core.network

object Topology {
    const val PRODUCTION_HOST = "xiu-ci.com"
    const val PRODUCTION_SCHEME = "https"
    const val SITE_ROOT_URL = "https://xiu-ci.com"
    const val FHD_API_BASE_URL = "https://xiu-ci.com/fhd-api"
    const val MARKET_BASE_URL = "https://xiu-ci.com/market"
    const val LLM_V1_BASE_URL = "https://xiu-ci.com/v1"
    const val MARKET_CATALOG_URL = "https://xiu-ci.com/api/market/catalog"
    const val IM_WS_URL = "wss://xiu-ci.com/ws/im"
    const val DESKTOP_FHD_LISTEN_PORT = 17500
    const val FHD_API_LISTEN_PORT = 5000
    const val FHD_API_UPSTREAM_PORT = 5100
    const val MODSTORE_LISTEN_PORT = 8765
    val MUST_RUN_PROCESSES = listOf("web", "modstore-scheduler")
}
