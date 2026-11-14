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
  const deviceId = readDeviceId()
  if (!deviceId || deviceId === 'desktop-unknown') return
  try {
    await fetch('/api/mobile/v1/devices/desktop/heartbeat', {
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
  } catch {
    // 心跳失败不阻塞界面，下一次 tick 重试。
  }
}

export function installDesktopDeviceHeartbeat(): void {
  if (typeof window === 'undefined') return
  void sendHeartbeat()
  window.setInterval(() => void sendHeartbeat(), HEARTBEAT_INTERVAL_MS)
}
