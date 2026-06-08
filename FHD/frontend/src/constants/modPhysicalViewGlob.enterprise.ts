type ViewLoader = () => Promise<{ default: unknown }>

/** 企业版：预打包全部通用 bridge 的物理视图（与 hostViewGlob.enterprise 对齐） */
export const modPhysicalViewGlob = import.meta.glob(
  '../../../mods/*/frontend/views/**/*.vue',
) as Record<string, ViewLoader>
