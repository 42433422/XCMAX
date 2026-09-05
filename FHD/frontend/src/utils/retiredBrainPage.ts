/** 旧开发页面已退出产品导航；兼容历史菜单 id 与自定义标题的旧路径。 */
export function isRetiredBrainPage(menuKey: unknown, menuPath: unknown): boolean {
  const key = String(menuKey || '')
    .trim()
    .replace(/^mod-mod-/, 'mod-')
  const path = String(menuPath || '')
    .trim()
    .split('?')[0]
    .split('#')[0]
    .replace(/\/$/, '')
  return key === 'brain' || key === 'mod-planner-brain' || path === '/brain' || path === '/mod/xcagi-planner-bridge/brain'
}
