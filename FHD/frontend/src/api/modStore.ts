import { apiFetch } from '@/utils/apiBase';
import { clearDeliverableStatusCache } from '@/utils/platformShellApi';
import type { ModCatalogItem, ModCatalogItemUi } from '@/types/modCatalog';

export type { ModCatalogItem, ModCatalogItemUi } from '@/types/modCatalog';

export interface ModCatalog {
  installed: ModCatalogItemUi[];
  available: ModCatalogItemUi[];
  indexed_count: number;
}

export interface MarketCatalogResult {
  items: ModCatalogItemUi[];
  total: number;
  collection: string;
}

export interface ModSearchResult {
  data: ModCatalogItemUi[];
  count: number;
}

export interface ModStatistics {
  total_downloads: number;
  total_installs: number;
  total_uninstalls: number;
  total_updates: number;
  avg_rating: number;
  rating_count: number;
}

export interface ModRating {
  id: number;
  mod_id: string;
  user_id: string;
  rating: number;
  comment: string;
  created_at: string;
}

export interface ModDetails {
  id: string;
  name: string;
  version: string;
  author: string;
  description: string;
  statistics: ModStatistics | null;
  ratings: ModRating[];
  rating_count: number;
}

export interface InstallResult {
  success: boolean;
  message: string;
  data: {
    id: string;
    name: string;
    version: string;
  };
}

export interface UploadResult {
  success: boolean;
  message: string;
  data: ModCatalogItemUi;
}

/**
 * 获取 MOD 目录
 */
export async function getModCatalog(): Promise<ModCatalog> {
  const response = await apiFetch('/api/mod-store/catalog');
  const data = await response.json();
  
  if (!data.success) {
    throw new Error(data.error || '获取 MOD 目录失败');
  }
  
  return data.data;
}

/** 按分类拉取修茈 AI 市场目录（经宿主 /api/mod-store/market-catalog 代理） */
export async function fetchMarketCatalog(params: {
  q?: string;
  collection?: string;
  artifact?: string;
  material_category?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<MarketCatalogResult> {
  const search = new URLSearchParams();
  search.set('limit', String(params.limit ?? 80));
  search.set('offset', String(params.offset ?? 0));
  if (params.q) search.set('q', params.q);
  if (params.collection) search.set('collection', params.collection);
  if (params.artifact) search.set('artifact', params.artifact);
  if (params.material_category) search.set('material_category', params.material_category);

  const response = await apiFetch(`/api/mod-store/market-catalog?${search}`, {
    timeoutMs: 120_000,
  });
  const data = await response.json();

  if (!data.success) {
    throw new Error(data.error || data.message || '获取 AI 市场目录失败');
  }

  return data.data as MarketCatalogResult;
}

/**
 * 搜索 MOD
 */
export async function searchMods(
  query?: string,
  author?: string,
  installed?: boolean,
  limit: number = 50
): Promise<ModSearchResult> {
  const params = new URLSearchParams();
  
  if (query) params.append('q', query);
  if (author) params.append('author', author);
  if (installed) params.append('installed', 'true');
  params.append('limit', limit.toString());
  
  const response = await apiFetch(`/api/mod-store/search?${params}`);
  const data = await response.json();
  
  if (!data.success) {
    throw new Error(data.error || '搜索失败');
  }
  
  return data.data;
}

/**
 * 获取热门 MOD
 */
export async function getPopularMods(limit: number = 10): Promise<ModCatalogItemUi[]> {
  const response = await apiFetch(`/api/mod-store/popular?limit=${limit}`);
  const data = await response.json();
  
  if (!data.success) {
    throw new Error(data.error || '获取热门 MOD 失败');
  }
  
  return data.data;
}

/**
 * 获取最新 MOD
 */
export async function getRecentMods(limit: number = 10): Promise<ModCatalogItemUi[]> {
  const response = await apiFetch(`/api/mod-store/recent?limit=${limit}`);
  const data = await response.json();
  
  if (!data.success) {
    throw new Error(data.error || '获取最新 MOD 失败');
  }
  
  return data.data;
}

/**
 * 获取 MOD 详情
 */
export async function getModDetails(modId: string): Promise<ModDetails> {
  const response = await apiFetch(`/api/mod-store/mod/${modId}/details`);
  const data = await response.json();
  
  if (!data.success) {
    throw new Error(data.error || '获取 MOD 详情失败');
  }
  
  return data.data;
}

/**
 * 上传 MOD 包
 */
export async function uploadModPackage(
  file: File,
  activate: boolean = false
): Promise<UploadResult> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('activate', activate.toString());
  
  const response = await apiFetch('/api/mod-store/upload', {
    method: 'POST',
    body: formData,
  });
  
  const data = await response.json();
  
  if (!data.success) {
    throw new Error(data.detail || data.error || '上传失败');
  }
  
  return data;
}

/**
 * 安装 MOD
 */
export async function installMod(mod: string | Pick<ModCatalogItemUi, 'id' | 'pkg_id' | 'version' | 'package_file'>): Promise<InstallResult> {
  const payload = typeof mod === 'string'
    ? { package_file: mod, activate: true, verify_signature: false }
    : {
        pkg_id: mod.pkg_id || mod.id,
        version: mod.version,
        package_file: mod.package_file,
        activate: true,
        verify_signature: false,
      };
  
  const response = await apiFetch('/api/mod-store/install', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  
  const data = await response.json();
  
  if (!data.success) {
    throw new Error(data.detail || data.error || '安装失败');
  }
  
  return data;
}

/**
 * 卸载 MOD
 */
export async function uninstallMod(modId: string): Promise<{ success: boolean; message: string }> {
  const formData = new FormData();
  formData.append('mod_id', modId);
  formData.append('remove_files', 'true');
  
  const response = await apiFetch('/api/mod-store/uninstall', {
    method: 'POST',
    body: formData,
  });
  
  const data = await response.json();
  
  if (!data.success) {
    throw new Error(data.detail || data.error || '卸载失败');
  }
  
  return data;
}

/**
 * 更新 MOD
 */
export async function updateMod(
  modId: string,
  packageFile: string
): Promise<InstallResult> {
  const payload = {
    mod_id: modId,
    package_file: packageFile,
    verify_signature: false,
  };
  
  const response = await apiFetch('/api/mod-store/update', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  
  const data = await response.json();
  
  if (!data.success) {
    throw new Error(data.detail || data.error || '更新失败');
  }
  
  return data;
}

/**
 * 验证 MOD 包
 */
export async function validateModPackage(packageFile: string): Promise<{
  success: boolean;
  message: string;
  data: any;
}> {
  const response = await apiFetch(`/api/mod-store/validate?package_file=${encodeURIComponent(packageFile)}`);
  const data = await response.json();
  return data;
}

/**
 * 检查可用更新
 */
export async function checkUpdates(): Promise<{
  updates_available: Array<{
    mod_id: string;
    current_version: string;
    new_version: string;
    package_file: string;
    name: string;
  }>;
  count: number;
}> {
  const response = await apiFetch('/api/mod-store/updates');
  const data = await response.json();
  
  if (!data.success) {
    throw new Error(data.error || '检查更新失败');
  }
  
  return data.data;
}

/**
 * 解析依赖关系
 */
export async function resolveDependencies(packageFile: string): Promise<{
  mod_id: string;
  dependencies: string[];
  satisfied: Array<{ id: string; version_spec: string; status: string; type: string }>;
  missing: Array<{ id: string; version_spec: string; status: string; type: string }>;
  can_install: boolean;
}> {
  const response = await apiFetch(`/api/mod-store/dependencies?package_file=${encodeURIComponent(packageFile)}`);
  const data = await response.json();
  
  if (!data.success) {
    throw new Error(data.error || '依赖解析失败');
  }
  
  return data.data;
}

/**
 * 对 MOD 评分
 */
export async function rateMod(
  modId: string,
  rating: number,
  comment: string = '',
  userId: string = ''
): Promise<{ success: boolean; message: string }> {
  const formData = new FormData();
  formData.append('rating', rating.toString());
  formData.append('comment', comment);
  formData.append('user_id', userId);
  
  const response = await apiFetch(`/api/mod-store/mod/${modId}/rate`, {
    method: 'POST',
    body: formData,
  });
  
  const data = await response.json();
  
  if (!data.success) {
    throw new Error(data.detail || data.error || '评分失败');
  }
  
  return data;
}

/**
 * 下载 MOD 包
 */
export async function downloadModPackage(packageFile: string): Promise<Blob> {
  const response = await apiFetch(`/api/mod-store/package/${packageFile}/download`);
  
  if (!response.ok) {
    throw new Error('下载失败');
  }
  
  return await response.blob();
}

/**
 * 删除 MOD 包
 */
export async function deleteModPackage(packageFile: string): Promise<{ success: boolean; message: string }> {
  const response = await apiFetch(`/api/mod-store/package/${encodeURIComponent(packageFile)}`, {
    method: 'DELETE',
  });
  
  const data = await response.json();
  
  if (!data.success) {
    throw new Error(data.detail || data.error || '删除失败');
  }
  
  return data;
}

/**
 * 重建 MOD 索引
 */
export async function rebuildIndex(): Promise<{
  success: boolean;
  data: { indexed: number; failed: number };
  message: string;
}> {
  const response = await apiFetch('/api/mod-store/index/rebuild', {
    method: 'POST',
  });
  
  const data = await response.json();
  
  if (!data.success) {
    throw new Error(data.error || '重建索引失败');
  }
  
  return data;
}

/** 使用修茈 PAT（mod:sync）从线上 /v1/mod-sync 拉 zip 并由本机后端安装到 mods/ */
export async function syncModstoreLibraryFromRemote(payload: {
  base_url?: string;
  baseUrl?: string;
  token: string;
  mod_ids?: string[] | string;
  all?: boolean;
}): Promise<{
  success: boolean;
  message?: string;
  data?: { installed: string[]; errors: string[] };
}> {
  const response = await apiFetch('/api/mod-store/sync-modstore-library', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    const detail = (data && (data.detail || data.message)) || response.statusText;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  clearDeliverableStatusCache();
  return data;
}

/** 一键装齐当前 edition 所需 Mod（先内置种子，再尝试 Catalog） */
/**
 * 安装「宿主基础能力（预装员工）」并 materialize 全部 bridge（非逐项 Mod）。
 */
export async function installHostFoundation(
  edition?: 'minimal' | 'generic' | 'full',
): Promise<{ success: boolean; message: string; data?: Record<string, unknown> }> {
  const q = edition ? `?edition=${encodeURIComponent(edition)}` : '';
  const response = await apiFetch(`/api/mod-store/install-host-foundation${q}`, {
    method: 'POST',
  });
  let data: { success?: boolean; message?: string; detail?: string; error?: string; data?: Record<string, unknown> } =
    {};
  try {
    data = (await response.json()) as typeof data;
  } catch {
    /* 非 JSON 响应 */
  }
  const errMsg =
    (typeof data.message === 'string' && data.message) ||
    (typeof data.detail === 'string' && data.detail) ||
    (typeof data.error === 'string' && data.error) ||
    '';
  if (!response.ok) {
    throw new Error(errMsg || response.statusText || '安装宿主基础员工包失败');
  }
  return {
    success: Boolean(data.success),
    message: errMsg || '安装完成',
    data: data.data,
  };
}

/** L2：从 industry-seeds 池安装所选行业中性 Mod（池缺失时 Catalog 兜底） */
export async function installIndustrySeed(
  industryId: string,
): Promise<{ success: boolean; message: string; data?: Record<string, unknown> }> {
  const response = await apiFetch('/api/mod-store/install-industry-seed', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ industry_id: String(industryId || '').trim() }),
  });
  let data: {
    success?: boolean;
    message?: string;
    detail?: string;
    error?: string;
    data?: Record<string, unknown>;
  } = {};
  try {
    data = (await response.json()) as typeof data;
  } catch {
    /* 非 JSON 响应 */
  }
  const errMsg =
    (typeof data.message === 'string' && data.message) ||
    (typeof data.detail === 'string' && data.detail) ||
    (typeof data.error === 'string' && data.error) ||
    '';
  if (!response.ok) {
    throw new Error(errMsg || response.statusText || '安装行业种子失败');
  }
  return {
    success: Boolean(data.success),
    message: errMsg || '安装完成',
    data: (data.data as Record<string, unknown> | undefined) ?? undefined,
  };
}

export async function bootstrapEditionPack(
  edition: 'minimal' | 'generic' | 'full' = 'generic',
): Promise<{ success: boolean; message?: string; data?: Record<string, unknown> }> {
  const response = await apiFetch(
    `/api/mod-store/bootstrap-edition-pack?edition=${encodeURIComponent(edition)}`,
    { method: 'POST' },
  );
  const data = await response.json();
  clearDeliverableStatusCache();
  if (!response.ok) {
    const detail = (data && (data.detail || data.message)) || response.statusText;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return data;
}

/** 刷新 employee_pack HTTP 路由与 Planner 工具注册表 */
export async function reloadEmployeePacks(
  packId?: string,
): Promise<{ success: boolean; message: string; data?: Record<string, unknown> }> {
  const response = await apiFetch('/api/mod-store/reload-employees', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(packId ? { pack_id: packId } : {}),
  });
  const data = await response.json();
  if (!response.ok) {
    const detail = (data && (data.detail || data.message)) || response.statusText;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return {
    success: Boolean(data.success),
    message: String(data.message || '已刷新'),
    data: data.data,
  };
}

/** 逐包安装办公 10 员工并刷新 Planner registry */
export async function installOfficeEmployeePack(options?: {
  onProgress?: (message: string) => void;
}): Promise<{ success: boolean; errors: string[] }> {
  const { OFFICE_EMPLOYEE_PKG_IDS } = await import('@/constants/officeEmployeePack');
  const response = await apiFetch('/api/mod-store/catalog', { timeoutMs: 90_000 });
  const body = await response.json();
  const available: ModCatalogItemUi[] = body?.data?.available || body?.available || [];
  const errors: string[] = [];
  const targets = OFFICE_EMPLOYEE_PKG_IDS.map((id) =>
    available.find((m) => (m.pkg_id || m.id) === id),
  ).filter(Boolean) as ModCatalogItemUi[];

  for (let i = 0; i < targets.length; i += 1) {
    const mod = targets[i];
    const pkgId = mod.pkg_id || mod.id;
    options?.onProgress?.(`正在安装办公员工 ${i + 1}/${targets.length}：${mod.name || pkgId}`);
    if (mod.is_installed) continue;
    try {
      const ir = await installMod(mod);
      if (!ir.success) {
        errors.push(`${mod.name || pkgId}：${ir.message || '安装失败'}`);
      }
    } catch (err) {
      errors.push(`${mod.name || pkgId}：${err instanceof Error ? err.message : '安装失败'}`);
    }
  }

  try {
    await reloadEmployeePacks();
  } catch (err) {
    errors.push(err instanceof Error ? err.message : '刷新员工工具注册表失败');
  }

  return { success: errors.length === 0, errors };
}
