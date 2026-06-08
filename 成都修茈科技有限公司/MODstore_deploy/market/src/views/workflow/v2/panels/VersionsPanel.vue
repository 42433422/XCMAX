<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../../../../api'

const props = defineProps<{
  workflowId: number
  open: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'rolled-back', versionNo: number): void
}>()

interface VersionRow {
  id: number
  version_no: number
  note: string
  is_current: boolean
  created_at: string
}

const rows = ref<VersionRow[]>([])
const loading = ref(false)
const errMsg = ref('')

async function refresh() {
  loading.value = true
  errMsg.value = ''
  try {
    const list: any = await api.listWorkflowVersions(props.workflowId)
    rows.value = Array.isArray(list) ? list : []
  } catch (e: any) {
    errMsg.value = e?.detail || e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(refresh)

async function rollback(row: VersionRow) {
  if (row.is_current) return
  if (!confirm(`确认回滚到 v${row.version_no}？\n\n该操作会用此版本快照覆盖当前画布的节点与连线，触发器不变。`)) return
  try {
    await api.rollbackWorkflowVersion(props.workflowId, row.id)
    await refresh()
    emit('rolled-back', row.version_no)
  } catch (e: any) {
    errMsg.value = e?.detail || e?.message || '回滚失败'
  }
}

function formatTime(iso: string): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return d.toLocaleString()
  } catch {
    return iso
  }
}

defineExpose({ refresh })
</script>

<template>
  <transition name="vp-fade">
    <aside v-if="open" class="vp">
      <header class="vp__head">
        <h3>版本历史</h3>
        <button class="vp__btn" type="button" @click="emit('close')">关闭</button>
      </header>
      <div class="vp__body">
        <p v-if="loading" class="vp__hint">
          <span class="vp__spinner" />
          加载中…
        </p>
        <p v-else-if="errMsg" class="vp__err">{{ errMsg }}</p>
        <p v-else-if="!rows.length" class="vp__hint">还没有发布过版本，点击顶栏「发布版本」开始记录历史。</p>

        <ul v-else class="vp__list">
          <li
            v-for="(r, idx) in rows"
            :key="r.id"
            class="vp__item"
            :class="{ 'vp__item--current': r.is_current }"
          >
            <div class="vp__timeline">
              <span class="vp__dot" :class="{ 'vp__dot--current': r.is_current }" />
              <span v-if="idx < rows.length - 1" class="vp__line" />
            </div>
            <div class="vp__content">
              <div class="vp__row">
                <span class="vp__no">v{{ r.version_no }}</span>
                <span v-if="r.is_current" class="vp__chip">当前</span>
                <span class="vp__time">{{ formatTime(r.created_at) }}</span>
              </div>
              <p v-if="r.note" class="vp__note">{{ r.note }}</p>
              <p v-else class="vp__note vp__note--empty">无备注</p>
              <div class="vp__actions">
                <button
                  class="vp__btn"
                  type="button"
                  :disabled="r.is_current"
                  @click="rollback(r)"
                >
                  {{ r.is_current ? '当前版本' : '回滚到此' }}
                </button>
              </div>
            </div>
          </li>
        </ul>
      </div>
    </aside>
  </transition>
</template>

<style scoped>
.vp {
  position: absolute;
  right: 16px;
  top: 68px;
  width: 360px;
  max-height: calc(100vh - 90px);
  background: rgba(15, 23, 42, 0.92);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(148, 163, 184, 0.1);
  border-radius: 14px;
  box-shadow: 0 24px 48px -12px rgba(0, 0, 0, 0.5);
  z-index: 25;
  display: flex;
  flex-direction: column;
}

.vp__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.08);
}

.vp__head h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: #f1f5f9;
}

.vp__body {
  padding: 8px 0;
  overflow-y: auto;
}

.vp__hint,
.vp__err {
  padding: 20px;
  margin: 0;
  color: #64748b;
  font-size: 13px;
  text-align: center;
}

.vp__err {
  color: #f87171;
}

.vp__spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(148, 163, 184, 0.2);
  border-top-color: #94a3b8;
  border-radius: 50%;
  animation: vp-spin 0.8s linear infinite;
  margin-right: 6px;
  vertical-align: middle;
}

@keyframes vp-spin {
  to {
    transform: rotate(360deg);
  }
}

.vp__list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.vp__item {
  display: flex;
  gap: 12px;
  padding: 12px 18px;
  position: relative;
}

.vp__item--current {
  background: rgba(34, 197, 94, 0.05);
}

.vp__timeline {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex-shrink: 0;
  width: 16px;
  position: relative;
}

.vp__dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: rgba(148, 163, 184, 0.3);
  border: 2px solid rgba(15, 23, 42, 0.92);
  flex-shrink: 0;
  margin-top: 4px;
}

.vp__dot--current {
  background: #22c55e;
  box-shadow: 0 0 10px rgba(34, 197, 94, 0.4);
}

.vp__line {
  width: 2px;
  flex: 1;
  background: rgba(148, 163, 184, 0.1);
  margin-top: 4px;
  min-height: 20px;
}

.vp__content {
  flex: 1;
  min-width: 0;
}

.vp__row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.vp__no {
  font-weight: 700;
  color: #f1f5f9;
  font-size: 14px;
}

.vp__chip {
  font-size: 10px;
  font-weight: 700;
  background: rgba(34, 197, 94, 0.15);
  color: #4ade80;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid rgba(34, 197, 94, 0.2);
}

.vp__time {
  margin-left: auto;
  font-size: 11px;
  color: #475569;
}

.vp__note {
  margin: 6px 0 8px;
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.5;
  white-space: pre-wrap;
}

.vp__note--empty {
  color: #475569;
  font-style: italic;
}

.vp__actions {
  display: flex;
  justify-content: flex-end;
}

.vp__btn {
  font-size: 12px;
  font-weight: 500;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(30, 41, 59, 0.5);
  color: #cbd5e1;
  padding: 5px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.vp__btn:hover:not(:disabled) {
  background: rgba(148, 163, 184, 0.12);
  color: #f1f5f9;
}

.vp__btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.vp-fade-enter-active,
.vp-fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.vp-fade-enter-from,
.vp-fade-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
</style>
