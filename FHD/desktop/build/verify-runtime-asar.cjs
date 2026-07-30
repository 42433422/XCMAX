/**
 * Verify that a packaged Electron ASAR contains the complete production
 * dependency closure required by its root package manifest.
 *
 * electron-builder flattens node_modules while packaging. A stale or
 * incompatible builder can therefore leave a transitive module out of the
 * archive even though the source tree happens to resolve it. Validate the
 * archive itself before it is sealed into an installer.
 */
const fs = require('node:fs')
const path = require('node:path')
const { builtinModules } = require('node:module')
const asar = require('@electron/asar')

const BUILTIN_MODULES = new Set([...builtinModules, ...builtinModules.map(name => `node:${name}`)])

function closureError(message) {
  const error = new Error(`XCAGI_ASAR_RUNTIME_CLOSURE_FAILED: ${message}`)
  error.code = 'XCAGI_ASAR_RUNTIME_CLOSURE_FAILED'
  return error
}

function normalizeArchivePath(value) {
  return value.replace(/^\/+/, '').split(path.sep).join('/')
}

function readArchiveJson(archivePath, entries, manifestPath) {
  if (!entries.has(manifestPath)) {
    throw closureError(`runtime package manifest is missing: ${manifestPath}`)
  }
  try {
    return JSON.parse(asar.extractFile(archivePath, manifestPath).toString('utf8'))
  } catch (error) {
    throw closureError(`runtime package manifest is invalid: ${manifestPath}; ${error.message}`)
  }
}

function packageSearchRoots(packageDirectory) {
  const roots = []
  let current = packageDirectory
  while (current && current !== '.') {
    if (path.posix.basename(current) !== 'node_modules') {
      roots.push(path.posix.join(current, 'node_modules'))
    }
    current = path.posix.dirname(current)
  }
  roots.push('node_modules')
  return [...new Set(roots)]
}

function findPackageManifest(entries, packageDirectory, dependencyName) {
  for (const searchRoot of packageSearchRoots(packageDirectory)) {
    const candidate = path.posix.join(searchRoot, dependencyName, 'package.json')
    if (entries.has(candidate)) return candidate
  }
  return null
}

function productionDependencies(manifest) {
  const required = Object.keys(manifest.dependencies || {})
  const optional = Object.keys(manifest.optionalDependencies || {})
  return {
    required,
    optional: optional.filter(name => !required.includes(name)),
  }
}

function verifyRuntimeAsarDependencyClosure(archivePath) {
  const resolvedArchivePath = path.resolve(archivePath)
  if (!fs.existsSync(resolvedArchivePath)) {
    throw closureError(`ASAR archive is missing: ${resolvedArchivePath}`)
  }

  let entries
  try {
    entries = new Set(asar.listPackage(resolvedArchivePath).map(normalizeArchivePath))
  } catch (error) {
    throw closureError(`cannot read ASAR archive: ${resolvedArchivePath}; ${error.message}`)
  }

  const visited = new Set()
  const packageNames = []

  function visit(manifestPath) {
    if (visited.has(manifestPath)) return
    visited.add(manifestPath)

    const manifest = readArchiveJson(resolvedArchivePath, entries, manifestPath)
    const packageDirectory = manifestPath === 'package.json' ? '' : path.posix.dirname(manifestPath)
    const packageName = typeof manifest.name === 'string' && manifest.name ? manifest.name : manifestPath
    packageNames.push(packageName)

    const { required, optional } = productionDependencies(manifest)
    for (const dependencyName of required) {
      if (BUILTIN_MODULES.has(dependencyName)) continue
      const dependencyManifest = findPackageManifest(entries, packageDirectory, dependencyName)
      if (!dependencyManifest) {
        throw closureError(
          `runtime dependency is missing: ${packageName} requires ${dependencyName} (${manifestPath})`,
        )
      }
      visit(dependencyManifest)
    }
    for (const dependencyName of optional) {
      if (BUILTIN_MODULES.has(dependencyName)) continue
      const dependencyManifest = findPackageManifest(entries, packageDirectory, dependencyName)
      if (dependencyManifest) visit(dependencyManifest)
    }
  }

  visit('package.json')
  return {
    archivePath: resolvedArchivePath,
    packageCount: visited.size,
    packageNames,
  }
}

function runCli() {
  const archivePaths = process.argv.slice(2)
  if (!archivePaths.length) {
    console.error('Usage: node build/verify-runtime-asar.cjs <app.asar> [more archives...]')
    process.exitCode = 2
    return
  }

  for (const archivePath of archivePaths) {
    try {
      const result = verifyRuntimeAsarDependencyClosure(archivePath)
      console.log(
        `[asar-runtime-closure] verified ${result.archivePath} (${result.packageCount} runtime packages)`,
      )
    } catch (error) {
      console.error(`[asar-runtime-closure] ${error.message}`)
      process.exitCode = 1
    }
  }
}

if (require.main === module) runCli()

module.exports = {
  findPackageManifest,
  productionDependencies,
  verifyRuntimeAsarDependencyClosure,
}
