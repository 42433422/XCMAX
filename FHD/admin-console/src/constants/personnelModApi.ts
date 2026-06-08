/** 管理端：人员/客户 API 默认挂在 xcmax-personnel（与企业 dev .env 一致） */
export function getPersonnelModApiBase(): string {
  const raw = String(import.meta.env.VITE_PERSONNEL_MOD_ID ?? '').trim()
  const id = raw || 'xcmax-personnel'
  return `/api/mod/${id}`
}
