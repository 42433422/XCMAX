/** 太阳鸟企业壳：人员/客户 API 默认挂在 taiyangniao-pro */
export function getPersonnelModApiBase(): string {
  const raw = String(import.meta.env.VITE_PERSONNEL_MOD_ID ?? '').trim()
  const id = raw || 'taiyangniao-pro'
  return `/api/mod/${id}`
}
