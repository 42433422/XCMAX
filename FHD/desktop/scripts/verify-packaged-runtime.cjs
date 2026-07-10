#!/usr/bin/env node
'use strict'

const fs = require('node:fs')
const path = require('node:path')
const asar = require('@electron/asar')

function normalizeArchivePath(entry) {
  return entry.replaceAll('\\', '/').replace(/^\/+/, '')
}

function verifyPackagedRuntime(archivePath) {
  const resolvedArchive = path.resolve(archivePath)
  if (!fs.existsSync(resolvedArchive)) {
    throw new Error(`app.asar missing: ${resolvedArchive}`)
  }

  const entries = new Set(
    asar.listPackage(resolvedArchive).map(normalizeArchivePath)
  )

  for (const requiredEntry of ['package.json', 'dist/main.js']) {
    if (!entries.has(requiredEntry)) {
      throw new Error(`packaged runtime entry missing: ${requiredEntry}`)
    }
  }

  const packageCache = new Map()
  function readPackageJson(packageJsonPath) {
    if (packageCache.has(packageJsonPath)) {
      return packageCache.get(packageJsonPath)
    }
    if (!entries.has(packageJsonPath)) {
      return null
    }
    const payload = asar.extractFile(resolvedArchive, packageJsonPath)
    const parsed = JSON.parse(payload.toString('utf8'))
    packageCache.set(packageJsonPath, parsed)
    return parsed
  }

  function resolveDependencyPackage(fromPackageJsonPath, dependencyName) {
    let currentDir = path.posix.dirname(fromPackageJsonPath)
    if (currentDir === '.') currentDir = ''

    while (true) {
      const candidate = path.posix.join(
        currentDir,
        'node_modules',
        dependencyName,
        'package.json'
      )
      if (entries.has(candidate)) return candidate
      if (!currentDir) return null
      currentDir = path.posix.dirname(currentDir)
      if (currentDir === '.') currentDir = ''
    }
  }

  const rootPackage = readPackageJson('package.json')
  if (!rootPackage) {
    throw new Error('packaged package.json is unreadable')
  }

  const queue = [{ packageJsonPath: 'package.json', packageJson: rootPackage }]
  const visited = new Set()
  const missing = []

  while (queue.length > 0) {
    const current = queue.shift()
    if (visited.has(current.packageJsonPath)) continue
    visited.add(current.packageJsonPath)

    const dependencies = current.packageJson.dependencies || {}
    const optionalDependencies = current.packageJson.optionalDependencies || {}
    for (const dependencyName of Object.keys(dependencies).sort()) {
      if (Object.hasOwn(optionalDependencies, dependencyName)) continue

      const dependencyPackageJsonPath = resolveDependencyPackage(
        current.packageJsonPath,
        dependencyName
      )
      if (!dependencyPackageJsonPath) {
        const parent = current.packageJson.name || current.packageJsonPath
        missing.push(`${parent} -> ${dependencyName}`)
        continue
      }

      const dependencyPackage = readPackageJson(dependencyPackageJsonPath)
      if (!dependencyPackage) {
        missing.push(`${dependencyPackageJsonPath} is unreadable`)
        continue
      }
      queue.push({
        packageJsonPath: dependencyPackageJsonPath,
        packageJson: dependencyPackage
      })
    }
  }

  if (missing.length > 0) {
    throw new Error(
      `packaged runtime dependency graph is incomplete:\n- ${missing.join('\n- ')}`
    )
  }

  return { packagesChecked: visited.size, archivePath: resolvedArchive }
}

function main(argv) {
  const archivePath = argv[2]
  if (!archivePath) {
    console.error('Usage: node verify-packaged-runtime.cjs <path-to-app.asar>')
    return 2
  }

  try {
    const result = verifyPackagedRuntime(archivePath)
    console.log(
      `[packaged-runtime] verified ${result.packagesChecked} runtime packages in ${result.archivePath}`
    )
    return 0
  } catch (error) {
    console.error(`[packaged-runtime] ${error.message}`)
    return 1
  }
}

if (require.main === module) {
  process.exitCode = main(process.argv)
}

module.exports = { normalizeArchivePath, verifyPackagedRuntime }
