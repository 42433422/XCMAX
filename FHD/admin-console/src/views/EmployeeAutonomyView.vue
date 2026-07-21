<template>
  <div class="employee-autonomy-view" id="view-employee-autonomy">
    <div class="page-header">
      <div>
        <h2>员工自治</h2>
        <p>建议看板 · 问答 · 成绩单 · 批量审批</p>
      </div>
      <div class="header-actions">
        <button class="btn btn-secondary" type="button" :disabled="loading" @click="refresh">
          {{ loading ? '刷新中…' : '刷新' }}
        </button>
        <button class="btn btn-primary" type="button" :disabled="!selectedIds.length || acting" @click="batchApprove">
          批量通过 ({{ selectedIds.length }})
        </button>
      </div>
    </div>
    <p v-if="error" class="banner-error">{{ error }}</p>

    <nav class="tabs">
      <button type="button" :class="{ active: tab === 'suggestions' }" @click="tab = 'suggestions'">建议看板</button>
      <button type="button" :class="{ active: tab === 'questions' }" @click="tab = 'questions'">问答</button>
      <button type="button" :class="{ active: tab === 'scorecard' }" @click="tab = 'scorecard'">成绩单</button>
    </nav>

    <section v-show="tab === 'suggestions'" class="card">
      <table v-if="suggestions.length" class="data-table">
        <thead>
          <tr>
            <th></th>
            <th>员工</th>
            <th>建议</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in suggestions" :key="String(row.id)">
            <td>
              <input v-model="selectedIds" type="checkbox" :value="row.id" />
            </td>
            <td>{{ row.employee_id || row.employee || '—' }}</td>
            <td>{{ row.title || row.summary || row.suggestion || '—' }}</td>
            <td>{{ row.status || 'pending' }}</td>
            <td class="ops">
              <button type="button" class="link" @click="approveOne(row.id)">通过</button>
              <button type="button" class="link danger" @click="rejectOne(row.id)">拒绝</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">暂无建议</div>
    </section>

    <section v-show="tab === 'questions'" class="card">
      <div v-for="q in questions" :key="String(q.id)" class="qa-item">
        <div class="qa-q">{{ q.question || q.content || q.title }}</div>
        <div class="qa-meta">{{ q.employee_id || '—' }} · {{ q.created_at || '' }}</div>
        <div class="qa-answer">
          <input v-model="answers[String(q.id)]" type="text" placeholder="输入答复" />
          <button type="button" class="btn btn-primary" @click="answerOne(q.id)">提交</button>
        </div>
      </div>
      <div v-if="!questions.length" class="empty">暂无待答问题</div>
    </section>

    <section v-show="tab === 'scorecard'" class="card">
      <table v-if="scorecard.length" class="data-table">
        <thead>
          <tr>
            <th>员工</th>
            <th>任务数</th>
            <th>成功率</th>
            <th>最近活跃</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, idx) in scorecard" :key="String(row.employee_id || idx)">
            <td>{{ row.employee_id || row.name || '—' }}</td>
            <td>{{ row.total_tasks ?? row.task_count ?? '—' }}</td>
            <td>{{ formatRate(row.success_rate) }}</td>
            <td>{{ row.last_active_at || row.updated_at || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">暂无成绩单数据</div>
    </section>
  </div>
</template>

<script lang="ts">
export default { name: 'EmployeeAutonomyView' }
</script>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { xcmaxEmployeeAutonomyApi } from '@/api/xcmaxEmployeeAutonomy'
import { appAlert, appPrompt } from '@/utils/appDialog'

type Row = Record<string, any>

const tab = ref<'suggestions' | 'questions' | 'scorecard'>('suggestions')
const loading = ref(false)
const acting = ref(false)
const error = ref('')
const suggestions = ref<Row[]>([])
const questions = ref<Row[]>([])
const scorecard = ref<Row[]>([])
const selectedIds = ref<Array<string | number>>([])
const answers = reactive<Record<string, string>>({})

function formatRate(value: unknown) {
  if (value == null || value === '') return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return String(value)
  return n <= 1 ? `${(n * 100).toFixed(1)}%` : `${n.toFixed(1)}%`
}

function asList(payload: unknown, keys: string[] = ['items', 'suggestions', 'questions', 'rows', 'data']): Row[] {
  if (Array.isArray(payload)) return payload
  if (!payload || typeof payload !== 'object') return []
  const obj = payload as Record<string, unknown>
  for (const key of keys) {
    const val = obj[key]
    if (Array.isArray(val)) return val as Row[]
    if (val && typeof val === 'object') {
      const nested = asList(val, ['items', 'rows'])
      if (nested.length) return nested
    }
  }
  return []
}

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const [sug, qs, sc] = await Promise.all([
      xcmaxEmployeeAutonomyApi.listSuggestions({ limit: 50 }),
      xcmaxEmployeeAutonomyApi.listQuestions({ include_history: false }),
      xcmaxEmployeeAutonomyApi.scorecard({ days: 7, top_n: 50 }),
    ])
    suggestions.value = asList(sug)
    questions.value = asList(qs)
    scorecard.value = asList(sc)
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function approveOne(id: string | number) {
  acting.value = true
  try {
    await xcmaxEmployeeAutonomyApi.approveSuggestion(id)
    await refresh()
  } catch (e: unknown) {
    await appAlert(e instanceof Error ? e.message : String(e))
  } finally {
    acting.value = false
  }
}

async function rejectOne(id: string | number) {
  const reason = await appPrompt('拒绝原因（可选）', '')
  if (reason === null) return
  acting.value = true
  try {
    await xcmaxEmployeeAutonomyApi.rejectSuggestion(id, reason || undefined)
    await refresh()
  } catch (e: unknown) {
    await appAlert(e instanceof Error ? e.message : String(e))
  } finally {
    acting.value = false
  }
}

async function batchApprove() {
  if (!selectedIds.value.length) return
  acting.value = true
  try {
    await xcmaxEmployeeAutonomyApi.batchReview({ approve_ids: [...selectedIds.value] })
    selectedIds.value = []
    await refresh()
  } catch (e: unknown) {
    await appAlert(e instanceof Error ? e.message : String(e))
  } finally {
    acting.value = false
  }
}

async function answerOne(id: string | number) {
  const text = String(answers[String(id)] || '').trim()
  if (!text) {
    await appAlert('请输入答复')
    return
  }
  acting.value = true
  try {
    await xcmaxEmployeeAutonomyApi.answerQuestion(id, text)
    answers[String(id)] = ''
    await refresh()
  } catch (e: unknown) {
    await appAlert(e instanceof Error ? e.message : String(e))
  } finally {
    acting.value = false
  }
}

onMounted(() => {
  void refresh()
})
</script>

<style scoped>
.employee-autonomy-view {
  padding: 24px 28px 40px;
  max-width: 1400px;
  margin: 0 auto;
  background: linear-gradient(135deg, #edf5fb 0%, #e7eef6 100%);
  min-height: 100%;
}
.page-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.page-header h2 { margin: 0 0 4px; font-size: 22px; color: #172033; }
.page-header p { margin: 0; color: #64748b; font-size: 13px; }
.header-actions, .ops { display: flex; gap: 8px; align-items: center; }
.btn {
  border: 1px solid #d0d7e2;
  background: #fff;
  border-radius: 8px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 13px;
}
.btn-primary { background: #1890ff; border-color: #1890ff; color: #fff; }
.btn:disabled { opacity: 0.6; cursor: not-allowed; }
.banner-error {
  background: #fff1f0; color: #cf1322; border: 1px solid #ffa39e;
  border-radius: 8px; padding: 10px 12px; margin-bottom: 12px;
}
.tabs { display: flex; gap: 8px; margin-bottom: 12px; }
.tabs button {
  border: 1px solid #d0d7e2; background: #fff; border-radius: 999px;
  padding: 6px 14px; cursor: pointer;
}
.tabs button.active { background: #1890ff; border-color: #1890ff; color: #fff; }
.card {
  background: rgba(255,255,255,0.92);
  border: 1px solid rgba(15,76,129,0.1);
  border-radius: 16px;
  padding: 14px;
  box-shadow: 0 4px 18px rgba(15,76,129,0.07);
}
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th, .data-table td {
  text-align: left; padding: 8px 10px; border-bottom: 1px solid #eef2f7;
}
.empty { padding: 28px; text-align: center; color: #94a3b8; }
.link { border: none; background: none; color: #1890ff; cursor: pointer; }
.link.danger { color: #cf1322; }
.qa-item { border: 1px solid #eef2f7; border-radius: 10px; padding: 12px; margin-bottom: 10px; }
.qa-q { font-weight: 600; color: #172033; }
.qa-meta { color: #94a3b8; font-size: 12px; margin: 4px 0 8px; }
.qa-answer { display: flex; gap: 8px; }
.qa-answer input {
  flex: 1; border: 1px solid #d0d7e2; border-radius: 8px; padding: 8px 10px;
}
</style>
