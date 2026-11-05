<script setup lang="ts">
import { computed, ref } from 'vue'
import api from '@/api'

const props = withDefaults(defineProps<{ code?: string }>(), { code: 'LOGIN_CONNECTION' })
const checking = ref(false)
const result = ref('尚未检查连接')
const checkedAt = ref('未检查')
const copied = ref('')
// Only fixed categories and transport status are copied; no address, account, payload or raw error.
const diagnostic = computed(() => `故障编号：${/^[A-Z_]{1,40}$/.test(props.code) ? props.code : 'CONNECTION'}\n浏览器网络：${navigator.onLine === false ? '离线' : '在线（不代表服务可用）'}\n连接检查：${result.value}\n检查时间：${checkedAt.value}`)
async function checkConnection() {
  if (checking.value) return
  checking.value = true
  copied.value = ''
  try {
    await api.get('/api/health', { lite: true }, { timeoutMs: 5000 })
    result.value = '已连接应用服务；若原操作仍失败，请重试原操作或联系管理员。'
  } catch (error) {
    const status = Number((error as { status?: number })?.status)
    result.value = status === 401 || status === 403 ? '连接已到达服务，请返回登录后重试。' : '暂时无法连接。请检查网络；桌面用户可退出并重新打开应用，再重试。'
  } finally {
    checkedAt.value = new Date().toISOString()
    checking.value = false
  }
}
async function copyDiagnostic() {
  try {
    if (window.xcagiDesktop?.clipboardWriteText) {
      if (!(await window.xcagiDesktop.clipboardWriteText(diagnostic.value)).ok) throw new Error('copy failed')
    } else await navigator.clipboard.writeText(diagnostic.value)
    copied.value = '诊断信息已复制，可发给管理员。'
  } catch { copied.value = '无法自动复制，请展开诊断信息后手动复制。' }
}
</script>

<template>
  <section class="connection-recovery" aria-label="连接帮助" :aria-busy="checking">
    <p role="status">{{ checking ? '正在检查连接…' : result }}</p>
    <button type="button" :disabled="checking" @click="checkConnection">{{ checking ? '检查中…' : '检查连接' }}</button>
    <button type="button" @click="copyDiagnostic">复制诊断信息</button>
    <p v-if="copied" role="status">{{ copied }}</p>
    <details><summary>查看诊断信息</summary><pre>{{ diagnostic }}</pre></details>
  </section>
</template>

<style scoped>
.connection-recovery { margin-top: 16px; font-size: 13px; line-height: 1.6; }
.connection-recovery button { padding: 6px 10px; margin: 0 8px 8px 0; cursor: pointer; }
.connection-recovery pre { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
