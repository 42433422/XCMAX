/**
 * 与 MODstore `market/src/domain/yuangonDutyRoster.ts` 及 `modstore_server/duty_roster.py`
 * 编制矩阵一致。变更时请与上述两处手迁同步。
 */
const PLANNED_PKG_IDS: readonly string[] = [
  'site-content-editor',
  'seo-sitemap-curator',
  'flask-entry-keeper',
  'nginx-config-engineer',
  'push-update-context-officer',
  'deploy-release-officer',
  'security-secrets-guard',
  'log-monitor-incident',
  'retention-officer',
  'dbops-engineer',
  'modstore-backend-api',
  'employee-pack-curator',
  'payment-billing-reconciler',
  'market-frontend-dev',
  'workbench-ux-stylist',
  'vibe-coding-maintainer',
  'mods-and-eskill-curator',
  'change-request-auditor',
  'daily-orchestrator',
  'intake-dispatcher',
  'task-router-officer',
  'test-qa-runner',
  'doc-knowledge-curator',
  'employee-interview-assistant',
  'employee-pack-quality-interviewer',
]

export const ALL_PLANNED_YUANGON_PKG_IDS: ReadonlySet<string> = new Set(PLANNED_PKG_IDS)

export function normEmployeePkgId(id: string): string {
  return String(id || '').trim()
}

/** 管理端「编制内在岗」：已入库 catalog 的编制矩阵包（与工作台 LeftRail 展示集合一致，本页排除） */
export function isMgmtOnDutyRow(row: { id?: string; source?: string }): boolean {
  const pid = normEmployeePkgId(String(row?.id ?? ''))
  if (!pid) return false
  return ALL_PLANNED_YUANGON_PKG_IDS.has(pid) && row?.source === 'catalog'
}

/** 服务端禁止删除的编制包 id（与 MODstore admin delete 403 一致） */
export function isPlannedDutyRosterPkgId(pkgId: string): boolean {
  return ALL_PLANNED_YUANGON_PKG_IDS.has(normEmployeePkgId(pkgId))
}
