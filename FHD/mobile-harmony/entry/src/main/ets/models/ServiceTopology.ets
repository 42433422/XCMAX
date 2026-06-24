// CI SSOT: generated from config/service_topology.yaml — DO NOT EDIT BY HAND
// 改拓扑请编辑该 yaml 后运行: python scripts/dev/service_topology_ssot.py generate --apply

export const PRODUCTION_HOST: string = 'xiu-ci.com';
export const PRODUCTION_SCHEME: string = 'https';

export const SITE_ROOT_URL: string = 'https://xiu-ci.com';
export const FHD_API_BASE_URL: string = 'https://xiu-ci.com/fhd-api';
export const MARKET_BASE_URL: string = 'https://xiu-ci.com/market';
export const LLM_V1_BASE_URL: string = 'https://xiu-ci.com/v1';
export const MARKET_CATALOG_URL: string = 'https://xiu-ci.com/api/market/catalog';
export const IM_WS_URL: string = 'wss://xiu-ci.com/ws/im';

export const DESKTOP_FHD_LISTEN_PORT: number = 17500;
export const FHD_API_LISTEN_PORT: number = 5000;
export const FHD_API_UPSTREAM_PORT: number = 5100;
export const MODSTORE_LISTEN_PORT: number = 8765;

export const MUST_RUN_PROCESSES: string[] = ['web', 'modstore-scheduler'];
