import { ref, watch, onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useModsStore } from '@/stores/mods'

const hasLegacyProModeRuntime = () => {
  const legacyToggle = (window as any).__legacyToggleProMode || (window as any).toggleProMode
  return typeof legacyToggle === 'function'
}

const readProModeStateFromDom = () => {
  const overlay = document.getElementById('proModeOverlay')
  if (!overlay && typeof (window as any).__XCAGI_IS_PRO_MODE === 'boolean') {
    return !!(window as any).__XCAGI_IS_PRO_MODE
  }
  const bodyActive = document.body.classList.contains('pro-mode-active')
  const overlayActive = !!overlay?.classList.contains('active')
  const overlayVisible = !!overlay && overlay.style.display !== 'none'
  return bodyActive || (overlayActive && overlayVisible)
}

const syncProModeStateSoon = (isProMode: ReturnType<typeof ref<boolean>>) => {
  requestAnimationFrame(() => {
    isProMode.value = readProModeStateFromDom()
  })
  setTimeout(() => {
    isProMode.value = readProModeStateFromDom()
  }, 350)
}

const resolveModProEntryPath = () => {
  const modsStore = useModsStore()
  const mods = Array.isArray(modsStore.modsForUi) ? modsStore.modsForUi : []
  for (const mod of mods) {
    const frontend = mod?.frontend && typeof mod.frontend === 'object' ? mod.frontend : {}
    const explicit = typeof frontend.pro_entry_path === 'string' ? frontend.pro_entry_path.trim() : ''
    if (explicit) return explicit
    const menu = Array.isArray(mod?.menu) ? mod.menu : []
    const firstPath = typeof menu[0]?.path === 'string' ? menu[0].path.trim() : ''
    if (firstPath) return firstPath
  }
  return ''
}

export function useAppProMode() {
  const route = useRoute()
  const router = useRouter()
  const modsStore = useModsStore()
  const isProMode = ref(false)

  const syncGlobalProMode = () => {
    const active = !!isProMode.value
    ;(window as any).__XCAGI_IS_PRO_MODE = active
    window.dispatchEvent(new CustomEvent('xcagi:pro-mode-changed', {
      detail: { isProMode: active }
    }))
  }

  const enterModProMode = async () => {
    if (!Array.isArray(modsStore.modsForUi) || modsStore.modsForUi.length === 0) {
      try {
        await modsStore.initialize()
      } catch (error) {
        console.warn('加载 Mod 菜单失败，无法解析专业版入口:', error)
      }
    }
    const targetPath = resolveModProEntryPath()
    isProMode.value = true
    if (targetPath && route.path !== targetPath) {
      await router.push(targetPath).catch((error) => {
        console.warn('跳转 Mod 专业版入口失败:', error)
      })
    }
  }

  const exitModProMode = async () => {
    isProMode.value = false
    if (route.name !== 'chat') {
      await router.push({ name: 'chat' }).catch(() => undefined)
    }
  }

  const handleToggleProMode = () => {
    const legacyToggle = (window as any).__legacyToggleProMode || (window as any).toggleProMode
    if (!resolveModProEntryPath() && typeof legacyToggle === 'function') {
      legacyToggle()
      syncProModeStateSoon(isProMode)
      return
    }
    if (isProMode.value) {
      void exitModProMode()
    } else {
      void enterModProMode()
    }
  }

  let proModeObserver: MutationObserver | null = null
  let onToggleProModeEvent: (() => void) | null = null

  onMounted(() => {
    const syncProModeFromDom = () => {
      isProMode.value = readProModeStateFromDom()
    }

    ;(window as any).setProModeEnabled = (enabled: boolean) => {
      const shouldEnable = !!enabled
      const active = isProMode.value || readProModeStateFromDom()
      if (shouldEnable === active) {
        isProMode.value = active
        return
      }
      if (!resolveModProEntryPath() && hasLegacyProModeRuntime()) {
        const legacyToggle = (window as any).__legacyToggleProMode || (window as any).toggleProMode
        legacyToggle()
        syncProModeStateSoon(isProMode)
      } else if (shouldEnable) {
        void enterModProMode()
      } else {
        void exitModProMode()
      }
    }

    onToggleProModeEvent = () => {
      handleToggleProMode()
    }

    window.addEventListener('xcagi:toggle-pro-mode', onToggleProModeEvent)

    if (hasLegacyProModeRuntime()) {
      let scheduled = false
      const scheduleSync = () => {
        if (scheduled) return
        scheduled = true
        requestAnimationFrame(() => {
          scheduled = false
          syncProModeFromDom()
        })
      }
      proModeObserver = new MutationObserver(() => {
        scheduleSync()
      })
      proModeObserver.observe(document.body, { attributes: true, attributeFilter: ['class'] })
      const overlay = document.getElementById('proModeOverlay')
      if (overlay) {
        proModeObserver.observe(overlay, { attributes: true, attributeFilter: ['class', 'style'] })
      }
    }
    syncProModeFromDom()
    syncGlobalProMode()
  })

  watch(isProMode, () => {
    syncGlobalProMode()
  })

  onBeforeUnmount(() => {
    if (proModeObserver) {
      proModeObserver.disconnect()
      proModeObserver = null
    }
    if (onToggleProModeEvent) {
      window.removeEventListener('xcagi:toggle-pro-mode', onToggleProModeEvent)
      onToggleProModeEvent = null
    }
    if ((window as any).setProModeEnabled) {
      delete (window as any).setProModeEnabled
    }
    if (typeof (window as any).__XCAGI_IS_PRO_MODE !== 'undefined') {
      delete (window as any).__XCAGI_IS_PRO_MODE
    }
  })

  return {
    isProMode,
    handleToggleProMode,
  }
}
