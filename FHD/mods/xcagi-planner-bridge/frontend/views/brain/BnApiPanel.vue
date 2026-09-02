<script setup>
import { defineProps } from 'vue'

// 拆分自 BrainView.vue 模板（原第 136–186 行）；模板逐字迁移，行为不变。
const props = defineProps({ tm: { type: Object, required: true } })

const {
  activeTab, openapiError, openapiLoading, apiFilter, filteredOperations, openapiTitle,
} = props.tm
</script>

<template>
          <div v-show="activeTab === 'api'" class="brain-panel card brain-card">
            <div class="card-header">Level 2 · 接口层（当前 OpenAPI）</div>
            <p class="muted">
              数据来自 <code class="brain-mono">GET /api/system/openapi</code>（与仅反代 <code class="brain-mono">/api</code> 的部署一致）。
            </p>
            <div v-if="openapiError" class="muted text-warn">{{ openapiError }}</div>
            <div v-else-if="openapiLoading" class="muted">加载 OpenAPI…</div>
            <template v-else>
              <div class="form-group brain-search">
                <label for="brain-api-filter">按 path 过滤</label>
                <input
                  id="brain-api-filter"
                  v-model="apiFilter"
                  type="search"
                  placeholder="例如 /api/system 或 chat"
                  class="brain-input-mono"
                  autocomplete="off"
                >
              </div>
              <p class="muted brain-count">
                共 <strong>{{ filteredOperations.length }}</strong> 条 operation（{{ openapiTitle }}）
              </p>
              <div class="brain-table-wrap">
                <table class="brain-table">
                  <thead>
                    <tr>
                      <th>Method</th>
                      <th>Path</th>
                      <th>Summary / operationId</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, idx) in filteredOperations" :key="idx">
                      <td>
                        <span class="brain-method-chip" :class="'brain-method-chip--' + row.method.toLowerCase()">
                          {{ row.method }}
                        </span>
                      </td>
                      <td><code class="brain-mono">{{ row.path }}</code></td>
                      <td>{{ row.summary }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>
            <p class="muted brain-future">
              规划中的代码编辑接口示例：<code class="brain-mono">POST /api/code-editor/analyze</code>、
              <code class="brain-mono">POST /api/code-editor/edit</code>、<code class="brain-mono">GET /api/code-editor/diff/{id}</code>、
              <code class="brain-mono">POST /api/code-editor/apply/{id}</code> — 实现后将出现在上表。
            </p>
          </div>
</template>

<style scoped src="./brain.css"></style>
