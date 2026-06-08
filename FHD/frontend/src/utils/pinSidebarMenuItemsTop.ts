/** 始终固定在侧栏主菜单顶部的宿主项（优先于 Mod 前置与用户拖拽排序） */
import { ADMIN_SIDEBAR_PINNED_TOP_KEYS } from '@/constants/adminOperatorNav'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'

export const SIDEBAR_PINNED_TOP_KEYS = ['chat'] as const

export function pinSidebarMenuItemsTop<T extends { key: string }>(items: T[]): T[] {
  if (!items.length) return items
  const pinKeys = isAdminConsoleSpa()
    ? [...ADMIN_SIDEBAR_PINNED_TOP_KEYS]
    : [...SIDEBAR_PINNED_TOP_KEYS]
  const pinSet = new Set<string>(pinKeys)
  const pinned: T[] = []
  for (const key of pinKeys) {
    const item = items.find((row) => row.key === key)
    if (item) pinned.push(item)
  }
  const rest = items.filter((row) => !pinSet.has(row.key))
  return [...pinned, ...rest]
}
