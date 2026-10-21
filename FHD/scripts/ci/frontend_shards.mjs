#!/usr/bin/env node
/** Four-machine Vitest execution with native blob/coverage merging and strict evidence. */
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { copyFileSync, existsSync, mkdirSync, readdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import {
  coverageEvidence, identity, readRegular, relativeFile, sha256, stableJson,
  uniqueFiles, verifyArtifacts,
} from './frontend_shard_evidence.mjs'

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url))
const reporter = path.join(SCRIPT_DIR, 'frontend_shard_reporter.mjs')
const writeJson = (filename, value) => writeFileSync(filename, JSON.stringify(value, null, 2) + '\n')

export function context(root, env = process.env) {
  root = path.resolve(root)
  const expected = identity(env)
  const git = spawnSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' })
  assert.equal(git.status, 0, 'Cannot read the tested checkout identity')
  assert.equal(git.stdout.trim(), expected.FRONTEND_SOURCE_SHA, 'Checkout differs from FRONTEND_SOURCE_SHA')
  const version = JSON.parse(readRegular(path.join(root, 'node_modules/vitest/package.json'))).version
  assert.match(version, /^5\./, 'Frontend evidence adapter requires Vitest 5')
  const total = Number(env.FRONTEND_SHARD_TOTAL)
  assert(Number.isInteger(total) && total > 0, 'FRONTEND_SHARD_TOTAL is required')
  const configFiles = ['vitest.config.js', 'package-lock.json', 'vitest.polyfill.cjs']
  const configSha = sha256(stableJson(configFiles.map(file => [file, sha256(readRegular(path.join(root, file)))])))
  return { root, expected, version, total, configSha, env }
}

function invoke(ctx, args, env = {}) {
  return spawnSync(process.execPath, [
    '--require', path.join(ctx.root, 'vitest.polyfill.cjs'),
    path.join(ctx.root, 'node_modules/vitest/vitest.mjs'), ...args,
  ], { cwd: ctx.root, stdio: 'inherit', env: { ...ctx.env, ...env } })
}

function requireSuccess(result, name) {
  assert.equal(result.error, undefined, `${name} could not start: ${result.error?.message}`)
  assert.equal(result.signal, null, `${name} was terminated: ${result.signal}`)
  assert.equal(result.status, 0, `${name} failed with exit status ${result.status}`)
}

function emptyDirectory(directory) {
  assert(!existsSync(directory) || readdirSync(directory).length === 0, `Refusing stale evidence: ${directory}`)
  mkdirSync(directory, { recursive: true })
}

export function collectFiles(ctx, directory) {
  const output = path.join(directory, 'collection.json')
  const args = ['list', '--config', path.join(ctx.root, 'vitest.config.js'), '--filesOnly', `--json=${output}`]
  requireSuccess(invoke(ctx, args), 'Vitest file collection')
  const data = JSON.parse(readRegular(output))
  const files = data.map(item => relativeFile(typeof item === 'string' ? item : item.file, ctx.root))
  return uniqueFiles(files)
}

function configuration(ctx, directory, phase) {
  const file = path.join(directory, 'vitest-ci.config.mjs')
  // Keep the source test/coverage include and exclude lists, isolation and pool.
  // A partial shard cannot satisfy global coverage floors. Only native merging
  // uses the unmodified source thresholds, followed by the existing ratchet.
  const collect = phase === 'collect'
  writeFileSync(file, `import base from ${JSON.stringify(pathToFileURL(path.join(ctx.root, 'vitest.config.js')).href)}\n` +
    `export default { ...base, root: ${JSON.stringify(ctx.root)}, test: { ...base.test,\n` +
    `  reporters: ['default', ${collect ? "'blob', " : ''}${JSON.stringify(reporter)}],\n` +
    `  outputFile: { blob: ${JSON.stringify(path.join(directory, 'blob.json'))} },\n` +
    `  coverage: { ...base.test.coverage, enabled: true, reportOnFailure: true,\n` +
    (collect ? `    thresholds: {}, reporter: ['json'], reportsDirectory: ${JSON.stringify(path.join(directory, 'coverage'))},\n` : '') +
    `  } } }\n`)
  return file
}

export function runShard(ctx, directory) {
  const index = Number(ctx.env.FRONTEND_SHARD_INDEX)
  assert(Number.isInteger(index) && index >= 1 && index <= ctx.total, 'Invalid FRONTEND_SHARD_INDEX')
  directory = path.resolve(ctx.root, directory)
  emptyDirectory(directory)
  const full = collectFiles(ctx, directory)
  const result = invoke(ctx, [
    'run', '--config', configuration(ctx, directory, 'collect'), `--shard=${index}/${ctx.total}`,
  ], { FRONTEND_SHARD_PHASE: 'collect', FRONTEND_SHARD_REPORT: path.join(directory, 'report.json') })
  // Failed or interrupted shards retain diagnostics but never receive a valid
  // success manifest. GitHub uploads the directory with if: always().
  requireSuccess(result, 'Vitest shard')
  const report = JSON.parse(readRegular(path.join(directory, 'report.json')))
  assert.equal(report.success, true, report.error || 'Incomplete Vitest execution report')
  assert.deepEqual(report.collection, full, 'Shard configuration changed the complete test collection')
  const selected = uniqueFiles(report.files)
  assert(selected.every(file => full.includes(file)), 'Foreign selected test file')
  const coverage = coverageEvidence(JSON.parse(readRegular(path.join(directory, 'coverage/coverage-final.json'))), ctx.root)
  assert.deepEqual(coverage, report.coverage, 'Raw coverage differs from the blob reporter input')
  const outputs = Object.fromEntries(['blob.json', 'report.json', 'coverage/coverage-final.json'].map(file => [file, sha256(readRegular(path.join(directory, file)))]))
  writeJson(path.join(directory, 'manifest.json'), {
    schema: 1, ...ctx.expected, index, total: ctx.total, root: ctx.root,
    vitest_version: ctx.version, config_sha256: ctx.configSha, exit_code: 0,
    full, selected, coverage, outputs,
  })
}

export function mergeShards(ctx, directory, output = '.frontend-merge') {
  directory = path.resolve(ctx.root, directory)
  output = path.resolve(ctx.root, output)
  emptyDirectory(output)
  const full = collectFiles(ctx, output)
  const manifests = verifyArtifacts(directory, ctx.total, ctx.expected, full, ctx.version, ctx.configSha)
  const blobs = path.join(output, 'blobs')
  mkdirSync(blobs)
  for (const manifest of manifests) {
    copyFileSync(path.join(manifest.directory, 'blob.json'), path.join(blobs, `shard-${manifest.index}.json`))
  }
  const plan = path.join(output, 'merge-plan.json')
  writeJson(plan, { coverages: manifests.map(item => item.coverage) })
  requireSuccess(invoke(ctx, [
    'run', '--config', configuration(ctx, output, 'merge'), `--merge-reports=${blobs}`,
  ], {
    FRONTEND_SHARD_PHASE: 'merge', FRONTEND_SHARD_REPORT: path.join(output, 'report.json'),
    FRONTEND_SHARD_MERGE_PLAN: plan,
  }), 'Native Vitest blob/coverage merge')
  const report = JSON.parse(readRegular(path.join(output, 'report.json')))
  assert.equal(report.success, true, report.error || 'Incomplete merged execution report')
  assert.deepEqual(uniqueFiles(report.files), full, 'Merged report differs from full test collection')
  const expectedTests = manifests.flatMap(manifest => JSON.parse(readRegular(path.join(manifest.directory, 'report.json'))).tests).sort((a, b) => a.id.localeCompare(b.id))
  assert.deepEqual(report.tests, expectedTests, 'Native blob results differ from sealed execution evidence')
  const coverage = coverageEvidence(JSON.parse(readRegular(path.join(ctx.root, 'coverage/coverage-final.json'))), ctx.root)
  const expectedCoverageFiles = [...new Set(manifests.flatMap(item => item.coverage.files))].sort()
  assert.deepEqual(coverage.files, expectedCoverageFiles, 'Merged coverage changed the source-file universe')
  const summary = JSON.parse(readRegular(path.join(ctx.root, 'coverage/coverage-summary.json')))
  for (const metric of ['lines', 'branches', 'functions', 'statements']) {
    assert(Number.isFinite(summary.total?.[metric]?.pct), `Missing merged coverage ${metric}`)
    assert(summary.total[metric].total > 0, `Empty merged coverage ${metric}`)
  }
  writeJson(path.join(output, 'summary.json'), {
    schema: 1, ...ctx.expected, files: full.length, tests: report.tests.length,
    shards: ctx.total, vitest_version: ctx.version,
    collection_sha256: sha256(stableJson(full)), coverage,
    coverage_summary: summary.total,
  })
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const [command, directory] = process.argv.slice(2)
    assert(directory, 'Usage: frontend_shards.mjs run|merge <evidence-directory>')
    const ctx = context(process.cwd())
    if (command === 'run') runShard(ctx, directory)
    else if (command === 'merge') mergeShards(ctx, directory)
    else throw new Error(`Unknown command: ${command}`)
  } catch (error) {
    console.error(`[frontend-shards] ${error.stack || error}`)
    process.exitCode = 1
  }
}
