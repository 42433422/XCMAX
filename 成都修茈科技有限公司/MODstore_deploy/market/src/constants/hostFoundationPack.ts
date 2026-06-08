/** 宿主基础能力：单个预装员工包（非逐项 bridge Mod 上架）。 */

export const HOST_FOUNDATION_EMPLOYEE_PACK_ID = 'xcagi-host-foundation-employee'

export const HOST_FOUNDATION_COLLECTION = 'host_foundation'

export function isHostFoundationEmployeePack(pkgId?: string | null): boolean {
  return (pkgId || '').trim() === HOST_FOUNDATION_EMPLOYEE_PACK_ID
}
