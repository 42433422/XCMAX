#!/usr/bin/env node
/**
 * P-App 真机/模拟器全页截图（adb + 深链巡检）— SA 节点主执行器。
 */
import fs from 'node:fs'
import path from 'node:path'
import { execFileSync, spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { loginSurfaceAuditForLane } from './surface_audit_auth.mjs'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const FHD_ROOT = path.resolve(__dirname, '../..')
const CONFIG_PATH = path.join(FHD_ROOT, 'config/surface_audit_pages.json')

function resolveSku() {
  const fromEnv = (process.env.SURFACE_AUDIT_PRODUCT_SKU || '').trim()
  if (fromEnv) return fromEnv
  try {
    const cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'))
    return cfg.lanes?.['P-App']?.product_sku || 'personal'
  } catch {
    return 'personal'
  }
}

const SKU = resolveSku()
const DEFAULT_ADB = path.join(FHD_ROOT, 'mobile-android/.toolchain/android-sdk/platform-tools/adb')
const PACKAGE =
  process.env.SURFACE_AUDIT_ANDROID_PACKAGE ||
  (SKU === 'enterprise' ? 'com.xiuci.xcagi.mobile.enterprise' : 'com.xiuci.xcagi.mobile.personal')
const APK_CANDIDATES =
  SKU === 'enterprise'
    ? [
        path.join(FHD_ROOT, 'mobile-android/app/build/outputs/apk/enterprise/debug/app-enterprise-debug.apk'),
        path.join(FHD_ROOT, 'mobile-android/app/build/outputs/apk/enterpriseDebug/app-enterprise-debug.apk'),
      ]
    : [
        path.join(FHD_ROOT, 'mobile-android/app/build/outputs/apk/personal/debug/app-personal-debug.apk'),
        path.join(FHD_ROOT, 'mobile-android/app/build/outputs/apk/personalDebug/app-personal-debug.apk'),
      ]

const outArgIdx = process.argv.indexOf('--out')
const OUT_PATH = outArgIdx >= 0 ? process.argv[outArgIdx + 1] : ''
const SAMPLE = process.argv.includes('--sample') || process.env.SURFACE_AUDIT_ANDROID_SAMPLE === '1'
const MAX_PAGES = Number(process.env.SURFACE_AUDIT_ANDROID_MAX_PAGES || '0')

const ADB = process.env.SURFACE_AUDIT_ANDROID_ADB || (fs.existsSync(DEFAULT_ADB) ? DEFAULT_ADB : 'adb')
const ACTIVITY = `${PACKAGE}/com.xiuci.xcagi.mobile.MainActivity`
const FHD_HOST = process.env.SURFACE_AUDIT_ANDROID_FHD_HOST || '10.0.2.2:5000'
const DEFAULT_WAIT_MS = Number(process.env.SURFACE_AUDIT_ANDROID_WAIT_MS || '4000')
const FOREGROUND_TIMEOUT_MS = Number(process.env.SURFACE_AUDIT_ANDROID_FOREGROUND_MS || '15000')
const ADB_TIMEOUT_MS = Number(process.env.SURFACE_AUDIT_ANDROID_ADB_TIMEOUT_MS || '60000')
const MOD_ID = process.env.SURFACE_AUDIT_SAMPLE_MOD_ID || 'taiyangniao-pro'

const FRESH_ROUTES = new Set(['legal', 'connect', 'auth', 'register'])
const WEBVIEW_IDS = new Set(['workbench', 'mod_web', 'chat', 'market', 'bridge'])
const COLD_START_IDS = new Set(['legal', 'connect', 'auth', 'register', 'splash'])
const MODSTORE_HOST = (process.env.SURFACE_AUDIT_MODSTORE_HOST || 'xiu-ci.com').trim()
const SKIP_FORCE_UPDATE = process.env.SURFACE_AUDIT_SKIP_FORCE_UPDATE !== '0'

let modstoreBlockIps = []
let modstoreBlocked = false

function adb(...args) {
  return execFileSync(ADB, args, { encoding: 'utf8', maxBuffer: 20 * 1024 * 1024, timeout: ADB_TIMEOUT_MS }).trim()
}

function adbBuf(...args) {
  return execFileSync(ADB, args, { maxBuffer: 20 * 1024 * 1024, timeout: ADB_TIMEOUT_MS })
}

function resolveApk() {
  for (const p of APK_CANDIDATES) {
    if (fs.existsSync(p)) return p
  }
  return ''
}

function packageInstalled() {
  try {
    const out = adb('shell', 'pm', 'path', PACKAGE)
    return Boolean(out && out.includes('package:'))
  } catch {
    return false
  }
}

/** 模拟器已装更高 versionCode 时允许跳过/降级，避免 INSTALL_FAILED_VERSION_DOWNGRADE 阻断 adb 截图。 */
function installApkIfNeeded(apk) {
  if (!apk) return
  if (process.env.SURFACE_AUDIT_SKIP_APK_INSTALL === '1' && packageInstalled()) return
  try {
    adb('install', '-r', apk)
    return
  } catch (err) {
    const msg = String(err)
    if (msg.includes('VERSION_DOWNGRADE') || msg.includes('INSTALL_FAILED_VERSION_DOWNGRADE')) {
      if (packageInstalled()) return
      try {
        adb('install', '-r', '-d', apk)
        return
      } catch {
        if (packageInstalled()) return
      }
    }
    throw err
  }
}

function androidRoute(pageDef) {
  let route = pageDef.android_route || pageDef.id
  if (pageDef.path_template || pageDef.id === 'mod_web') {
    route = `mod/${MOD_ID}`
  }
  return route
}

function uninstallPersonalPackage() {
  if (SKU !== 'enterprise') return
  try {
    adb('uninstall', 'com.xiuci.xcagi.mobile.personal')
  } catch {
    /* 未安装个人版时忽略 */
  }
}

function waitMs(pageDef) {
  if (pageDef.android_wait_ms) return Number(pageDef.android_wait_ms)
  if (WEBVIEW_IDS.has(pageDef.id)) return Math.max(DEFAULT_WAIT_MS, 7500)
  if (pageDef.id === 'connect' || pageDef.id === 'splash') return Math.max(DEFAULT_WAIT_MS, 5500)
  if (pageDef.id === 'auth' || pageDef.id === 'register') return Math.max(DEFAULT_WAIT_MS, 12000)
  return DEFAULT_WAIT_MS
}

function isAppForeground() {
  try {
    const resumed = adb(
      'shell',
      'sh',
      '-c',
      "dumpsys activity activities 2>/dev/null | grep -E 'mResumedActivity|topResumedActivity' | tail -3",
    )
    if (resumed.includes(PACKAGE) && resumed.includes('MainActivity')) return true
    const focus = adb('shell', 'dumpsys', 'window', 'windows')
    const line = focus.split('\n').find((l) => l.includes('mCurrentFocus') || l.includes('mFocusedApp'))
    return Boolean(line && line.includes(PACKAGE))
  } catch {
    return false
  }
}

function waitForAppForeground(timeoutMs = FOREGROUND_TIMEOUT_MS) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (isAppForeground()) return true
    sleep(400)
  }
  return false
}

function resolveModstoreIps() {
  if (modstoreBlockIps.length) return modstoreBlockIps
  try {
    adb('root')
  } catch {
    return []
  }
  try {
    const out = adb('shell', 'ping', '-c', '1', MODSTORE_HOST)
    const m = out.match(/\(([\d.]+)\)/)
    if (m) modstoreBlockIps = [m[1]]
  } catch {
    modstoreBlockIps = []
  }
  return modstoreBlockIps
}

function setModstoreBlocked(block) {
  if (!SKIP_FORCE_UPDATE) return
  const ips = resolveModstoreIps()
  if (!ips.length) return
  try {
    adb('root')
    for (const ip of ips) {
      if (block && !modstoreBlocked) {
        adb('shell', 'iptables', '-I', 'OUTPUT', '1', '-d', ip, '-j', 'DROP')
      } else if (!block && modstoreBlocked) {
        adb('shell', 'iptables', '-D', 'OUTPUT', '-d', ip, '-j', 'DROP')
      }
    }
    modstoreBlocked = block
  } catch {
    /* 非 root 设备跳过 */
  }
}

function reinstallPersonalApk() {
  if (SKU !== 'enterprise') return
  const personalApk = path.join(
    FHD_ROOT,
    'mobile-android/app/build/outputs/apk/personal/debug/app-personal-debug.apk',
  )
  if (!fs.existsSync(personalApk)) return
  try {
    adb('install', '-r', personalApk)
  } catch {
    /* 可选恢复个人版 */
  }
}

function capturePageScreenshot(pageDef, route, fresh, auditAuth) {
  const needsModstore = WEBVIEW_IDS.has(pageDef.id)
  setModstoreBlocked(!needsModstore)
  if (pageDef.id === 'auth' || pageDef.id === 'register') {
    try {
      adb('shell', 'pm', 'clear', PACKAGE)
      sleep(800)
    } catch {
      /* ignore */
    }
  }
  adb('shell', 'am', 'force-stop', PACKAGE)
  sleep(400)
  let settled = false
  let foreground = false
  for (let attempt = 0; attempt < 3; attempt += 1) {
    settled = launchAndSettle(route, fresh, auditAuth, pageDef)
    const navExtra = !fresh && route !== 'home_hub' && route !== 'splash' ? 1800 : 0
    const blockExtra = needsModstore ? 0 : 3000
    sleep(waitMs(pageDef) + navExtra + blockExtra)
    foreground = isAppForeground()
    if (settled && foreground) break
    adb('shell', 'am', 'force-stop', PACKAGE)
    sleep(600)
  }
  setModstoreBlocked(false)
  const b64 = foreground ? capturePngB64() : ''
  const analysis = ['Android App adb 截图（SA 真机巡检）']
  if (!settled) analysis.push('警告: App 启动超时')
  if (!foreground) analysis.push('警告: 截屏时 App 可能未在前台')
  return {
    settled,
    foreground,
    b64,
    analysis,
    status: settled && foreground ? 200 : 206,
  }
}

function launchAndSettle(route, fresh, auth, pageDef) {
  const intentAuth = fresh ? null : auth
  const attempts = pageDef.id === 'connect' || pageDef.id === 'auth' ? 3 : 2
  const fgTimeout =
    pageDef.id === 'connect' ? 12000 : pageDef.id === 'auth' || pageDef.id === 'register' ? 20000 : FOREGROUND_TIMEOUT_MS
  for (let i = 0; i < attempts; i += 1) {
    launchRoute(route, fresh, intentAuth)
    if (waitForAppForeground(fgTimeout)) {
      sleep(pageDef.id === 'connect' ? 1200 : pageDef.id === 'auth' ? 1500 : 500)
      return true
    }
    sleep(800)
  }
  return false
}

function launchRoute(route, fresh, auth) {
  const args = [
    'shell', 'am', 'start', '-W', '-n', ACTIVITY,
    '--ez', 'surface_audit', 'true',
    '--ez', 'audit_skip_update', 'true',
    '--es', 'audit_route', route,
    '--es', 'audit_fhd_host', FHD_HOST,
  ]
  if (fresh) args.push('--ez', 'audit_fresh', 'true')
  if (auth?.access_token) {
    args.push('--es', 'audit_access_token', auth.access_token)
    if (auth.refresh_token) args.push('--es', 'audit_refresh_token', auth.refresh_token)
    if (auth.session_id) args.push('--es', 'audit_session_id', auth.session_id)
    if (auth.username) args.push('--es', 'audit_username', auth.username)
    if (auth.user_id) args.push('--ei', 'audit_user_id', String(auth.user_id))
    if (auth.market_access_token) args.push('--es', 'audit_market_access', auth.market_access_token)
    if (auth.market_refresh_token) args.push('--es', 'audit_market_refresh', auth.market_refresh_token)
  }
  adb(...args)
}

function capturePngB64() {
  const buf = adbBuf('exec-out', 'screencap', '-p')
  return buf.toString('base64')
}

function sleep(ms) {
  spawnSync('sleep', [String(Math.max(1, Math.ceil(ms / 1000)))], { stdio: 'ignore' })
}

function filterPages(pages) {
  return (pages || []).filter((p) => {
    if (p.web_only) return false
    if (!p.android_route && !p.id) return false
    if (p.sku === 'enterprise' && (process.env.SURFACE_AUDIT_PRODUCT_SKU || 'personal') === 'personal') {
      return process.env.SURFACE_AUDIT_INCLUDE_ENTERPRISE === '1'
    }
    return true
  })
}

function pickSamplePages(pages) {
  const preferred = ['home_hub', 'chat', 'auth', 'splash', 'connect']
  for (const id of preferred) {
    const found = pages.find((p) => p.id === id)
    if (found) return [found]
  }
  return pages.slice(0, 1)
}

async function main() {
  let auditAuth = null
  try {
    auditAuth = await loginSurfaceAuditForLane('P-App')
  } catch (err) {
    return finish({ success: false, message: `巡检登录失败: ${err}`, pages: [] })
  }

  let devices = []
  try {
    const lines = adb('devices').split('\n').slice(1)
    devices = lines.filter((l) => l.trim() && l.includes('device') && !l.includes('devices'))
  } catch (err) {
    return finish({ success: false, message: `adb 不可用: ${err}`, pages: [] })
  }

  if (!devices.length) {
    return finish({
      success: false,
      message: '未检测到 Android 设备/模拟器',
      pages: [],
      hint: 'make android-emulator-start',
    })
  }

  const cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'))
  const laneCfg = cfg.lanes['P-App']
  let appPages = filterPages(laneCfg?.pages)
  if (SAMPLE || MAX_PAGES === 1) {
    appPages = pickSamplePages(appPages)
  } else if (Number.isFinite(MAX_PAGES) && MAX_PAGES > 1) {
    appPages = appPages.slice(0, MAX_PAGES)
  }

  const apk = resolveApk()
  if (apk) {
    try {
      installApkIfNeeded(apk)
    } catch (err) {
      reinstallPersonalApk()
      return finish({ success: false, message: `APK 安装失败: ${err}`, pages: [] })
    }
  }

  uninstallPersonalPackage()

  const results = []
  for (const pageDef of appPages) {
    const route = androidRoute(pageDef)
    const fresh = FRESH_ROUTES.has(pageDef.id) || FRESH_ROUTES.has(route)
    try {
      const shot = capturePageScreenshot(pageDef, route, fresh, auditAuth)
      results.push({
        id: pageDef.id,
        name: pageDef.name,
        android_route: route,
        url: `xcagi://audit/nav/${route}`,
        status: shot.status,
        native: !!pageDef.native,
        android_capture: true,
        console_errors: [],
        screenshot_b64: shot.b64,
        analysis: shot.analysis,
      })
    } catch (err) {
      results.push({
        id: pageDef.id,
        name: pageDef.name,
        android_route: route,
        url: `xcagi://audit/nav/${route}`,
        status: 0,
        native: !!pageDef.native,
        android_capture: false,
        console_errors: [String(err)],
        screenshot_b64: '',
        error: String(err),
        analysis: [`Android 截图失败: ${err}`],
      })
    }
  }

  setModstoreBlocked(false)
  reinstallPersonalApk()

  finish({
    success: results.some((r) => r.screenshot_b64),
    lane: 'P-App',
    workflow_node: 'SA',
    label: laneCfg?.label,
    source: 'android-adb',
    device_count: devices.length,
    package: PACKAGE,
    fhd_host: FHD_HOST,
    page_count: results.length,
    sample: SAMPLE,
    max_pages: Number.isFinite(MAX_PAGES) ? MAX_PAGES : 0,
    pages: results,
    apk_installed: Boolean(apk),
  })
}

function finish(payload) {
  reinstallPersonalApk()
  const text = JSON.stringify(payload)
  if (OUT_PATH) {
    fs.mkdirSync(path.dirname(OUT_PATH), { recursive: true })
    fs.writeFileSync(OUT_PATH, text, 'utf8')
    process.stdout.write(
      JSON.stringify({
        success: payload.success,
        page_count: payload.page_count,
        source: payload.source,
        out: OUT_PATH,
      }),
    )
  } else {
    process.stdout.write(text)
  }
  process.exit(payload.success ? 0 : 1)
}

main().catch((err) => finish({ success: false, message: String(err), pages: [] }))
