import { apiFetch } from '@/utils/apiBase';

export interface ModInfo {
  id: string;
  name: string;
  version: string;
  author: string;
  description: string;
  package_file?: string;
  is_installed: boolean;
  download_count?: number;
  total_downloads?: number;
  avg_rating?: number;
  rating_count?: number;
  created_at?: string;
  dependencies?: Record<string, string>;
  installationInProgress?: boolean;
  uninstallationInProgress?: boolean;
  updateInProgress?: boolean;
}

export interface ModCatalog {
  installed: ModInfo[];
  available: ModInfo[];
  indexed_count: number;
}

export interface ModSearchResult {
  data: ModInfo[];
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
  data: ModInfo;
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
export async function getPopularMods(limit: number = 10): Promise<ModInfo[]> {
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
export async function getRecentMods(limit: number = 10): Promise<ModInfo[]> {
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
export async function installMod(packageFile: string): Promise<InstallResult> {
  const formData = new FormData();
  formData.append('package_file', packageFile);
  formData.append('activate', 'true');
  formData.append('verify_signature', 'true');
  
  const response = await apiFetch('/api/mod-store/install', {
    method: 'POST',
    body: formData,
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
  const formData = new FormData();
  formData.append('mod_id', modId);
  formData.append('package_file', packageFile);
  formData.append('verify_signature', 'true');
  
  const response = await apiFetch('/api/mod-store/update', {
    method: 'POST',
    body: formData,
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
