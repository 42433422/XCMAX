type RouteModuleLoader = () => Promise<Record<string, unknown>>

/** 干净通用宿主：Mod 路由由回装后动态注册，构建期不 glob 空 mods 目录 */
export const modRouteGlob = {} as Record<string, RouteModuleLoader>
