/**
 * 解析后端 API 基址：优先环境变量 VITE_API_BASE，其次读取 .runtime/api.port
 * （由 run.py 启动时写入），实现前端代理自动跟随后端实际端口。
 *
 * macOS AirPlay 占用 5000 时，run.py 会自动避让到 5001+ 并写入 .runtime/api.port，
 * 前端 vite 启动时读取该文件即可对齐后端真实端口，无需手动改 VITE_API_BASE。
 */
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

export function resolveApiBase(envApiBase) {
  if (envApiBase) return envApiBase
  try {
    const __dirname = path.dirname(fileURLToPath(import.meta.url))
    // 本文件位于 frontend/vite/，.runtime 在仓库根 FHD/.runtime
    const portFile = path.resolve(__dirname, '..', '..', '.runtime', 'api.port')
    if (fs.existsSync(portFile)) {
      const port = parseInt(fs.readFileSync(portFile, 'utf-8').trim(), 10)
      if (Number.isFinite(port) && port > 0) {
        return `http://127.0.0.1:${port}`
      }
    }
  } catch {
    // 读取失败回退默认
  }
  return 'http://127.0.0.1:5000'
}
