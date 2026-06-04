/**
 * 「人员管理」（ProductsView）、客户/购买单位、SSH「同步服务器员工」等调用的 Mod API 根。
 * 实现位于 ``app.mod_sdk.personnel_http``，默认挂在 taiyangniao-pro；独立扩展包 ``xcmax-personnel`` 亦提供同一路由，可设 ``VITE_PERSONNEL_MOD_ID=xcmax-personnel``。
 */
export function getPersonnelModApiBase(): string {
  const raw = String(import.meta.env.VITE_PERSONNEL_MOD_ID ?? '').trim()
  const id = raw || 'taiyangniao-pro'
  return `/api/mod/${id}`
}
