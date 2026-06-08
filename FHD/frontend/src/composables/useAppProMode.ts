import { ref, watch } from 'vue'
import type { Router, RouteLocationNormalizedLoaded } from 'vue-router'
import type { useModsStore } from '@/stores/mods'
import {
  isClientModeTiersUiEnabled,
  resetClientModeTierLocalState,
} from '@/constants/clientModeTiers'

export function useAppProMode(
  modsStore: ReturnType<typeof useModsStore>,
  router: Router,
  route: RouteLocationNormalizedLoaded
) {
  const isProMode = ref(false)
  let proModeObserver: MutationObserver | null = null

  function hasLegacyProModeRuntime() {
    const w = window as Window & { __legacyToggleProMode?: () => void; toggleProMode?: () => void }
    const legacyToggle = w.__legacyToggleProMode || w.toggleProMode
    return typeof legacyToggle === 'function'
  }

  function readProModeStateFromDom() {
    const overlay = document.getElementById('proModeOverlay')
    const w = window as Window & { __XCAGI_IS_PRO_MODE?: boolean }
    if (!overlay && typeof w.__XCAGI_IS_PRO_MODE === 'boolean') {
      return !!w.__XCAGI_IS_PRO_MODE
    }
    const bodyActive = document.body.classList.contains('pro-mode-active')
    const overlayActive = !!overlay?.classList.contains('active')
    const overlayVisible = !!overlay && overlay.style.display !== 'none'
    return bodyActive || (overlayActive && overlayVisible)
  }

  function syncProModeStateSoon() {
    requestAnimationFrame(() => {
      isProMode.value = readProModeStateFromDom()
    })
    setTimeout(() => {
      isProMode.value = readProModeStateFromDom()
    }, 350)
  }

  function resolveModProEntryPath() {
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

  async function enterModProMode() {
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

  async function exitModProMode() {
    isProMode.value = false
    if (route.name !== 'chat') {
      await router.push({ name: 'chat' }).catch(() => undefined)
    }
  }

  function handleToggleProMode() {
    if (!isClientModeTiersUiEnabled()) return
    const w = window as Window & { __legacyToggleProMode?: () => void; toggleProMode?: () => void }
    const legacyToggle = w.__legacyToggleProMode || w.toggleProMode
    if (!resolveModProEntryPath() && typeof legacyToggle === 'function') {
      legacyToggle()
      syncProModeStateSoon()
      return
    }
    if (isProMode.value) {
      void exitModProMode()
    } else {
      void enterModProMode()
    }
  }

  function syncGlobalProMode() {
    const active = !!isProMode.value
    const w = window as Window & { __XCAGI_IS_PRO_MODE?: boolean }
    w.__XCAGI_IS_PRO_MODE = active
    window.dispatchEvent(
      new CustomEvent('xcagi:pro-mode-changed', {
        detail: { isProMode: active },
      })
    )
  }

  function installLegacyDomObserver() {
    if (!hasLegacyProModeRuntime()) return
    let scheduled = false
    const scheduleSync = () => {
      if (scheduled) return
      scheduled = true
      requestAnimationFrame(() => {
        scheduled = false
        isProMode.value = readProModeStateFromDom()
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

  function uninstallLegacyDomObserver() {
    if (proModeObserver) {
      proModeObserver.disconnect()
      proModeObserver = null
    }
  }

  function enforceClientNormalModeBaseline() {
    if (isClientModeTiersUiEnabled()) return
    resetClientModeTierLocalState()
    const legacyActive = readProModeStateFromDom()
    if (legacyActive) {
      const w = window as Window & { __legacyToggleProMode?: () => void; toggleProMode?: () => void }
      const legacyToggle = w.__legacyToggleProMode || w.toggleProMode
      if (typeof legacyToggle === 'function') {
        legacyToggle()
      }
    }
    isProMode.value = false
    void exitModProMode()
    syncGlobalProMode()
  }

  watch(isProMode, () => {
    syncGlobalProMode()
  })

  return {
    isProMode,
    hasLegacyProModeRuntime,
    readProModeStateFromDom,
    syncProModeStateSoon,
    resolveModProEntryPath,
    enterModProMode,
    exitModProMode,
    handleToggleProMode,
    enforceClientNormalModeBaseline,
    syncGlobalProMode,
    installLegacyDomObserver,
    uninstallLegacyDomObserver,
  }
}
