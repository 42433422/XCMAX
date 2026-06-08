type ViewLoader = () => Promise<{ default: unknown }>

/** 企业桌面：注册全部宿主页（与 full 一致，含日更全链路等运维视图） */
const all = import.meta.glob([
  '../views/**/*.vue',
  '!../views/**/*Fixed.vue',
  '!../views/**/*Optimized.vue',
  '!../views/temp*.vue',
]) as Record<string, ViewLoader>

export const hostViewGlob = Object.fromEntries(
  Object.entries(all).filter(([path]) => {
    const norm = path.replace(/\\/g, '/')
    if (/\/views\/temp\d+\.vue$/.test(norm)) return false
    if (/\/views\/[^/]+(?:Fixed|Optimized)\.vue$/.test(norm)) return false
    return true
  }),
) as Record<string, ViewLoader>
