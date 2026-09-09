<template>
  <section v-if="files.length" class="artifact-downloads" aria-label="生成文件">
    <strong>生成文件</strong>
    <ul>
      <li v-for="artifact in files" :key="artifact.artifact_id">
        <div>
          <span class="artifact-name">{{ artifact.name || '导出文件' }}</span>
          <small>{{ fileSize(artifact) }} · {{ artifactExpired(artifact) ? '已过期，请重新生成' : '生成后 24 小时内可下载' }}</small>
          <small v-if="states[artifact.artifact_id]?.message" :role="states[artifact.artifact_id]?.failed ? 'alert' : 'status'">
            {{ states[artifact.artifact_id]?.message }}
          </small>
        </div>
        <button type="button" class="btn btn-secondary btn-sm" :disabled="states[artifact.artifact_id]?.busy || artifactExpired(artifact)" @click="download(artifact)">
          {{ states[artifact.artifact_id]?.busy ? '下载中…' : '下载' }}
        </button>
      </li>
    </ul>
  </section>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import type { AgentArtifact } from '@/api/agentRuns'
import { artifactExpired, downloadableArtifact, useAgentArtifactDownloads } from '@/composables/useAgentArtifactDownloads'

const props = defineProps<{ artifacts: AgentArtifact[] }>()
const files = computed(() => props.artifacts.filter(downloadableArtifact))
const { states, download, clear } = useAgentArtifactDownloads()
watch(() => JSON.stringify(files.value.map(file => [file.artifact_id, file.uri, file.metadata]).sort()), clear, { flush: 'sync' })
function fileSize(artifact: AgentArtifact): string {
  const size = artifact.metadata?.size
  if (typeof size !== 'number' || !Number.isFinite(size) || size < 0) return '大小未知'
  return size < 1024 * 1024 ? `${Math.ceil(size / 1024)} KB` : `${(size / 1024 / 1024).toFixed(1)} MB`
}
</script>

<style scoped>
.artifact-downloads { padding: 10px; border: 1px solid #dbe4ed; border-radius: 8px; background: #f8fafc; color: #334155; font-size: 12px; }
.artifact-downloads ul { margin: 7px 0 0; padding: 0; list-style: none; }
.artifact-downloads li { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 6px 0; }
.artifact-downloads li > div { min-width: 0; }
.artifact-name { display: block; overflow-wrap: anywhere; font-weight: 500; }
.artifact-downloads small { display: block; margin-top: 4px; color: #64748b; }
.artifact-downloads [role="alert"] { color: #b91c1c; }
.artifact-downloads button { flex-shrink: 0; }
</style>
