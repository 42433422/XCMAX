<template>
  <div v-if="files.length" class="agent-artifact-downloads" aria-label="下载文件">
    <button
      v-for="file in files"
      :key="file.uri"
      type="button"
      class="btn btn-primary btn-sm"
      :disabled="Boolean(downloadingId)"
      @click.stop="download(file)"
    >{{ downloadingId === file.uri ? '正在下载…' : `下载 ${file.name}` }}</button>
    <p v-if="downloadError" role="alert">{{ downloadError }}</p>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import agentRunsApi from '@/api/agentRuns'
import { downloadBlob } from '@/utils'
import type { AgentArtifactDownload } from '@/utils/agentArtifactDownloads'
import { getAuthSessionEpoch } from '@/utils/authSessionCache'
import { readActiveModIdFromStorage } from '@/utils/chatStorageKeys'
import { productReadScopeKey } from '@/utils/productReadAccountScope'

const props = defineProps<{ files: AgentArtifactDownload[]; scope: string }>()
const downloadingId = ref('')
const downloadError = ref('')
let downloadEpoch = 0
function retireDownload(): void {
  downloadEpoch++
  downloadingId.value = ''
  downloadError.value = ''
}
const scopeKey = () => JSON.stringify([props.scope, props.files.map(file => file.uri),
  getAuthSessionEpoch(), productReadScopeKey(readActiveModIdFromStorage())])
watch(scopeKey, retireDownload, { flush: 'sync' })
onBeforeUnmount(retireDownload)

async function download(file: AgentArtifactDownload): Promise<void> {
  if (downloadingId.value || !props.files.includes(file)) return
  const requestedScope = scopeKey(), epoch = ++downloadEpoch
  const isCurrent = () => epoch === downloadEpoch && requestedScope === scopeKey()
  downloadingId.value = file.uri
  downloadError.value = ''
  try {
    const response = await agentRunsApi.downloadArtifact(file.run_id, file.artifact_id)
    if (!isCurrent()) return
    const blob = await response.blob()
    if (isCurrent()) downloadBlob(blob, file.name)
  } catch {
    if (isCurrent()) downloadError.value = '下载失败，请重试。'
  } finally {
    if (epoch === downloadEpoch) downloadingId.value = ''
  }
}
</script>
