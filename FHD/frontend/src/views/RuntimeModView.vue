<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { apiFetch } from '@/utils/apiBase'
import { createRuntimeModSdk, loadRuntimeMod, type RuntimeModMetadata } from '@/utils/runtimeModSdk'

const props = defineProps<{ modId: string }>()
const element = ref<HTMLElement>()
const error = ref('')
const loading = ref(true)
const receiptStatus = ref('')
const route = useRoute()
const router = useRouter()
const account = useAccountProfileStore()
let generation = 0
let cleanup: (() => void) | undefined
let pending: AbortController | undefined

function dispose() {
  pending?.abort()
  pending = undefined
  try { cleanup?.() } finally {
    cleanup = undefined
    element.value?.replaceChildren()
  }
}

watch(() => [element.value, props.modId, route.fullPath, account.tenantId, account.localUserId, account.marketUserId], async () => {
  const current = ++generation
  dispose()
  if (!element.value) return
  loading.value = true
  error.value = ''
  receiptStatus.value = ''
  const controller = new AbortController()
  pending = controller
  try {
    const response = await apiFetch(`/api/mods/runtime/${encodeURIComponent(props.modId)}`, { signal: controller.signal })
    const body = await response.json()
    if (!response.ok || body.success !== true) throw new Error(typeof body.detail === 'string' ? body.detail : '无法验证当前扩展或账号权限')
    const metadata = body.data as RuntimeModMetadata
    if (metadata.mod_id !== props.modId) throw new Error('扩展身份与当前页面不一致')
    if (metadata.requires_restart) throw new Error('扩展已安装，请重启客户端后使用新版本')
    const module = await loadRuntimeMod(metadata)
    if (current !== generation || controller.signal.aborted || !element.value) return
    const mountPoint = document.createElement('div')
    element.value.replaceChildren(mountPoint)
    const unmount = await module.mount(mountPoint, createRuntimeModSdk(metadata, route, controller.signal, (path) => router.push(path)))
    if (typeof unmount !== 'function') throw new Error('扩展未提供页面清理接口')
    if (current !== generation || controller.signal.aborted) unmount()
    else {
      cleanup = unmount
      // The host owns the durable retry and actual business probe. Mount alone
      // never declares a delivery complete and receipt failures leave the UI usable.
      void apiFetch('/api/mod-store/receipts/retry', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}', signal: controller.signal })
        .then(async (reply) => {
          const receipt = await reply.json()
          if (current !== generation || controller.signal.aborted) return
          if (!reply.ok || receipt.success !== true || receipt.data?.pending > 0) receiptStatus.value = '交付验证待确认，可在交付页重试'
        })
        .catch(() => {
          if (current === generation && !controller.signal.aborted) receiptStatus.value = '交付回执暂未确认，可在交付页重试'
        })
    }
  } catch (cause) {
    if (current === generation && !controller.signal.aborted) {
      error.value = cause instanceof Error ? cause.message : '扩展加载失败'
      element.value?.replaceChildren()
    }
  } finally {
    if (current === generation) loading.value = false
  }
}, { flush: 'post', immediate: true })

onBeforeUnmount(() => { generation++; dispose() })
</script>

<template>
  <section class="runtime-mod-page">
    <p v-if="loading" role="status">正在验证并加载扩展…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="receiptStatus" role="status">{{ receiptStatus }}</p>
    <div ref="element" class="runtime-mod-content" />
  </section>
</template>

<style scoped>
.runtime-mod-page { min-height: 0; overflow: auto; flex: 1; padding: 24px; }
.runtime-mod-content { min-height: 0; }
</style>
