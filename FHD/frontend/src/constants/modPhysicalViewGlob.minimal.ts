type ViewLoader = () => Promise<{ default: unknown }>

export const modPhysicalViewGlob = {
  ...import.meta.glob('../../../mods/bridge/xcagi-planner-bridge/frontend/views/**/*.vue'),
  ...import.meta.glob('../../../mods/bridge/xcagi-neuro-bus-bridge/frontend/views/**/*.vue'),
  ...import.meta.glob('../../../mods/bridge/xcagi-office-employee-pack-bridge/frontend/views/**/*.vue'),
} as Record<string, ViewLoader>
