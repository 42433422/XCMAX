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
    // A shared development venv may have editable installs from another worktree.
    // Bind source imports to the same checkout as run.py; the Python vendored
    // provenance assertion remains the fail-closed authority.
    const packages = path.join(developmentSourceRoot, 'packages')
    const sourcePaths = [
      developmentSourceRoot,
      ...[
        'xcagi_langgraph_core',
        'xcagi_langgraph_prebuilt',
        'xcagi_langgraph_checkpoint',
        'xcagi_langgraph_checkpoint_backends/checkpoint-sqlite',
        'xcagi_langgraph_checkpoint_backends/checkpoint-postgres',
        'xcagi_langgraph_sdk',
      ].map(packageName => path.join(packages, packageName)),
    ]
    isolated.PYTHONPATH = [...sourcePaths, ...(isolated.PYTHONPATH?.split(path.delimiter) || [])]
      .filter(Boolean).filter((value, index, values) => values.indexOf(value) === index)
      .join(path.delimiter)
  }
  return isolated;
}
