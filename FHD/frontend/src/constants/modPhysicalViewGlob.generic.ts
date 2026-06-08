type ViewLoader = () => Promise<{ default: unknown }>

/** 干净通用宿主：仅保留登录与双核心页（智能对话 / 智能生态）+ 设置 */
export const modPhysicalViewGlob = {} as Record<string, ViewLoader>
