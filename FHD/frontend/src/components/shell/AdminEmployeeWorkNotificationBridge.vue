<script setup lang="ts">
import { onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  managementWorkApi,
  type ManagementWorkItem,
  type ManagementWorkStatus,
} from '@/api/managementWork'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'

const POLL_INTERVAL_MS = 5_000
const SNAPSHOT_STORAGE_KEY = 'xcagi.admin.employee-work.notification-snapshot.v1'
const ATTENTION_STATUSES = new Set<ManagementWorkStatus>([
  'waiting_decision',
  'delivered',
  'blocked',
  'failed',
])

type StatusSnapshot = Record<string, string>

const route = useRoute()
const router = useRouter()

let pollTimer: ReturnType<typeof setInterval> | null = null
let polling = false
let stopped = false
let previousSnapshot: StatusSnapshot | null = null

function loadSnapshot(): StatusSnapshot | null {
  try {
    const raw = localStorage.getItem(SNAPSHOT_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null
    return Object.fromEntries(
      Object.entries(parsed).filter(
        ([taskId, status]) => Boolean(taskId) && typeof status === 'string',
      ),
    ) as StatusSnapshot
  } catch {
    return null
  }
}

function saveSnapshot(snapshot: StatusSnapshot): void {
  try {
    localStorage.setItem(SNAPSHOT_STORAGE_KEY, JSON.stringify(snapshot))
  } catch {
    // 无痕窗口或存储配额异常不应中断全局轮询。
  }
}

function isPublicRoute(): boolean {
  return Boolean(route.meta?.publicAccess)
}

function itemSnapshot(items: ManagementWorkItem[]): StatusSnapshot {
  return Object.fromEntries(
    items.map((item) => [
      item.task_id,
      [item.status, item.owner_employee_id, item.current_stage || '', item.updated_at || ''].join('|'),
    ]),
  )
}

function notificationCopy(item: ManagementWorkItem): { title: string; body: string } | null {
  const employee = item.owner_employee_id || '管理端员工'
  const task = item.title || item.task_id
  const detail = (item.last_update || item.error || item.current_stage || '').trim()
  const suffix = detail ? `；${detail.slice(0, 120)}` : ''

  if (item.status === 'waiting_decision') {
    return {
      title: '员工等待你决策',
      body: `${employee}：${task}${suffix}`,
    }
  }
  if (item.status === 'delivered') {
    return {
      title: '员工已交付，等待验收',
      body: `${employee}：${task}${suffix}`,
    }
  }
  if (item.status === 'blocked') {
    return {
      title: '员工任务被阻塞',
      body: `${employee}：${task}${suffix}`,
    }
  }
  if (item.status === 'failed') {
    return {
      title: '员工任务执行失败',
      body: `${employee}：${task}${suffix}`,
    }
  }
  if (item.status === 'cancel_requested') {
    return {
      title: '员工任务正在安全停止',
      body: `${employee}：${task}${suffix}`,
    }
  }
  if (item.status === 'cancelled') {
    return {
      title: '员工任务已停止',
      body: `${employee}：${task}${suffix}`,
    }
  }
  if (item.status === 'assigned' && item.current_stage === 'reassigned') {
    return {
      title: '管理任务已改派',
      body: `${task} → ${employee}${suffix}`,
    }
  }
  return null
}

async function showBrowserNotification(
  item: ManagementWorkItem,
  title: string,
  body: string,
): Promise<void> {
  if (typeof Notification === 'undefined') return

  let permission = Notification.permission
  if (permission === 'default') {
    try {
      permission = await Notification.requestPermission()
    } catch {
      return
    }
  }
  if (permission !== 'granted') return

  try {
    const notification = new Notification(title, {
      body,
      tag: `xcagi-employee-work:${item.task_id}:${item.status}`,
    })
    notification.onclick = () => {
      window.focus()
      void router.push('/employee-inbox')
      notification.close()
    }
  } catch {
    // 某些内嵌 WebView 暴露 Notification 但不允许直接构造。
  }
}

async function notifyTransition(item: ManagementWorkItem): Promise<void> {
  const copy = notificationCopy(item)
  if (!copy) return

  if (window.xcagiDesktop?.showNotification) {
    try {
      await window.xcagiDesktop.showNotification(copy.title, copy.body)
      return
    } catch {
      // Electron 通知不可用时回退到浏览器原生通知。
    }
  }
  await showBrowserNotification(item, copy.title, copy.body)
}

async function updateBadge(count: number): Promise<void> {
  try {
    await window.xcagiDesktop?.setBadge?.(count)
  } catch {
    // badge 失败不影响任务通知和下一轮轮询。
  }
}

async function refresh(): Promise<void> {
  if (stopped || polling || !isAdminConsoleSpa()) return
  if (isPublicRoute()) {
    await updateBadge(0)
    return
  }

  polling = true
  try {
    const response = await managementWorkApi.list({ limit: 500 })
    if (stopped) return

    const items = Array.isArray(response.items) ? response.items : []
    const nextSnapshot = itemSnapshot(items)
    const oldSnapshot = previousSnapshot

    // 先持久化，再触发系统通知；即便通知实现抛错，下一轮也不会重复轰炸。
    previousSnapshot = nextSnapshot
    saveSnapshot(nextSnapshot)

    const attentionCount = items.filter((item) => ATTENTION_STATUSES.has(item.status)).length
    await updateBadge(attentionCount)

    // 第一次使用本功能只建立基线，避免把多年历史阻塞任务一次性全部弹出。
    if (oldSnapshot === null) return

    const transitions = items.filter((item) => {
      const fingerprint = nextSnapshot[item.task_id]
      return notificationCopy(item) !== null && oldSnapshot[item.task_id] !== fingerprint
    })
    await Promise.allSettled(transitions.map((item) => notifyTransition(item)))
  } catch {
    // 登录页、会话过期或后端短暂重启时静默保留旧快照和 badge，恢复后继续比较状态。
  } finally {
    polling = false
  }
}

onMounted(() => {
  if (!isAdminConsoleSpa()) return
  previousSnapshot = loadSnapshot()
  void refresh()
  // 管理任务不复用企业 IM WebSocket。短轮询只访问管理员专用代理，
  // 与手机端 management audience outbox 形成两条相互隔离的通知通道。
  pollTimer = setInterval(() => void refresh(), POLL_INTERVAL_MS)
})

watch(
  () => route.fullPath,
  () => {
    if (isAdminConsoleSpa()) void refresh()
  },
)

onUnmounted(() => {
  stopped = true
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
})
</script>

<template>
  <span v-if="false" aria-hidden="true" />
</template>
