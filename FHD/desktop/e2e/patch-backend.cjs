/**
 * E2E 后端预加载（由 Playwright 以 `-r` 注入）。
 *
 * 仓库中的 stub-backend.mjs 是普通源文件（100644），直接 spawn 在 POSIX 上
 * EACCES，在 Windows 上 EFTYPE。所有平台都复用 Electron 的 Node 模式运行它，
 * 不依赖 shebang、执行位或 PATH 中另一版 Node。真实 dist/main.js 与身份探测不变。
 */
{
  const path = require('node:path')
  const cp = require('node:child_process')
  const { app } = require('electron')

  const stub = path.resolve(__dirname, 'stub-backend.mjs')
  const config = require('../dist/desktop-config.js')

  config.backendExecutable = () => ({
    command: process.execPath,
    args: [
      stub,
      '--host',
      config.DESKTOP_BACKEND_BIND_HOST,
      '--port',
      String(config.DEFAULT_PORT),
    ],
    cwd: path.resolve(__dirname, '..'),
  })

  const originalSpawn = cp.spawn
  cp.spawn = (command, args, options) => {
    if (command === process.execPath && Array.isArray(args) && args[0] === stub) {
      options = { ...options, env: { ...options.env, ELECTRON_RUN_AS_NODE: '1' } }
    }
    return originalSpawn(command, args, options)
  }

  // 本机 Electron 44 在 `electron .` 开发启动时也报告 isPackaged=true，
  // 会让 E2E 走打包路径（app-update.yml 等）。E2E 始终是未打包运行，显式还原。
  if (process.platform === 'win32') {
    try {
      Object.defineProperty(app, 'isPackaged', { configurable: true, get: () => false })
    } catch {
      /* 属性不可配置时保持 Electron 默认值 */
    }
  }
}
