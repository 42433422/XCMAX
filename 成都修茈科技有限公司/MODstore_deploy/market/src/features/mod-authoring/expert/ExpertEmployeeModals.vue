<script setup lang="ts">
import { useModAuthoringContext } from '../composables/useModAuthoringContext'

const {
  empPickOpen,
  empPickLoading,
  empPickError,
  empPickRows,
  empPickSaving,
  closeEmployeePickModal,
  goMyEmployees,
  confirmPickEmployee,
  empModalOpen,
  empScaffoldDone,
  empModalMode,
  empDraft,
  empScaffoldRouter,
  empModalError,
  empModalMergeHint,
  closeEmployeeModal,
  copyMergeHint,
  empModalSaving,
  submitEmployeeModal,
} = useModAuthoringContext()
</script>

<template>
  <div v-if="empPickOpen" class="modal-overlay" @click.self="closeEmployeePickModal">
    <div class="modal modal-wide" role="dialog" aria-labelledby="emp-pick-title">
      <h3 id="emp-pick-title" class="modal-title">选择员工包</h3>
      <p class="muted small">从 AI 市场、执行器目录或本地包目录添加到当前 Mod。</p>
      <p v-if="empPickError" class="flash flash-err small">{{ empPickError }}</p>
      <p v-if="empPickLoading" class="muted">加载列表…</p>
      <div v-else-if="!empPickRows.length" class="emp-pick-empty">
        <p>暂无可选员工包。请先到 AI 市场下载，或在工作台创建员工。</p>
        <button type="button" class="btn btn-sm" @click="goMyEmployees">打开员工工作台</button>
      </div>
      <ul v-else class="emp-pick-list">
        <li v-for="row in empPickRows" :key="row.pickKey">
          <button
            type="button"
            class="emp-pick-row"
            :disabled="empPickSaving"
            @click="() => void confirmPickEmployee(row)"
          >
            <span class="emp-pick-name">{{ row.name }}</span>
            <span class="emp-pick-meta muted">{{ row.id }} · {{ row.sourceLabel }}</span>
            <span v-if="row.version" class="emp-pick-meta muted">v{{ row.version }}</span>
          </button>
        </li>
      </ul>
      <div class="modal-actions">
        <button type="button" class="btn" :disabled="empPickSaving" @click="closeEmployeePickModal">取消</button>
      </div>
    </div>
  </div>

  <div v-if="empModalOpen" class="modal-overlay" @click.self="closeEmployeeModal">
    <div class="modal modal-wide" role="dialog" aria-labelledby="emp-modal-title">
      <h3 id="emp-modal-title" class="modal-title">
        {{ empModalMode === 'add' ? '添加员工名片' : '编辑员工名片' }}
      </h3>
      <p v-if="empModalError" class="flash flash-err small">{{ empModalError }}</p>
      <div class="form-grid">
        <div v-if="empModalMode === 'add'" class="form-group full-width">
          <label class="label">内部 ID</label>
          <input v-model="empDraft.id" class="input mono" type="text" maxlength="64" placeholder="小写字母开头" />
        </div>
        <div class="form-group full-width">
          <label class="label">显示名</label>
          <input v-model="empDraft.label" class="input" type="text" maxlength="200" />
        </div>
        <div class="form-group full-width">
          <label class="label">面板标题</label>
          <input v-model="empDraft.panel_title" class="input" type="text" maxlength="200" />
        </div>
        <div class="form-group full-width">
          <label class="label">面板摘要</label>
          <textarea v-model="empDraft.panel_summary" class="input textarea" rows="3" maxlength="8000" />
        </div>
        <label v-if="empModalMode === 'add' && !empScaffoldDone" class="checkbox-line full-width">
          <input v-model="empScaffoldRouter" type="checkbox" />
          <span>同时生成占位路由与 blueprints 骨架（推荐）</span>
        </label>
      </div>
      <div v-if="empModalMergeHint" class="merge-hint-block">
        <span class="merge-hint-label">合并说明</span>
        <pre class="merge-hint-pre">{{ empModalMergeHint }}</pre>
        <button type="button" class="btn btn-sm" @click="copyMergeHint">复制说明</button>
      </div>
      <div class="modal-actions">
        <button type="button" class="btn" :disabled="empModalSaving" @click="closeEmployeeModal">取消</button>
        <button
          type="button"
          class="btn btn-primary"
          :disabled="empModalSaving"
          @click="() => void submitEmployeeModal()"
        >
          {{ empModalSaving ? '保存中…' : empScaffoldDone ? '关闭' : '保存' }}
        </button>
      </div>
    </div>
  </div>
</template>
