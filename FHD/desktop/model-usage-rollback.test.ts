import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const mocks = vi.hoisted(() => ({ execFile: vi.fn() }))
vi.mock('node:child_process', () => ({ execFile: mocks.execFile }))
import { assertLedgerOutsideRollbackTarget, handoffModelUsageLedger, modelUsageLedgerPath } from './model-usage-rollback'

let directory: string
beforeEach(() => {
  directory = fs.mkdtempSync(path.join(os.tmpdir(), 'xcmax-ledger-handoff-'))
  fs.mkdirSync(path.join(directory, 'data'))
  mocks.execFile.mockReset()
})
afterEach(() => fs.rmSync(directory, { recursive: true, force: true }))

describe('rollback ledger handoff', () => {
  it('keeps old JSON-only installations unchanged', async () => {
    await handoffModelUsageLedger({ command: 'backend', args: [], cwd: directory }, directory, {})
    expect(mocks.execFile).not.toHaveBeenCalled()
  })

  it('uses the actual backend location and resolves custom relative paths against its cwd', () => {
    const ledger = path.join(directory, 'custom ledger.json')
    fs.writeFileSync(path.join(directory, 'data', 'model_usage_storage.json'), JSON.stringify({ version: 1, ledger_path: ledger }))
    expect(modelUsageLedgerPath(directory, {})).toBe(ledger)
    expect(modelUsageLedgerPath(directory, { MODEL_USAGE_LEDGER_PATH: 'another.json' }, directory)).toBe(path.join(directory, 'another.json'))
  })

  it('does not substitute an empty default ledger for corrupt location metadata', () => {
    fs.writeFileSync(path.join(directory, 'data', 'model_usage_storage.json'), '{"version":2}')
    expect(() => modelUsageLedgerPath(directory, {})).toThrow()
  })

  it('refuses to retire a ledger that the application restore would overwrite', () => {
    const install = path.join(directory, 'backend')
    fs.mkdirSync(install)
    expect(() => assertLedgerOutsideRollbackTarget(path.join(install, 'ledger.json'), install)).toThrow(/安装目录/)
    expect(() => assertLedgerOutsideRollbackTarget(path.join(directory, 'data', 'ledger.json'), install)).not.toThrow()
  })

  it('does not treat a missing migrated database as an old empty installation', async () => {
    const ledger = modelUsageLedgerPath(directory, {})
    fs.writeFileSync(path.join(directory, 'data', 'model_usage_storage.json'), JSON.stringify({ version: 1, ledger_path: ledger }))
    await expect(handoffModelUsageLedger({ command: 'backend', args: [], cwd: directory }, directory, {})).rejects.toThrow(/数据库丢失/)
    fs.writeFileSync(ledger, '{"entries":[],"wallets":{}}')
    await expect(handoffModelUsageLedger({ command: 'backend', args: [], cwd: directory }, directory, {})).rejects.toThrow(/交接快照/)
    expect(mocks.execFile).not.toHaveBeenCalled()
  })

  it('allows a repeated handoff only with its retired database and compatible JSON', async () => {
    const ledger = modelUsageLedgerPath(directory, {})
    fs.writeFileSync(path.join(directory, 'data', 'model_usage_storage.json'), JSON.stringify({ version: 1, ledger_path: ledger }))
    fs.writeFileSync(ledger, JSON.stringify({ entries: [], wallets: {}, compatibility_snapshot: { source: `${ledger}.sqlite3` } }))
    fs.writeFileSync(`${ledger}.rollback-test.sqlite3`, 'archived')
    await handoffModelUsageLedger({ command: 'backend', args: [], cwd: directory }, directory, {})
    expect(mocks.execFile).not.toHaveBeenCalled()
  })

  it('requires a successful receipt and retirement before allowing the old binary', async () => {
    const ledger = modelUsageLedgerPath(directory, {})
    fs.writeFileSync(`${ledger}.sqlite3`, 'current-ledger')
    mocks.execFile.mockImplementationOnce((_command, args, options, callback) => {
      expect(args).toEqual(['--desktop', '--export-model-usage-ledger', ledger])
      expect(options).toMatchObject({ windowsHide: true, timeout: 60_000, cwd: directory })
      fs.writeFileSync(ledger, '{"wallets":{"customer":{"balance":42}},"entries":[]}')
      fs.renameSync(`${ledger}.sqlite3`, `${ledger}.rollback.sqlite3`)
      callback(null, `XCAGI_MODEL_USAGE_HANDOFF=${ledger}\n`)
    })
    await handoffModelUsageLedger({ command: 'backend', args: ['--desktop'], cwd: directory }, directory, {})
    expect(fs.readFileSync(ledger, 'utf8')).toContain('42')
  })

  it.each(['pending', 'no_receipt', 'not_retired'])('aborts an incomplete handoff: %s', async failure => {
    const ledger = modelUsageLedgerPath(directory, {})
    fs.writeFileSync(`${ledger}.sqlite3`, 'current-ledger')
    mocks.execFile.mockImplementationOnce((_command, _args, _options, callback) => {
      fs.writeFileSync(ledger, '{"wallets":{}}')
      callback(failure === 'pending' ? new Error('pending wallet settlement') : null,
        failure === 'no_receipt' ? '' : `XCAGI_MODEL_USAGE_HANDOFF=${ledger}\n`)
    })
    await expect(handoffModelUsageLedger({ command: 'backend', args: [], cwd: directory }, directory, {})).rejects.toThrow()
    expect(fs.readFileSync(`${ledger}.sqlite3`, 'utf8')).toBe('current-ledger')
  })
})
