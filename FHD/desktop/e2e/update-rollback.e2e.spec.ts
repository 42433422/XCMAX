import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test'
import crypto from 'node:crypto'
import fs from 'node:fs'
import http from 'node:http'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'

/**
 * 真实端到端：更新签名校验链路 + 更新后回滚观察期提交链路。
 *
 * 与 desktop.e2e.spec.ts（启动/安全/IPC 基线）不同，本文件聚焦两条单测无法覆盖的
 * 真实主进程链路（均在真实 Electron net / fs / crypto 上运行，非 mock）：
 *
 *   1. 更新元数据 Ed25519 二次签名校验：
 *      渲染进程 IPC `xcagi:check-for-updates` → 主进程 runUpdateCheckWithDirectNet
 *      → checkForUpdates → fetchLatestMetadataText（真实 net.request 拉取本地更新源）
 *      → verifyMetadataSignatureText（真实 crypto.verify）。
 *      有效签名 → 检查通过；篡改/错误密钥签名 → 拒绝并抛出 Ed25519 错误。
 *
 *   2. 更新后回滚观察期「提交」链路：
 *      启动前预置 rollback-marker.json（模拟 quitAndInstall 后的首次启动）→
 *      bootstrap 进入观察期 → stub 后端就绪 + 主界面加载 + 5s 稳定性窗口全部通过 →
 *      commitRollback() 删除 marker。通过轮询真实文件系统验证 marker 被删除。
 *
 * 说明：dev（未打包）模式下 autoUpdater.checkForUpdates 直接返回 null（不触发下载），
 * 因此这里断言的是「签名校验是否放行/拦截」这一安全边界，而非真实下载安装。
 * 打包后的备份/还原（prepareRollback/triggerRollback）已由 rollback.test.ts 单测覆盖。
 */

let electronApp: ElectronApplication
let page: Page
let userDataDir: string
let backendPort: number
let updateServerPort: number
let updateServer: http.Server

/** 由更新源服务器动态返回的元数据内容，各用例在调用前置位。 */
let currentMetadata = ''

const ROLLBACK_MARKER = 'rollback-marker.json'

// 动态生成 Ed25519 密钥对（正确密钥 + 一把用于负向用例的错误密钥），避免硬编码私钥。
const keyPair = crypto.generateKeyPairSync('ed25519')
const TEST_PUBLIC_KEY_PEM = keyPair.publicKey.export({ type: 'spki', format: 'pem' }).toString()
const TEST_PRIVATE_KEY_PEM = keyPair.privateKey.export({ type: 'pkcs8', format: 'pem' }).toString()
const wrongKeyPair = crypto.generateKeyPairSync('ed25519')
const WRONG_PRIVATE_KEY_PEM = wrongKeyPair.privateKey.export({ type: 'pkcs8', format: 'pem' }).toString()

function signMetadata(body: string, privateKeyPem: string): string {
  const privateKey = crypto.createPrivateKey(privateKeyPem)
  const signature = crypto.sign(null, Buffer.from(body, 'utf8'), privateKey)
  return `${body}\nsignature: ed25519:${signature.toString('base64')}`
}

// 贴近真实 latest-mac.yml 的元数据主体（含 buildSha / releaseDate / 强制升级字段）。
const METADATA_BODY = [
  'version: 9.9.9',
  'files:',
  '  - url: XCAGI-9.9.9-mac.zip',
  '    sha512: fake-sha512',
  '    size: 12345',
  'path: XCAGI-9.9.9-mac.zip',
  'sha512: fake-sha512',
  `releaseDate: '2026-08-23T00:00:00.000Z'`,
  `buildSha: ${'a'.repeat(40)}`,
  'minVersion: 1.0.0.0',
  'forceUpgrade: false',
].join('\n')

const VALID_METADATA = signMetadata(METADATA_BODY, TEST_PRIVATE_KEY_PEM)
// 篡改主体（改动 version 行）但保留旧签名 → 验签必须失败。
const TAMPERED_METADATA = signMetadata(METADATA_BODY, TEST_PRIVATE_KEY_PEM).replace(
  'version: 9.9.9',
  'version: 9.9.8',
)
// 用错误密钥签名 → 验签必须失败。
const WRONG_KEY_METADATA = signMetadata(METADATA_BODY, WRONG_PRIVATE_KEY_PEM)

async function findFreePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = net.createServer()
    srv.once('error', reject)
    srv.listen(0, '127.0.0.1', () => {
      const address = srv.address()
      if (!address || typeof address === 'string') {
        srv.close(() => reject(new Error('无法分配空闲端口')))
        return
      }
      srv.close(() => resolve(address.port))
    })
  })
}

/** 本地更新源替身：按 currentMetadata 返回 latest*.yml。 */
function startUpdateServer(port: number): Promise<http.Server> {
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      const url = new URL(req.url || '/', `http://127.0.0.1:${port}`)
      if (url.pathname === '/latest-mac.yml' || url.pathname === '/latest.yml') {
        res.writeHead(200, { 'Content-Type': 'text/yaml; charset=utf-8' })
        res.end(currentMetadata)
        return
      }
      res.writeHead(404, { 'Content-Type': 'text/plain' })
      res.end('not found')
    })
    server.once('error', reject)
    server.listen(port, '127.0.0.1', () => resolve(server))
  })
}

test.beforeAll(async () => {
  backendPort = await findFreePort()
  updateServerPort = await findFreePort()
  currentMetadata = VALID_METADATA
  updateServer = await startUpdateServer(updateServerPort)

  userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-e2e-updroll-'))
  // 预置回滚 marker：模拟「quitAndInstall 之后的首次启动」，进入观察期。
  fs.writeFileSync(
    path.join(userDataDir, ROLLBACK_MARKER),
    JSON.stringify(
      {
        mode: 'backend',
        fromVersion: '9.9.8',
        toVersion: '9.9.9',
        preparedAt: new Date().toISOString(),
        backendPath: '/nonexistent/backend/xcagi-backend',
        backupRelPath: 'backend-9.9.8',
      },
      null,
      2,
    ),
    'utf8',
  )

  electronApp = await electron.launch({
    args: ['.'],
    cwd: path.resolve(__dirname, '..'),
    env: {
      ...process.env,
      // E2E 隔离开关：跳过登录项/协议注册/全局快捷键/OTA 自动检查（见 main.ts）
      XCAGI_DESKTOP_E2E: '1',
      XCAGI_DESKTOP_PORT: String(backendPort),
      XCAGI_DESKTOP_USER_DATA_DIR: userDataDir,
      // dev 模式后端可执行文件 → 指向 E2E stub（node shebang 脚本）
      PYTHON: path.resolve(__dirname, 'stub-backend.mjs'),
      // 更新链路：指向本地更新源替身 + 注入测试 Ed25519 公钥（main.ts 不会覆盖已设置的值）
      XCAGI_UPDATE_URL: `http://127.0.0.1:${updateServerPort}/`,
      XCAGI_UPDATE_ED25519_PUBLIC_KEY: TEST_PUBLIC_KEY_PEM,
    },
  })
  page = await electronApp.firstWindow()
  page.on('console', msg => {
    if (msg.type() === 'error') {
      console.info(`[renderer console.error] ${msg.text()}`)
    }
  })
})

test.afterAll(async () => {
  if (electronApp) {
    await electronApp.close()
  }
  if (updateServer) {
    await new Promise<void>(resolve => updateServer.close(() => resolve()))
  }
  if (userDataDir) {
    fs.rmSync(userDataDir, { recursive: true, force: true })
  }
})

test('真实启动链路：观察期启动仍能加载主界面', async () => {
  await page.waitForURL(`http://127.0.0.1:${backendPort}/?shell=1`, { timeout: 90_000 })
  await expect(page.locator('#e2e-marker')).toHaveText('XCAGI_E2E_OK')
})

test('更新链路：有效 Ed25519 签名的元数据通过校验（检查放行）', async () => {
  currentMetadata = VALID_METADATA
  const result = await page.evaluate(async () => {
    try {
      const value = await (
        window as unknown as { xcagiDesktop: { checkForUpdates: () => Promise<unknown> } }
      ).xcagiDesktop.checkForUpdates()
      return { ok: true, isNull: value === null }
    } catch (error) {
      return { ok: false, message: error instanceof Error ? error.message : String(error) }
    }
  })
  // dev 模式 autoUpdater 返回 null；关键是未因签名被拒绝（未抛 Ed25519 错误）。
  expect(result.ok, `有效签名应放行，但检查失败：${'message' in result ? result.message : ''}`).toBe(true)
})

test('更新链路：篡改主体的元数据被 Ed25519 校验拒绝', async () => {
  currentMetadata = TAMPERED_METADATA
  const result = await page.evaluate(async () => {
    try {
      await (
        window as unknown as { xcagiDesktop: { checkForUpdates: () => Promise<unknown> } }
      ).xcagiDesktop.checkForUpdates()
      return { ok: true }
    } catch (error) {
      return { ok: false, message: error instanceof Error ? error.message : String(error) }
    }
  })
  expect(result.ok).toBe(false)
  expect('message' in result ? result.message : '').toMatch(/Ed25519/)
})

test('更新链路：错误密钥签名的元数据被 Ed25519 校验拒绝', async () => {
  currentMetadata = WRONG_KEY_METADATA
  const result = await page.evaluate(async () => {
    try {
      await (
        window as unknown as { xcagiDesktop: { checkForUpdates: () => Promise<unknown> } }
      ).xcagiDesktop.checkForUpdates()
      return { ok: true }
    } catch (error) {
      return { ok: false, message: error instanceof Error ? error.message : String(error) }
    }
  })
  expect(result.ok).toBe(false)
  expect('message' in result ? result.message : '').toMatch(/Ed25519/)
})

test('回滚链路：更新后观察期稳定启动 → commitRollback 删除 marker', async () => {
  const markerPath = path.join(userDataDir, ROLLBACK_MARKER)
  // 启动前已预置 marker；观察期提交后应被删除。轮询真实文件系统（含 5s 稳定性窗口）。
  await expect
    .poll(() => fs.existsSync(markerPath), { timeout: 45_000, intervals: [500, 1000, 2000] })
    .toBe(false)
})
