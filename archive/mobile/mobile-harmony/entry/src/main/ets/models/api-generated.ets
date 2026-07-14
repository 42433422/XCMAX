// AUTO-GENERATED — 请勿手动编辑。
// 来源：contracts/openapi.json（由 scripts/dev/gen_arkts_models.py 生成）
// 共 23 个 mobile 相关 schema。
// 手动定义的类型（如 MobileEnvelope<T>、AiEmployeeProfile）仍保留在 MobileModels.ets。


export interface MobileLoginRequest {
  username: string;
  password: string;
  account_kind?: string;
}

export interface MobileRefreshRequest {
  refresh_token: string;
}

export interface ModStoreCatalogPayload {
  installed: Record<string, Object>[];
  available: Record<string, Object>[];
  indexed_count: number;
}

export interface ModStoreCatalogResponse {
  success?: boolean;
  data: ModStoreCatalogPayload;
}

export interface ModStoreDependenciesResponse {
  success?: boolean;
  data: Record<string, Object>;
}

export interface ModStoreDetailData {
  id: string;
  name: string;
  version: string;
  author: string;
  description: string;
  statistics?: Object;
  ratings?: Object[];
  rating_count?: number;
  source: string;
  catalog_base_url: string;
}

export interface ModStoreDetailResponse {
  success?: boolean;
  data: ModStoreDetailData;
}

export interface ModStoreInstallResult {
  success: boolean;
  message: string;
  data?: Object;
}

export interface ModStoreListResponse {
  success?: boolean;
  data: Record<string, Object>[];
}

export interface ModStoreMarketCatalogPayload {
  items: Record<string, Object>[];
  total: number;
  collection?: string;
}

export interface ModStoreMarketCatalogResponse {
  success?: boolean;
  data: ModStoreMarketCatalogPayload;
}

export interface ModStoreNotImplementedResponse {
  success?: boolean;
  detail: string;
}

export interface ModStoreRebuildResponse {
  success?: boolean;
  data: Record<string, Object>;
  message?: string | Object;
}

export interface ModStoreSimpleResponse {
  success: boolean;
  message?: string | Object;
  data?: Object;
}

export interface ModStoreUpdatesResponse {
  success?: boolean;
  data: Record<string, Object>;
}

export interface PairingExchangeBody {
  nonce?: string;
  code?: string;
}

export interface PairingIssueBody {
  host?: string;
  port?: number;
}

export interface PairingLookupBody {
  code: string;
}

export interface SyncAckBody {
  cursor?: number;
}

export interface SyncPullBody {
  since_cursor?: number;
}

export interface SyncPushBody {
  items?: SyncPushItem[];
}

export interface SyncPushItem {
  entity_type: string;
  entity_id: string;
  operation?: string;
  payload?: Record<string, Object>;
}

export interface UserRoleAssign {
  role: string;
}
