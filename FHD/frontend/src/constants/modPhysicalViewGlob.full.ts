type ViewLoader = () => Promise<{ default: unknown }>

/** full 构建：Mod 物理视图统一从 SSOT `mods/` 加载（不再读 mods-admin-runtime 副本） */
export const modPhysicalViewGlob = {
  ...import.meta.glob('../../../mods/*/frontend/views/**/*.vue'),
} as Record<string, ViewLoader>
