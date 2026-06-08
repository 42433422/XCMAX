/** 市场商品本地收藏（书签），与服务器「点赞」独立，仅存于本机。 */
const STORAGE_KEY = 'market_catalog_saved_v1'

function readIds(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return new Set()
    const arr = JSON.parse(raw) as unknown
    if (!Array.isArray(arr)) return new Set()
    return new Set(arr.map((x) => String(x)))
  } catch {
    return new Set()
  }
}

function writeIds(ids: Set<string>) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...ids]))
}

export function isCatalogSaved(catalogId: string | number | undefined | null): boolean {
  if (catalogId == null || catalogId === '') return false
  return readIds().has(String(catalogId))
}

export function toggleCatalogSaved(catalogId: string | number): boolean {
  const key = String(catalogId)
  const ids = readIds()
  if (ids.has(key)) {
    ids.delete(key)
    writeIds(ids)
    return false
  }
  ids.add(key)
  writeIds(ids)
  return true
}
