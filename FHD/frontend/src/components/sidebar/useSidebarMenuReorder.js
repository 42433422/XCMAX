/**
 * 侧栏菜单拖拽排序（拆分自 components/Sidebar.vue，行为保持一致）：
 * 右键长按进入拖拽、命中缓存、RAF 节流移动、pointerup 落位。
 */
import { computed, ref, watch } from 'vue'

export function useSidebarMenuReorder({ sidebarLayoutStore, menuItems, sidebarMenuRef }) {
  const LONG_PRESS_MS = 1000
  const pressingKey = ref('')
  const draggingKey = ref('')
  const dragOverKey = ref('')
  let activeReorderPointerId = null
  let pressTimer = null
  let boundWindowPointerMove = null
  let boundWindowPointerUp = null
  let boundWindowPointerCancel = null
  let dragMoveRaf = 0
  let pendingDragPoint = null
  /** @type {{ key: string, midY: number }[]} */
  let menuHitCache = []

  const displayMenuItems = computed(() => {
    const items = menuItems.value
    const drag = draggingKey.value
    const over = dragOverKey.value
    if (!drag || !over || drag === over) return items
    const keys = items.map((m) => m.key)
    const from = keys.indexOf(drag)
    const to = keys.indexOf(over)
    if (from < 0 || to < 0) return items
    const nextKeys = [...keys]
    const [lifted] = nextKeys.splice(from, 1)
    nextKeys.splice(to, 0, lifted)
    const byKey = new Map(items.map((m) => [m.key, m]))
    return nextKeys.map((k) => byKey.get(k)).filter(Boolean)
  })

  function clearPressTimer() {
    if (pressTimer) {
      window.clearTimeout(pressTimer)
      pressTimer = null
    }
  }

  function refreshMenuHitCache() {
    const root = sidebarMenuRef.value
    if (!root) {
      menuHitCache = []
      return
    }
    menuHitCache = Array.from(root.querySelectorAll('button.menu-item[data-view]'))
      .filter((btn) => btn.getAttribute('data-view') !== draggingKey.value)
      .map((btn) => {
        const rect = btn.getBoundingClientRect()
        return {
          key: String(btn.getAttribute('data-view') || ''),
          midY: rect.top + rect.height / 2,
        }
      })
  }

  function menuKeyUnderPoint(clientX, clientY) {
    const root = sidebarMenuRef.value
    if (!root) return ''
    const rect = root.getBoundingClientRect()
    if (clientX < rect.left || clientX > rect.right || clientY < rect.top || clientY > rect.bottom) {
      return ''
    }
    if (!menuHitCache.length) refreshMenuHitCache()
    let nearestKey = ''
    let nearestDistance = Number.POSITIVE_INFINITY
    for (const entry of menuHitCache) {
      const distance = Math.abs(entry.midY - clientY)
      if (distance < nearestDistance) {
        nearestDistance = distance
        nearestKey = entry.key
      }
    }
    return nearestKey
  }

  function clearDragMoveRaf() {
    if (dragMoveRaf) {
      window.cancelAnimationFrame(dragMoveRaf)
      dragMoveRaf = 0
    }
    pendingDragPoint = null
  }

  function detachReorderWindowListeners() {
    if (boundWindowPointerMove) {
      window.removeEventListener('pointermove', boundWindowPointerMove, true)
      boundWindowPointerMove = null
    }
    if (boundWindowPointerUp) {
      window.removeEventListener('pointerup', boundWindowPointerUp, true)
      boundWindowPointerUp = null
    }
    if (boundWindowPointerCancel) {
      window.removeEventListener('pointercancel', boundWindowPointerCancel, true)
      boundWindowPointerCancel = null
    }
  }

  function clearReorderGesture() {
    clearPressTimer()
    pressingKey.value = ''
    draggingKey.value = ''
    dragOverKey.value = ''
    activeReorderPointerId = null
    menuHitCache = []
    clearDragMoveRaf()
    detachReorderWindowListeners()
  }

  function flushDragMove() {
    dragMoveRaf = 0
    if (!pendingDragPoint || !draggingKey.value) {
      pendingDragPoint = null
      return
    }
    const { x, y } = pendingDragPoint
    pendingDragPoint = null
    const key = menuKeyUnderPoint(x, y)
    if (key && key !== dragOverKey.value) {
      dragOverKey.value = key
      refreshMenuHitCache()
    }
  }

  function onWindowPointerMove(event) {
    if (activeReorderPointerId !== null && event.pointerId !== activeReorderPointerId) return
    if (!draggingKey.value) return
    pendingDragPoint = { x: event.clientX, y: event.clientY }
    if (!dragMoveRaf) {
      dragMoveRaf = window.requestAnimationFrame(flushDragMove)
    }
  }

  function onWindowPointerUp(event) {
    if (activeReorderPointerId !== null && event.pointerId !== activeReorderPointerId) return
    if (draggingKey.value) {
      const from = draggingKey.value
      const to = dragOverKey.value
      if (to && to !== from) {
        sidebarLayoutStore.moveItem(
          from,
          to,
          menuItems.value.map((m) => m.key),
        )
      }
    }
    clearReorderGesture()
  }

  function attachReorderWindowListeners() {
    detachReorderWindowListeners()
    boundWindowPointerMove = onWindowPointerMove
    boundWindowPointerUp = onWindowPointerUp
    boundWindowPointerCancel = clearReorderGesture
    window.addEventListener('pointermove', boundWindowPointerMove, true)
    window.addEventListener('pointerup', boundWindowPointerUp, true)
    window.addEventListener('pointercancel', boundWindowPointerCancel, true)
  }

  function onReorderPointerDown(event, key) {
    if (!sidebarLayoutStore.reorderEnabled) return
    if (event.button !== 2) return
    event.preventDefault()
    clearReorderGesture()
    activeReorderPointerId = event.pointerId
    pressingKey.value = key
    attachReorderWindowListeners()
    pressTimer = window.setTimeout(() => {
      if (activeReorderPointerId !== event.pointerId || pressingKey.value !== key) return
      pressingKey.value = ''
      draggingKey.value = key
      dragOverKey.value = key
      refreshMenuHitCache()
    }, LONG_PRESS_MS)
  }

  watch(draggingKey, (key) => {
    if (key) {
      window.requestAnimationFrame(() => refreshMenuHitCache())
    } else {
      menuHitCache = []
    }
  })

  return {
    LONG_PRESS_MS,
    pressingKey,
    draggingKey,
    dragOverKey,
    displayMenuItems,
    onReorderPointerDown,
    clearReorderGesture,
  }
}
