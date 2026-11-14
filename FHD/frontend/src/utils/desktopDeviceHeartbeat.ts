import { hasKnownEnterpriseSession } from '@/utils/authSessionCache'

const DEVICE_ID_STORAGE_KEY = 'xcagi.desktop.device_id'
const HEARTBEAT_INTERVAL_MS = 60_000

function readDeviceId(): string {
  try {
    const existing = window.localStorage.getItem(DEVICE_ID_STORAGE_KEY)?.trim()
    if (existing) return existing
    const generated =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : `desktop-${Date.now().toString(36)}`
    window.localStorage.setItem(DEVICE_ID_STORAGE_KEY, generated)
    return generated
  } catch {
    return 'desktop-unknown'
  }
}

function platformLabel(): string {
  const platform = navigator.platform.toLowerCase()
  if (platform.includes('mac')) return 'macos'
  if (platform.includes('win')) return 'windows'
  if (platform.includes('linux')) return 'linux'
  return 'desktop'
}

async function sendHeartbeat(): Promise<void> {
  // 未登录时不上报设备心跳：登录页的 401 不是故障，静默跳过即可。
  if (!hasKnownEnterpriseSession()) return
  const deviceId = readDeviceId()
  if (!deviceId || deviceId === 'desktop-unknown') return
  try {
    const response = await fetch('/api/mobile/v1/devices/desktop/heartbeat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        device_id: deviceId,
        label: navigator.userAgent.includes('Electron') ? 'XCAGI 桌面端' : 'XCAGI Web',
        platform: platformLabel(),
        app_version: '',
        capabilities: {},
      }),
    })
    // 401/403 说明当前没有有效会话（例如刚退出登录），不算服务异常。
    if (!response.ok && response.status !== 401 && response.status !== 403) {
      console.warn('[heartbeat] 设备心跳失败:', response.status)
    }
  } catch (error) {
    // 真正的服务异常保留日志；下一次 tick 仍会重试。
    console.warn('[heartbeat] 设备心跳未送达:', error instanceof Error ? error.message : error)
  }
}

export function installDesktopDeviceHeartbeat(): void {
  if (typeof window === 'undefined') return
  void sendHeartbeat()
  window.setInterval(() => void sendHeartbeat(), HEARTBEAT_INTERVAL_MS)
}
