import path from 'node:path'
import { randomBytes } from 'node:crypto'

/** Main-process memory only; backend restarts share it, a new app process does not. */
export const desktopWorkspaceToken = randomBytes(32).toString('hex')

/** 桌面后端只允许使用 userData SQLite，不能继承 IDE/代理的 DATABASE_URL。 */
export function desktopBackendEnv(
  env: NodeJS.ProcessEnv,
  developmentSourceRoot?: string,
  packagedResourcesRoot?: string
): NodeJS.ProcessEnv {
  const isolated = { ...env };
  delete isolated.DATABASE_URL;
  isolated.XCAGI_DESKTOP_WORKSPACE_TOKEN = desktopWorkspaceToken
  isolated.XCAGI_EMPLOYEE_SCHEDULER ||= '0';
  if (packagedResourcesRoot) {
    isolated.XCAGI_DESKTOP_RESOURCES = packagedResourcesRoot
  }
  if (developmentSourceRoot) {
    const modsRoot = path.join(developmentSourceRoot, 'mods')
    isolated.XCAGI_MODS_ROOT = modsRoot
    isolated.XCAGI_MODS_DIR = modsRoot
  }
  return isolated;
}
