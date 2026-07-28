/**
 * electron-builder beforePack 钩子。
 *
 * 在打包前调用 scripts/package/generate-desktop-resources.py 生成 NSIS 安装包
 * 位图与应用图标（icon.ico / icon.png / icon.icns / installer-*.bmp）。
 *
 * 运行上下文：electron-builder 以 desktop/ 为 appDir，cwd 通常为 desktop/。
 * 仓库根 = desktop/ 的上一级。
 *
 * 容错策略：资源生成失败时不中断打包（resources/ 可能已被预生成或手动覆盖），
 * 仅打印警告。这样 CI 与本地打包均能继续。
 */
const { execFileSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

function log(msg) {
  console.log(`[before-pack] ${msg}`)
}

/**
 * Electron 在部分 macOS ASAR 启动路径中会把 `dist/` 当作入口包目录，
 * 因而会读取 `app.asar/dist/package.json`。根 package.json 的
 * `main: dist/main.js` 不能替代这份嵌套清单：若它不存在，Electron 会在
 * main 进程运行前以 ENOENT 退出。
 *
 * 不复制开发依赖、脚本或发布配置，以免把开发期元数据带入运行时 ASAR。
 * 该清单的入口相对于 dist/，故必须是 `main.js`（而非 `dist/main.js`）。
 */
function writeDesktopRuntimePackage(desktopDir) {
  const sourcePath = path.join(desktopDir, 'package.json')
  const distDir = path.join(desktopDir, 'dist')
  const mainPath = path.join(distDir, 'main.js')
  const outputPath = path.join(distDir, 'package.json')

  if (!fs.existsSync(sourcePath)) {
    throw new Error(`desktop package manifest is missing: ${sourcePath}`)
  }
  if (!fs.existsSync(mainPath)) {
    throw new Error(`desktop runtime entry is missing: ${mainPath}`)
  }

  let source
  try {
    source = JSON.parse(fs.readFileSync(sourcePath, 'utf8'))
  } catch (err) {
    throw new Error(`desktop package manifest is invalid JSON: ${sourcePath}; ${err.message}`)
  }
  if (source.main !== 'dist/main.js') {
    throw new Error(
      `desktop package main must remain dist/main.js before packaging; received ${JSON.stringify(source.main)}`
    )
  }
  if (typeof source.name !== 'string' || !source.name.trim()) {
    throw new Error(`desktop package name is required before packaging: ${sourcePath}`)
  }
  if (typeof source.version !== 'string' || !source.version.trim()) {
    throw new Error(`desktop package version is required before packaging: ${sourcePath}`)
  }

  const runtimePackage = {
    name: source.name,
    version: source.version,
    private: Boolean(source.private),
    ...(typeof source.author === 'string' && source.author ? { author: source.author } : {}),
    ...(typeof source.description === 'string' && source.description
      ? { description: source.description }
      : {}),
    // This file lives inside dist/, so its entry must be relative to dist/.
    main: 'main.js',
    type: source.type === 'module' ? 'module' : 'commonjs',
  }

  const temporaryPath = `${outputPath}.tmp-${process.pid}`
  fs.writeFileSync(temporaryPath, `${JSON.stringify(runtimePackage, null, 2)}\n`, 'utf8')
  fs.renameSync(temporaryPath, outputPath)
  return outputPath
}

/** 探测可用的 Python 解释器（python3 优先）。 */
function findPython() {
  for (const cmd of ['python3', 'python']) {
    try {
      execFileSync(cmd, ['--version'], { stdio: 'ignore' })
      return cmd
    } catch {
      // 继续尝试下一个
    }
  }
  return null
}

/** 确保 Pillow 可用（generate-desktop-resources.py 依赖 PIL）。 */
function ensurePillow(py, repoRoot) {
  try {
    execFileSync(py, ['-c', 'import PIL'], { stdio: 'ignore', cwd: repoRoot })
    return true
  } catch {
    log('Pillow 未安装，尝试安装...')
    try {
      execFileSync(py, ['-m', 'pip', 'install', 'Pillow>=10.2.0', '-q'], {
        stdio: 'inherit',
        cwd: repoRoot
      })
      return true
    } catch (err) {
      log(`Pillow 安装失败: ${err.message}`)
      return false
    }
  }
}

exports.default = async function beforePack(context) {
  const desktopDir = context.appDir || process.cwd()
  const repoRoot = path.resolve(desktopDir, '..')
  const script = path.join(repoRoot, 'scripts', 'package', 'generate-desktop-resources.py')

  const runtimePackagePath = writeDesktopRuntimePackage(desktopDir)
  log(`生成 ASAR 运行时入口清单: ${runtimePackagePath}`)

  if (!fs.existsSync(script)) {
    log(`generate-desktop-resources.py 不存在，跳过资源生成: ${script}`)
    return
  }

  const py = findPython()
  if (!py) {
    log('未找到 python3/python，跳过资源生成（请确保 resources/ 已预生成）')
    return
  }

  if (!ensurePillow(py, repoRoot)) {
    log('Pillow 不可用，跳过资源生成（请确保 resources/ 已预生成）')
    return
  }

  log(`生成桌面端资源: ${script}`)
  try {
    execFileSync(py, [script], { stdio: 'inherit', cwd: repoRoot })
    log('桌面端资源生成完成')
  } catch (err) {
    // 资源生成失败不中断打包：resources/ 可能已被预生成或手动覆盖
    log(`资源生成失败（忽略，使用已有 resources/）: ${err.message}`)
  }
}

// Exported for the focused packaging test. electron-builder only consumes the
// default hook above.
exports.writeDesktopRuntimePackage = writeDesktopRuntimePackage
