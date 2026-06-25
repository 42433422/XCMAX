# CI SSOT: generated from config/service_topology.yaml — DO NOT EDIT BY HAND
# 改拓扑请编辑该 yaml 后运行: python scripts/dev/service_topology_ssot.py generate --apply

"""服务拓扑常量（派生自 SSOT，零业务依赖，可被任意层 import）。"""

PRODUCTION_HOST = "xiu-ci.com"
PRODUCTION_SCHEME = "https"

SITE_ROOT_URL = "https://xiu-ci.com"
FHD_API_BASE_URL = "https://xiu-ci.com/fhd-api"
MARKET_BASE_URL = "https://xiu-ci.com/market"
LLM_V1_BASE_URL = "https://xiu-ci.com/v1"
MARKET_CATALOG_URL = "https://xiu-ci.com/api/market/catalog"
IM_WS_URL = "wss://xiu-ci.com/ws/im"

DESKTOP_FHD_LISTEN_PORT = 17500
FHD_API_LISTEN_PORT = 5000
FHD_API_UPSTREAM_PORT = 5100
MODSTORE_LISTEN_PORT = 8765

MUST_RUN_PROCESSES = ["web", "modstore-scheduler"]
