/** MOD 商店 / 市场目录项（/api/mod-store/*） */

export interface ModCatalogItem {
  id: string
  name: string
  version: string
  author: string
  description: string
  package_file?: string
  pkg_id?: string
  download_url?: string
  source?: 'remote' | 'local' | string
  catalog_base_url?: string
  is_installed: boolean
  download_count?: number
  total_downloads?: number
  avg_rating?: number
  rating_count?: number
  created_at?: string
  dependencies?: Record<string, string>
  artifact?: string
  sha256?: string
}

/** 前端 UI 状态扩展（安装/卸载/更新进行中） */
export interface ModCatalogItemUi extends ModCatalogItem {
  installationInProgress?: boolean
  uninstallationInProgress?: boolean
  updateInProgress?: boolean
}
