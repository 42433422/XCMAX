/** Fail-closed identity, collection and raw-coverage checks for Vitest shards. */
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { lstatSync, readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'

export const IDENTITY_KEYS = ['GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'FRONTEND_SOURCE_SHA']
export const sha256 = value => createHash('sha256').update(value).digest('hex')
export const stableJson = value => JSON.stringify(value, (_, item) => {
  if (!item || Array.isArray(item) || typeof item !== 'object') return item
  return Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]]))
})

export function identity(env = process.env) {
  const result = Object.fromEntries(IDENTITY_KEYS.map(key => [key, env[key]]))
  for (const key of ['GITHUB_SHA', 'FRONTEND_SOURCE_SHA']) {
    assert.match(result[key] || '', /^[0-9a-f]{40}$/, `Missing/invalid ${key}`)
  }
  for (const key of ['GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT']) {
    assert.match(result[key] || '', /^[1-9][0-9]*$/, `Missing/invalid ${key}`)
  }
  return result
}

export function relativeFile(filename, root) {
  assert.equal(typeof filename, 'string', 'Invalid test/coverage filename')
  const relative = path.relative(root, path.resolve(root, filename)).split(path.sep).join('/')
  assert(relative && !relative.startsWith('../') && relative !== '..', `File outside frontend root: ${filename}`)
  return relative
}

export function uniqueFiles(files, message = 'Invalid file collection') {
  assert(Array.isArray(files) && files.length > 0, message)
  assert(files.every(file => typeof file === 'string' && file.length > 0), message)
  assert.equal(new Set(files).size, files.length, `${message}: duplicate`)
  return [...files].sort()
}

export function coverageEvidence(coverage, root) {
  const raw = JSON.parse(JSON.stringify(coverage ?? null))
  assert(raw && typeof raw === 'object' && !Array.isArray(raw), 'Missing raw V8 coverage')
  const normalized = {}
  for (const [filename, value] of Object.entries(raw)) {
    const relative = relativeFile(filename, root)
    assert(!Object.hasOwn(normalized, relative), 'Duplicate coverage filename')
    assert(value && typeof value === 'object', 'Invalid coverage entry')
    for (const key of ['statementMap', 'fnMap', 'branchMap', 's', 'f', 'b']) {
      assert(value[key] && typeof value[key] === 'object', `Missing coverage ${key}`)
    }
    normalized[relative] = { ...value, path: relative }
  }
  const files = uniqueFiles(Object.keys(normalized), 'Empty raw V8 coverage')
  assert(files.some(file => Object.keys(normalized[file].s).length > 0), 'Coverage has no statements')
  return { files, sha256: sha256(stableJson(normalized)) }
}

export function executionEvidence(modules, errors, root) {
  assert.equal(errors.length, 0, 'Vitest reported unhandled errors')
  const files = [], tests = []
  function visit(task, filename, ancestors = [], inheritedSkip = false) {
    const skipped = inheritedSkip || task.mode === 'skip' || task.mode === 'todo'
    const state = task.result?.state
    assert(skipped || ['pass', 'skip', 'todo'].includes(state), `Unfinished/failed task: ${filename} ${task.name}`)
    assert(!task.result?.errors?.length, `Task errors: ${filename} ${task.name}`)
    if (task.type === 'test') {
      tests.push({ file: filename, id: task.id, name: [...ancestors, task.name].join(' > '), state: skipped ? task.mode === 'todo' ? 'todo' : 'skip' : state })
    } else {
      assert(Array.isArray(task.tasks), 'Missing collected tasks')
      for (const child of task.tasks) visit(child, filename, [...ancestors, task.name], skipped)
    }
  }
  for (const module of modules) {
    const task = module.task
    assert(task && task.type === 'suite', 'Invalid Vitest test module')
    const filename = relativeFile(task.filepath, root)
    files.push(filename)
    visit(task, filename)
  }
  assert(tests.length > 0, 'Shard executed no test cases')
  assert.equal(new Set(tests.map(test => test.id)).size, tests.length, 'Duplicate test case identity')
  return { files: uniqueFiles(files), tests: tests.sort((a, b) => a.id.localeCompare(b.id)) }
}

export function readRegular(filename) {
  const stat = lstatSync(filename)
  assert(stat.isFile() && !stat.isSymbolicLink(), `Not a regular evidence file: ${filename}`)
  return readFileSync(filename)
}

export function verifyArtifacts(directory, total, expectedIdentity, expectedFiles, expectedVersion, configSha) {
  assert(Number.isInteger(total) && total > 0, 'Invalid shard total')
  const directories = readdirSync(directory)
  assert.equal(directories.length, total, 'Missing or extra shard artifact')
  const indices = new Set(), selected = [], manifests = []
  for (const name of directories.sort()) {
    const shardDir = path.join(directory, name)
    const stat = lstatSync(shardDir)
    assert(stat.isDirectory() && !stat.isSymbolicLink(), 'Invalid shard artifact directory')
    const manifest = JSON.parse(readRegular(path.join(shardDir, 'manifest.json')))
    assert.equal(manifest.schema, 1, 'Unsupported shard evidence schema')
    for (const key of IDENTITY_KEYS) assert.equal(manifest[key], expectedIdentity[key], `Foreign ${key}`)
    assert.equal(manifest.vitest_version, expectedVersion, 'Foreign Vitest version')
    assert.equal(manifest.config_sha256, configSha, 'Foreign coverage/test configuration')
    assert.equal(manifest.total, total, 'Foreign shard total')
    assert(Number.isInteger(manifest.index) && manifest.index >= 1 && manifest.index <= total, 'Invalid shard index')
    assert(!indices.has(manifest.index), 'Duplicate shard index')
    indices.add(manifest.index)
    assert.equal(manifest.exit_code, 0, 'Shard process did not complete successfully')
    assert.deepEqual(uniqueFiles(manifest.full), expectedFiles, 'Foreign full test collection')
    const chosen = uniqueFiles(manifest.selected)
    assert(chosen.every(file => expectedFiles.includes(file)), 'Foreign selected test')
    const coverageDir = lstatSync(path.join(shardDir, 'coverage'))
    assert(coverageDir.isDirectory() && !coverageDir.isSymbolicLink(), 'Invalid coverage evidence directory')
    for (const filename of ['blob.json', 'report.json', 'coverage/coverage-final.json']) {
      const file = path.join(shardDir, filename)
      assert.equal(sha256(readRegular(file)), manifest.outputs[filename], `Changed/missing ${filename}`)
    }
    const report = JSON.parse(readRegular(path.join(shardDir, 'report.json')))
    assert.equal(report.success, true, 'Shard reporter did not complete successfully')
    assert.deepEqual(uniqueFiles(report.files), chosen, 'Missing or extra test file execution')
    assert(Array.isArray(report.tests) && report.tests.length > 0, 'Missing test case evidence')
    assert.equal(new Set(report.tests.map(test => test.id)).size, report.tests.length, 'Duplicate test case evidence')
    assert(report.tests.every(test => chosen.includes(test.file) && ['pass', 'skip', 'todo'].includes(test.state)), 'Failed/foreign test case')
    assert.deepEqual(report.coverage, manifest.coverage, 'Foreign coverage evidence')
    assert.deepEqual(coverageEvidence(JSON.parse(readRegular(path.join(shardDir, 'coverage/coverage-final.json'))), manifest.root), manifest.coverage, 'Changed raw coverage')
    manifests.push({ ...manifest, directory: shardDir })
    selected.push(...chosen)
  }
  assert.deepEqual(uniqueFiles(selected, 'Overlapping shard execution'), expectedFiles, 'Shard union differs from full suite')
  return manifests.sort((a, b) => a.index - b.index)
}
