// 拆分自 App.vue：会话条目滑动删除手势（触摸 + 鼠标，逻辑逐字迁移，行为不变）。
import { reactive, ref } from 'vue'

const DELETE_BTN_WIDTH = 56

export function useConversationSwipe() {
  const convSwipeOffset = reactive<Record<string, number>>({})
  const convTouchStartX = reactive<Record<string, number>>({})
  const convMouseDragging = ref(false)
  const convMouseStartX = ref(0)
  const convMouseId = ref('')
  const convJustSwiped = ref(false)

  function onConvTouchStart(e: TouchEvent, id: string) {
    convTouchStartX[id] = e.touches[0].clientX
  }

  function onConvTouchMove(e: TouchEvent, id: string) {
    const startX = convTouchStartX[id] ?? 0
    const dx = startX - e.touches[0].clientX
    convSwipeOffset[id] = Math.max(0, Math.min(dx, DELETE_BTN_WIDTH))
  }

  function onConvTouchEnd(id: string) {
    const offset = convSwipeOffset[id] ?? 0
    if (offset < DELETE_BTN_WIDTH / 2) {
      convSwipeOffset[id] = 0
    } else {
      convSwipeOffset[id] = DELETE_BTN_WIDTH
      convJustSwiped.value = true
    }
    delete convTouchStartX[id]
  }

  function onConvMouseDown(e: MouseEvent, id: string) {
    convMouseDragging.value = true
    convMouseStartX.value = e.clientX
    convMouseId.value = id
  }

  function onConvMouseMove(e: MouseEvent) {
    if (!convMouseDragging.value) return
    const dx = convMouseStartX.value - e.clientX
    convSwipeOffset[convMouseId.value] = Math.max(0, Math.min(dx, DELETE_BTN_WIDTH))
  }

  function onConvMouseUp() {
    if (!convMouseDragging.value) return
    const id = convMouseId.value
    const offset = convSwipeOffset[id] ?? 0
    if (offset < DELETE_BTN_WIDTH / 2) {
      convSwipeOffset[id] = 0
    } else {
      convSwipeOffset[id] = DELETE_BTN_WIDTH
      convJustSwiped.value = true
    }
    convMouseDragging.value = false
  }

  return {
    convSwipeOffset,
    convJustSwiped,
    onConvTouchStart,
    onConvTouchMove,
    onConvTouchEnd,
    onConvMouseDown,
    onConvMouseMove,
    onConvMouseUp,
  }
}
