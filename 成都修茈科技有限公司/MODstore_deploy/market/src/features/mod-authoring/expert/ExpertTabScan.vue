<script setup lang="ts">
import { useModAuthoringContext } from '../composables/useModAuthoringContext'

const { loadingSummary, refreshSummary, summary } = useModAuthoringContext()
</script>

<template>
  <section class="panel">
    <div class="panel-actions">
      <h2 class="panel-title panel-title--inline">路由</h2>
      <button type="button" class="btn" :disabled="loadingSummary" @click="refreshSummary">
        {{ loadingSummary ? '…' : '扫描' }}
      </button>
    </div>
    <div v-if="summary">
      <p class="small">
        <code v-if="summary.blueprint_file" class="mono">{{ summary.blueprint_file }}</code>
        <span v-else class="muted">无蓝图文件</span>
      </p>
      <p v-if="summary.validation_ok === false && summary.warnings?.length" class="warn-block">
        <span v-for="(w, i) in summary.warnings" :key="i">{{ w }}<br /></span>
      </p>
      <p v-else-if="summary.validation_ok" class="ok-line">无警告</p>
      <div v-if="summary.blueprint_routes?.length" class="table-wrap">
        <table class="routes-table">
          <thead>
            <tr>
              <th>方法</th>
              <th>路径</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, idx) in summary.blueprint_routes" :key="idx">
              <td class="mono">{{ (r.methods || []).join(', ') }}</td>
              <td class="mono">{{ r.path }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="muted small">无路由</p>
    </div>
  </section>
</template>
