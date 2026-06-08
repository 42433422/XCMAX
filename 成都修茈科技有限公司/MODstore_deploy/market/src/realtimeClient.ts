import { getAccessToken } from './infrastructure/storage/tokenStore'

type OnNotification = () => void

let socket: WebSocket | null = null
let retryTimer: ReturnType<typeof setTimeout> | null = null
let notifHandler: OnNotification | undefined
/** 指数退避；Nginx 未配置 WebSocket Upgrade 时会立刻断开，避免控制台每秒刷屏。 */
const RETRY_BASE_MS = 4_000
const RETRY_MAX_MS = 90_000
let reconnectAttempt = 0

/**
 * 建立到 ``/api/realtime/ws?token=`` 的长连接。需在已登录、且同源或反代将 ``/api`` 指到 FastAPI 时调用。
 * 新通知推送 JSON ``{ "type": "notification", ... }`` 时触发 onNotification（通常刷新未读数）。
 */
export function connectRealtime(onNotification?: OnNotification) {
  if (socket) {
    const old = socket
    socket = null
    old.onclose = null
    old.onerror = null
    old.onmessage = null
    try {
      old.close(1000, 'replaced')
    } catch {
      /* */
    }
  }
  if (retryTimer) {
    clearTimeout(retryTimer)
    retryTimer = null
  }
  notifHandler = onNotification
  const token = getAccessToken()
  if (!token) return
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const url = `${proto}://${window.location.host}/api/realtime/ws?token=${encodeURIComponent(token)}`
  let ws: WebSocket
  try {
    ws = new WebSocket(url)
  } catch {
    scheduleReconnect()
    return
  }
  socket = ws
  ws.onopen = () => {
    reconnectAttempt = 0
  }
  const pingId = window.setInterval(() => {
    if (socket === ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: 'ping', t: Date.now() }))
      } catch {
        /* */
      }
    } else {
      clearInterval(pingId)
    }
  }, 50_000)

  ws.onmessage = (ev) => {
    try {
      const data = JSON.parse(String(ev.data || '')) as { type?: string }
      if (data.type === 'notification' && notifHandler) {
        notifHandler()
      }
    } catch {
      /* */
    }
  }
  ws.onerror = () => {
    /* onclose 会重连 */
  }
  ws.onclose = () => {
    clearInterval(pingId)
    if (socket === ws) {
      socket = null
    }
    if (getAccessToken()) {
      scheduleReconnect()
    }
  }
}

function scheduleReconnect() {
  if (retryTimer) return
  reconnectAttempt += 1
  const delay = Math.min(RETRY_MAX_MS, RETRY_BASE_MS * 2 ** Math.min(reconnectAttempt, 6))
  retryTimer = setTimeout(() => {
    retryTimer = null
    if (!getAccessToken()) return
    if (notifHandler) {
      connectRealtime(notifHandler)
    } else {
      connectRealtime()
    }
  }, delay)
}

/** 登出时 clearHandler 应为 true。 */
export function disconnectRealtime(clearHandler = true) {
  reconnectAttempt = 0
  if (retryTimer) {
    clearTimeout(retryTimer)
    retryTimer = null
  }
  if (socket) {
    const old = socket
    socket = null
    old.onclose = null
    old.onerror = null
    old.onmessage = null
    try {
      old.close(1000, 'client')
    } catch {
      /* */
    }
  }
  if (clearHandler) {
    notifHandler = undefined
  }
}
