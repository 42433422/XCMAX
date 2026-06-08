/**
 * 当本页作为 XCAGI 壳（FHD）内 iframe 嵌入时，在成功将 Mod 部署到宿主 `mods/` 后
 * 通知父窗口刷新 Mod 列表与动态路由（无需整页刷新）。
 */
export function notifyParentModsDeployed(deployed: string[] | null | undefined): void {
  if (typeof window === 'undefined') return
  try {
    if (!window.parent || window.parent === window) return
    window.parent.postMessage(
      {
        source: 'xcagi-modstore',
        type: 'xcagi-mods-deployed',
        deployed: Array.isArray(deployed) ? deployed : [],
      },
      '*',
    )
  } catch {
    /* ignore */
  }
}
