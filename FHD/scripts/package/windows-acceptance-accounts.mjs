import fs from 'node:fs'
import crypto from 'node:crypto'
import { pathToFileURL } from 'node:url'

export const MODES = ['Clean', 'Upgrade', 'Gui', 'Recovery', 'Rollback']
export function selectAccounts(env = process.env) {
  const accountMode = env.ACCOUNT_MODE || 'shared-serial'
  if (!['shared-serial', 'isolated-parallel'].includes(accountMode)) throw new Error('Unknown acceptance account mode')
  const selections = { '': MODES, Lifecycle: ['Clean', 'Upgrade', 'Rollback'], Rollback: ['Rollback'] }
  if (!Object.hasOwn(selections, env.ONLY || '')) throw new Error('Unknown acceptance mode selection')
  const isolated = accountMode === 'isolated-parallel', users = new Set(), marketIds = new Set()
  const matrix = MODES.map(mode => {
    const prefix = isolated ? `XCAGI_TEST_${mode.toUpperCase()}` : 'XCAGI_TEST'
    const user_secret = `${prefix}_USER`, pass_secret = `${prefix}_PASS`
    const market_variable = isolated ? `${prefix}_MARKET_USER_ID` : ''
    if (!env[user_secret]?.trim() || !env[pass_secret]?.trim()) throw new Error(`Missing acceptance credentials: ${mode}`)
    if (isolated) {
      const user = env[user_secret].trim().toLowerCase(), marketId = env[market_variable] || ''
      if (!/^[1-9]\d*$/.test(marketId)) throw new Error(`Missing or invalid market identity: ${mode}`)
      if (users.has(user) || marketIds.has(marketId)) throw new Error('Parallel acceptance requires five distinct business identities')
      users.add(user); marketIds.add(marketId)
    }
    return { mode, user_secret, pass_secret, market_user_id: isolated ? env[market_variable] : '' }
  }).filter(({ mode }) => selections[env.ONLY || ''].includes(mode))
  return { matrix, parallel: isolated ? 5 : 1 }
}

export function assertIdentity(identity, env = process.env) {
  if ((env.XCAGI_ACCEPTANCE_ACCOUNT_MODE || 'shared-serial') === 'shared-serial') return
  const expected = env.XCAGI_TEST_MARKET_USER_ID || ''
  if (env.XCAGI_ACCEPTANCE_ACCOUNT_MODE !== 'isolated-parallel' || !/^[1-9]\d*$/.test(expected)
    || identity?.account_kind !== 'enterprise' || identity.market_is_enterprise !== true
    || identity.market_is_admin !== false || identity.impersonating_market_user_id != null
    || String(identity.market_user_id) !== expected) throw new Error('Acceptance business identity mismatch')
  return crypto.createHash('sha256').update(expected).digest('hex')
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const plan = selectAccounts()
    fs.appendFileSync(process.env.GITHUB_OUTPUT, `matrix=${JSON.stringify(plan.matrix)}\nparallel=${plan.parallel}\n`)
  } catch (error) { console.error(error.message); process.exitCode = 1 }
}
