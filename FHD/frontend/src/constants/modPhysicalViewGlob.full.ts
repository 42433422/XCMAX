type ViewLoader = () => Promise<{ default: unknown }>

export const modPhysicalViewGlob = {
  ...import.meta.glob('../../../mods/*/frontend/views/**/*.vue'),
  ...import.meta.glob('../../../mods-admin-runtime/*/frontend/views/**/*.vue'),
} as Record<string, ViewLoader>
