import path from 'node:path'
import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto'

/** Main-process memory only; backend restarts share it, a new app process does not. */
export const desktopWorkspaceToken = randomBytes(32).toString('hex')

/** A public nonce proves the listener owns the child-only secret without sending it. */
export function desktopBackendChallenge(): { nonce: string; verify: (proof: string) => boolean } {
  const nonce = randomBytes(32).toString('hex')
  const expected = createHmac('sha256', Buffer.from(desktopWorkspaceToken, 'ascii'))
    .update(`xcagi-desktop-backend-v1:${nonce}`, 'ascii').digest()
  return { nonce, verify: proof => proof.length === 64 && /^[0-9a-f]{64}$/.test(proof)
    && timingSafeEqual(expected, Buffer.from(proof, 'hex')) }
}

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
