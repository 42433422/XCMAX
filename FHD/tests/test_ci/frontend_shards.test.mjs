import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { after, test } from 'node:test'
import { copyFileSync, cpSync, existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { coverageEvidence, executionEvidence, identity, sha256, verifyArtifacts } from '../../scripts/ci/frontend_shard_evidence.mjs'
import { mergeShards, runShard } from '../../scripts/ci/frontend_shards.mjs'

const root = mkdtempSync(path.join(os.tmpdir(), 'xcmax-frontend-shards-'))
after(() => rmSync(root, { recursive: true, force: true }))
const frontend = fileURLToPath(new URL('../../frontend/', import.meta.url))
const expected = { GITHUB_SHA: 'a'.repeat(40), FRONTEND_SOURCE_SHA: 'a'.repeat(40), GITHUB_RUN_ID: '42', GITHUB_RUN_ATTEMPT: '2' }
const put = (filename, data) => writeFileSync(filename, JSON.stringify(data, null, 2) + '\n')
const get = filename => JSON.parse(readFileSync(filename, 'utf8'))

test('identity requires a complete source SHA and exact run attempt', () => {
  assert.deepEqual(identity(expected), expected)
  for (const key of Object.keys(expected)) assert.throws(() => identity({ ...expected, [key]: '' }))
})

test('execution rejects unfinished, failed and unhandled-error results', () => {
  const task = { type: 'suite', name: 'file', filepath: '/frontend/test.js', mode: 'run', result: { state: 'pass' }, tasks: [
    { type: 'test', id: 'case', name: 'works', mode: 'run', result: { state: 'pass' } },
  ] }
  assert.equal(executionEvidence([{ task }], [], '/frontend').tests.length, 1)
  for (const state of ['run', 'fail', undefined]) {
    const bad = structuredClone(task)
    bad.tasks[0].result.state = state
    assert.throws(() => executionEvidence([{ task: bad }], [], '/frontend'))
  }
  assert.throws(() => executionEvidence([{ task }], [new Error('unhandled')], '/frontend'))
  task.tasks[0].mode = 'skip'
  delete task.tasks[0].result
  assert.equal(executionEvidence([{ task }], [], '/frontend').tests[0].state, 'skip')
})

function fakeShards(directory) {
  mkdirSync(directory)
  const full = ['tests/a.test.js', 'tests/b.test.js']
  for (let index = 1; index <= 2; index++) {
    const shard = path.join(directory, `shard-${index}`)
    mkdirSync(path.join(shard, 'coverage'), { recursive: true })
    const coverage = { '/frontend/src/a.js': {
      path: '/frontend/src/a.js', statementMap: { 0: { start: { line: 1, column: 0 }, end: { line: 1, column: 1 } } },
      fnMap: {}, branchMap: {}, s: { 0: 1 }, f: {}, b: {},
    } }
    const fingerprint = coverageEvidence(coverage, '/frontend')
    const report = { success: true, files: [full[index - 1]], tests: [{ file: full[index - 1], id: `case-${index}`, state: 'pass' }], coverage: fingerprint }
    put(path.join(shard, 'report.json'), report)
    put(path.join(shard, 'coverage/coverage-final.json'), coverage)
    put(path.join(shard, 'blob.json'), ['placeholder'])
    put(path.join(shard, 'manifest.json'), {
      schema: 1, ...expected, root: '/frontend', index, total: 2, full, selected: [full[index - 1]],
      exit_code: 0, config_sha256: 'config', vitest_version: '5.0.5', coverage: fingerprint,
      outputs: Object.fromEntries(['report.json', 'blob.json', 'coverage/coverage-final.json'].map(file => [file, sha256(readFileSync(path.join(shard, file)))])),
    })
  }
  return () => verifyArtifacts(directory, 2, expected, full, '5.0.5', 'config')
}

test('artifact verification rejects missing, duplicate, stale and altered evidence', () => {
  const original = path.join(root, 'valid')
  assert.equal(fakeShards(original)().length, 2)
  const cases = {
    missing: dir => rmSync(path.join(dir, 'shard-2'), { recursive: true }),
    changed: dir => writeFileSync(path.join(dir, 'shard-1/blob.json'), 'changed'),
    cancelled: dir => mutate(dir, manifest => { manifest.exit_code = null }),
    stale: dir => mutate(dir, manifest => { manifest.GITHUB_RUN_ATTEMPT = '1' }),
    foreign: dir => mutate(dir, manifest => { manifest.FRONTEND_SOURCE_SHA = 'b'.repeat(40) }),
    duplicate: dir => mutate(dir, manifest => { manifest.index = 2 }),
    missingFile: dir => mutate(dir, manifest => { manifest.selected = [] }),
    staleConfig: dir => mutate(dir, manifest => { manifest.config_sha256 = 'old' }),
    symlink: dir => {
      const filename = path.join(dir, 'shard-1/blob.json')
      rmSync(filename)
      symlinkSync(path.join(original, 'shard-1/blob.json'), filename)
    },
    symlinkDirectory: dir => {
      const directory = path.join(dir, 'shard-1/coverage')
      rmSync(directory, { recursive: true })
      symlinkSync(path.join(original, 'shard-1/coverage'), directory, 'dir')
    },
  }
  function mutate(dir, change) {
    const filename = path.join(dir, 'shard-1/manifest.json')
    const manifest = get(filename)
    change(manifest)
    put(filename, manifest)
  }
  for (const [name, change] of Object.entries(cases)) {
    const directory = path.join(root, name)
    cpSync(original, directory, { recursive: true })
    change(directory)
    assert.throws(() => verifyArtifacts(directory, 2, expected, ['tests/a.test.js', 'tests/b.test.js'], '5.0.5', 'config'), name)
  }
})

test('real Vitest V8 four-shard merge equals full run and rejects coverage-free blobs', { timeout: 120000 }, () => {
  const fixture = path.join(root, 'real')
  mkdirSync(path.join(fixture, 'src'), { recursive: true })
  mkdirSync(path.join(fixture, 'tests'))
  symlinkSync(path.join(frontend, 'node_modules'), path.join(fixture, 'node_modules'), 'dir')
  put(path.join(fixture, 'package.json'), { type: 'module' })
  copyFileSync(path.join(frontend, 'package-lock.json'), path.join(fixture, 'package-lock.json'))
  copyFileSync(path.join(frontend, 'vitest.polyfill.cjs'), path.join(fixture, 'vitest.polyfill.cjs'))
  writeFileSync(path.join(fixture, 'src/math.js'), `export function calculate(flag) {\n let value = 0\n${Array.from({ length: 30 }, () => ' value += 1').join('\n')}\n return flag ? value : -value\n}\n`)
  writeFileSync(path.join(fixture, 'src/unimported.js'), 'export const uncovered = 1\n')
  const executions = path.join(fixture, 'executions.log')
  for (let n = 1; n <= 4; n++) {
    writeFileSync(path.join(fixture, `tests/${n}.test.js`), `import { test, expect } from 'vitest'\nimport { appendFileSync } from 'node:fs'\nimport { calculate } from '../src/math.js'\ntest('executes ${n}', () => { appendFileSync(${JSON.stringify(executions)}, '${n}\\n'); expect(calculate(${n % 2 === 0})).toBe(${n % 2 === 0 ? 30 : -30}) })\ntest.skip('declared skip ${n}', () => {})\n`)
  }
  writeFileSync(path.join(fixture, 'vitest.config.js'), `export default { test: { include: ['tests/*.test.js'], maxWorkers: 1, coverage: { provider: 'v8', include: ['src/**/*.js'], reporter: ['json', 'json-summary'], thresholds: { lines: 92, branches: 81, functions: 90, statements: 92 } } } }\n`)
  const version = get(path.join(frontend, 'node_modules/vitest/package.json')).version
  const env = { ...process.env, ...expected, FRONTEND_SHARD_TOTAL: '4', CI: 'true' }
  const ctx = { root: fixture, expected, version, total: 4, configSha: 'fixture', env }
  const shards = path.join(fixture, 'shards')
  mkdirSync(shards)
  for (let index = 1; index <= 4; index++) runShard({ ...ctx, env: { ...env, FRONTEND_SHARD_INDEX: String(index) } }, path.join(shards, `shard-${index}`))
  const executedOnce = readFileSync(executions, 'utf8')
  assert.equal(executedOnce.trim().split('\n').length, 4)
  for (let index = 1; index <= 4; index++) {
    const shard = path.join(shards, `shard-${index}`)
    const junit = readFileSync(path.join(shard, 'junit.xml'), 'utf8')
    assert.equal((junit.match(/<testcase\b/g) || []).length, 2)
    assert.equal((junit.match(/<skipped\b/g) || []).length, 1)
    assert.equal(get(path.join(shard, 'manifest.json')).outputs['junit.xml'], sha256(junit))
  }
  mergeShards(ctx, shards)
  assert.equal(readFileSync(executions, 'utf8'), executedOnce, 'Merging JUnit must not execute tests again')
  const junit = readFileSync(path.join(fixture, 'test-results/junit.xml'), 'utf8')
  assert.equal((junit.match(/<testcase\b/g) || []).length, 8)
  assert.equal((junit.match(/<skipped\b/g) || []).length, 4)
  for (let n = 1; n <= 4; n++) {
    assert.match(junit, new RegExp(`name="executes ${n}"`))
    assert.match(junit, new RegExp(`<testcase[^>]*name="declared skip ${n}"[^>]*>\\s*<skipped`))
  }
  const merged = get(path.join(fixture, 'coverage/coverage-summary.json'))
  assert(Object.keys(merged).some(file => file.endsWith('/src/unimported.js')), 'Unimported source must stay in the denominator')
  const monolithic = spawnSync(process.execPath, [path.join(frontend, 'node_modules/vitest/vitest.mjs'), 'run', '--coverage'], { cwd: fixture, env, encoding: 'utf8' })
  assert.equal(monolithic.status, 0, monolithic.stderr + monolithic.stdout)
  assert.deepEqual(get(path.join(fixture, 'coverage/coverage-summary.json')), merged)
  const executedTwice = readFileSync(executions, 'utf8')
  assert.equal(executedTwice.trim().split('\n').length, 8)
  // Prove the aggregate still obeys the source config's global floors. Raising
  // only this fixture's line floor must fail; no shard is re-executed.
  const configFile = path.join(fixture, 'vitest.config.js')
  const originalConfig = readFileSync(configFile, 'utf8')
  writeFileSync(configFile, originalConfig.replace('lines: 92', 'lines: 100'))
  assert.throws(() => mergeShards(ctx, shards, '.threshold-merge'), /Native Vitest/)
  writeFileSync(configFile, originalConfig)
  const damaged = path.join(fixture, 'damaged')
  cpSync(shards, damaged, { recursive: true })
  const blob = path.join(damaged, 'shard-1/blob.json')
  const native = get(blob)
  assert(Array.isArray(native[0]), 'Unexpected Vitest 5 blob format')
  native[0][3] = null // a raw coverage payload removed, with a new outer checksum
  put(blob, native)
  const manifestFile = path.join(damaged, 'shard-1/manifest.json')
  const manifest = get(manifestFile)
  manifest.outputs['blob.json'] = sha256(readFileSync(blob))
  put(manifestFile, manifest)
  assert.throws(() => mergeShards(ctx, damaged, '.bad-merge'), /Native Vitest/)
  writeFileSync(path.join(damaged, 'shard-1/junit.xml'), 'altered report')
  assert.throws(() => mergeShards(ctx, damaged, '.bad-junit-merge'), /Changed\/missing junit.xml/)
  assert.equal(readFileSync(executions, 'utf8'), executedTwice, 'Failed report merges must not rerun tests')

  // Failed shards still provide diagnostic JUnit without a success manifest.
  writeFileSync(path.join(fixture, 'tests/failure.test.js'), "import { test, expect } from 'vitest'\ntest('intentional failure', () => expect(1).toBe(2))\n")
  writeFileSync(configFile, originalConfig.replace("'tests/*.test.js'", "'tests/failure.test.js'"))
  const failed = path.join(fixture, 'failed-shard')
  assert.throws(() => runShard({ ...ctx, total: 1, env: { ...env, FRONTEND_SHARD_TOTAL: '1', FRONTEND_SHARD_INDEX: '1' } }, failed), /Vitest shard failed/)
  assert.match(readFileSync(path.join(failed, 'junit.xml'), 'utf8'), /<failure\b/)
  assert.equal(existsSync(path.join(failed, 'manifest.json')), false)
})
