/**
 * Windows 专用 E2E 预加载（由 Playwright 以 `-r` 注入）。
 *
 * Windows 上 Node 无法直接 spawn `stub-backend.mjs`（EFTYPE），因此把 dev 后端命令
 * 换成 Electron 自身以 Node 模式运行（ELECTRON_RUN_AS_NODE=1）。真实 `dist/main.js`
 * 仍原样启动，E2E 继续走生产窗口/回滚链路。非 Windows 保持原有 `PYTHON` 替身方式。
 */
if (process.platform === 'win32') {
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
  try {
    Object.defineProperty(app, 'isPackaged', { configurable: true, get: () => false })
  } catch {
    /* 属性不可配置时保持 Electron 默认值 */
  }
}
