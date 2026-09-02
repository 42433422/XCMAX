import { ref } from 'vue'
import { useResizablePane } from '@/composables/useResizablePane'
import { BRAIN_LAYOUT_MQ } from './brainStatic'

/** 观测面板宽度可拖拽调整（拆分自 BrainView.vue，逻辑不变） */
export function useBrainPane() {
  const isBrainPaneResizable = ref(true)
  let brainPaneViewportMedia = null

  const {
    paneStyle: brainPaneStyle,
    startResize: onBrainPaneResizeStart,
    resetSize: resetBrainPaneWidth,
    stopResize: stopBrainPaneResize,
  } = useResizablePane({
    paneKey: 'brain.obs-panel',
    cssVarName: '--brain-obs-width',
    orientation: 'vertical',
    invertDelta: true,
    defaultSize: 320,
    minSize: 260,
    maxSize: 480,
    enabled: () => isBrainPaneResizable.value,
  })

  function onBrainPaneViewportChange(event) {
    isBrainPaneResizable.value = !event.matches
    if (!isBrainPaneResizable.value) {
      stopBrainPaneResize()
    }
  }

  // 窄屏媒体查询监听（原 onMounted 挂载段，逐字迁移）
  function bindBrainPaneViewport() {
    brainPaneViewportMedia = window.matchMedia(BRAIN_LAYOUT_MQ)
    onBrainPaneViewportChange(brainPaneViewportMedia)
    if (typeof brainPaneViewportMedia.addEventListener === 'function') {
      brainPaneViewportMedia.addEventListener('change', onBrainPaneViewportChange)
    } else if (typeof brainPaneViewportMedia.addListener === 'function') {
      brainPaneViewportMedia.addListener(onBrainPaneViewportChange)
    }
  }

  // 原 onUnmounted 清理段，逐字迁移
  function unbindBrainPaneViewport() {
    stopBrainPaneResize()
    if (brainPaneViewportMedia) {
      if (typeof brainPaneViewportMedia.removeEventListener === 'function') {
        brainPaneViewportMedia.removeEventListener('change', onBrainPaneViewportChange)
      } else if (typeof brainPaneViewportMedia.removeListener === 'function') {
        brainPaneViewportMedia.removeListener(onBrainPaneViewportChange)
      }
    }
  }

  return {
    isBrainPaneResizable,
    brainPaneStyle,
    onBrainPaneResizeStart,
    resetBrainPaneWidth,
    bindBrainPaneViewport,
    unbindBrainPaneViewport,
  }
}
