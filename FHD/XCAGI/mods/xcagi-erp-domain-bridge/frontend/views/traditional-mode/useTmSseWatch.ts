import { ref } from 'vue'
import { buildFullApiUrl } from '@/api/core'

interface TmSseWatchDeps {
  /** 当前目录（决定 watch URL 与刷新范围） */
  getWatchPath: () => string
  /** 服务端报告文件变更后的刷新动作 */
  onFilesChanged: () => void
  /** 页面重新可见时恢复懒加载观察 */
  onPageVisible: () => void
  /** 页面隐藏时暂停懒加载观察 */
  onPageHidden: () => void
}

/** 目录监听：fetch 流式读取 SSE，断线指数退避重连，仅页面可见时保持连接 */
export function useTmSseWatch(deps: TmSseWatchDeps) {
  const changedFiles = ref(new Set<string>())

  let watchTimer: number | null = null
  let lastWatchData: Record<string, string> = {}
  let eventSource: AbortController | null = null
  let sseRetryCount = 0
  let sseStopped = false
  const SSE_MAX_RETRIES = 10

  function handleSSEMessage(data: any) {
    if (!data) return
    const changed = data.changed || []
    const snapshot = data.snapshot
    if (snapshot) {
      lastWatchData = snapshot
    }
    if (changed.length > 0) {
      const newChanged = new Set<string>()
      for (const fname of changed) {
        if (fname.startsWith('__deleted__:')) {
          newChanged.add(fname.replace('__deleted__:', ''))
        } else {
          newChanged.add(fname)
        }
      }
      changedFiles.value = newChanged
      deps.onFilesChanged()
    }
  }

  function startSSE() {
    stopSSE()
    sseRetryCount = 0
    sseStopped = false
    const url = buildFullApiUrl(`/api/traditional-mode/watch?path=${encodeURIComponent(deps.getWatchPath())}`)
    eventSource = { _url: url } as any
    ;(async () => {
      try {
        const res = await fetch(url, { credentials: 'include' })
        if (!res.ok || !res.body || sseStopped) return
        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        while (!sseStopped) {
          const { done, value } = await reader.read()
          if (done || sseStopped) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                sseRetryCount = 0
                handleSSEMessage(JSON.parse(line.slice(6)))
              } catch { /* ignore parse errors */ }
            }
          }
        }
        if (!sseStopped) reader.releaseLock()
      } catch (err: any) {
        if (sseStopped) return
      }
      if (!sseStopped && document.visibilityState === 'visible' && sseRetryCount < SSE_MAX_RETRIES) {
        sseRetryCount++
        const delay = Math.min(5000 * Math.pow(1.5, sseRetryCount - 1), 30000)
        setTimeout(() => { if (!sseStopped && document.visibilityState === 'visible' && !eventSource) startSSE() }, delay)
      }
    })()
  }

  function stopSSE() {
    sseStopped = true
    eventSource = null
  }

  /** 导航后重置监听（仅当已有连接时，与原行为一致） */
  function restartIfActive() {
    if (eventSource) {
      startSSE()
    }
  }

  function onVisibilityChange() {
    if (document.visibilityState === 'visible') {
      startSSE()
      deps.onPageVisible()
    } else {
      stopSSE()
      deps.onPageHidden()
    }
  }

  /** 刷新时仅清空变更标记；导航时才连同监听快照一起重置 */
  function clearChangedFiles() {
    changedFiles.value.clear()
  }

  function resetWatchState() {
    changedFiles.value.clear()
    lastWatchData = {}
  }

  function disposeSse() {
    stopSSE()
  }

  return { changedFiles, startSSE, restartIfActive, onVisibilityChange, clearChangedFiles, resetWatchState, disposeSse, watchTimer }
}
