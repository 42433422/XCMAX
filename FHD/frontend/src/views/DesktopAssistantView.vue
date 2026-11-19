<template>
  <FloatingChatAssistant v-if="identity" v-show="!checking" :key="identity" ref="assistant" desktop-window />
  <div v-if="!identity || checking" class="desktop-assistant-placeholder">
    <div class="desktop-assistant-grip" aria-hidden="true"></div>
    <button type="button" :disabled="checking" title="打开 XCAGI 主窗口" aria-label="打开 XCAGI 主窗口" @click="openMain">
      <img :src="avatarUrl" alt="" draggable="false" width="44" height="44" />
      <span>小C助理</span>
    </button>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import FloatingChatAssistant from '@/components/FloatingChatAssistant.vue'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { LS_ENTERPRISE_SESSION_HINT } from '@/utils/authSessionCache'
import { isDurableChatScope } from '@/utils/chatSessionRestore'
import { resolveChatIdentity, resolveChatStorageScope } from '@/utils/chatStorageKeys'
import { publicAssetUrl } from '@/utils/publicAssetUrl'

const desktop = window.xcagiDesktopAssistant!
const profile = useAccountProfileStore()
const assistant = ref<InstanceType<typeof FloatingChatAssistant>>()
const checking = ref(true)
const identity = ref('')
const avatarUrl = publicAssetUrl('ai-butler-female-avatar-v1.png')
let refreshVersion = 0
let stopWatchingShow: (() => void) | undefined

function openMain() {
  void desktop.openMain().catch(() => undefined)
}

async function refresh() {
  const version = ++refreshVersion
  checking.value = true
  assistant.value?.resetDesktopPanel()
  try {
    await profile.refreshFromServer({ keepVisible: true })
    if (version !== refreshVersion) return
    const canChat = profile.workspaceReady && !profile.sessionCheckUnavailable && !profile.isAdminAccount
      && !profile.userRole.startsWith('tenant:') && isDurableChatScope(resolveChatStorageScope())
    identity.value = canChat ? resolveChatIdentity() : ''
    assistant.value?.resetDesktopPanel()
  } catch {
    if (version === refreshVersion) invalidateSession()
  } finally {
    if (version === refreshVersion) checking.value = false
  }
}

function invalidateSession() {
  refreshVersion++
  assistant.value?.resetDesktopPanel()
  identity.value = ''
  checking.value = false
  profile.clear(false)
}

function onStorage(event: StorageEvent) {
  if (event.storageArea !== localStorage) return
  if (event.key === null || (event.key === LS_ENTERPRISE_SESSION_HINT && event.newValue === null)) {
    invalidateSession()
  }
}

onMounted(() => {
  const onShow = () => { void refresh() }
  stopWatchingShow = desktop.onShow(onShow)
  window.addEventListener('storage', onStorage)
  window.addEventListener('xcagi:enterprise-session-invalid', invalidateSession)
  onShow()
})
onBeforeUnmount(() => {
  refreshVersion++
  stopWatchingShow?.()
  window.removeEventListener('storage', onStorage)
  window.removeEventListener('xcagi:enterprise-session-invalid', invalidateSession)
})
</script>

<style>
.desktop-assistant-window,
.desktop-assistant-window body { background: transparent; overflow: hidden; }
.desktop-assistant-window .startup-placeholder { display: none; }
.desktop-assistant-placeholder { position: fixed; inset: 0; display: grid; place-items: center; }
.desktop-assistant-placeholder button {
  margin-top: 8px; display: grid; justify-items: center; gap: 3px; padding: 0 6px;
  border: 0; border-radius: 8px; background: transparent; cursor: pointer;
  font-size: 13px; line-height: 16px; font-weight: 600; color: #1e3a8a;
  text-shadow: 0 1px 3px #fff;
}
.desktop-assistant-placeholder img { border: 2px solid white; border-radius: 50%; object-fit: cover; }
.desktop-assistant-grip { position: absolute; inset: 0 30px auto; height: 12px; -webkit-app-region: drag; }
.desktop-assistant-grip::after {
  content: ''; position: absolute; inset: 5px 12px auto; height: 3px; border-radius: 2px;
  background: #8797bd; box-shadow: 0 0 1px white;
}
</style>
