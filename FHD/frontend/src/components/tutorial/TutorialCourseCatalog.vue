<template>
  <section class="tutorial-v2-catalog" aria-label="进阶教程课程目录">
    <div class="tutorial-v2-catalog__head">
      <div>
        <strong>进阶教程 · 真实业务实训</strong>
        <p>你亲自操作，服务端验证真实结果；所有写入只发生在个人教学空间。</p>
      </div>
      <span class="tutorial-v2-space-badge">教学空间</span>
    </div>

    <div class="tutorial-v2-upgrade" role="status">
      教程已升级：旧版“完成”记录不代表新课程完成，建议重新学习。
    </div>
    <div v-if="store.errorHint" class="tutorial-v2-error" role="alert">{{ store.errorHint }}</div>
    <div v-if="store.loading && !store.courses.length" class="tutorial-v2-loading">正在加载课程…</div>

    <ul v-else class="tutorial-v2-course-list">
      <li v-for="course in store.courses" :key="course.id" class="tutorial-v2-course-card">
        <div class="tutorial-v2-course-card__top">
          <div>
            <strong>{{ course.title }}</strong>
            <p>{{ course.summary }}</p>
          </div>
          <span class="tutorial-v2-status" :data-status="course.status">
            {{ statusLabel(course.status) }}
          </span>
        </div>
        <div class="tutorial-v2-meta">
          <span>约 {{ course.estimated_minutes }} 分钟</span>
          <span>进度 {{ course.progress }}%</span>
          <span v-if="course.prerequisite_ids.length">
            前置：{{ prerequisiteLabel(course.prerequisite_ids) }}
          </span>
          <span v-else>无前置课程</span>
        </div>
        <div class="tutorial-v2-progress" role="progressbar" :aria-valuenow="course.progress" aria-valuemin="0" aria-valuemax="100">
          <span :style="{ width: `${course.progress}%` }"></span>
        </div>
        <p v-if="course.locked" class="tutorial-v2-locked">
          先完成：{{ prerequisiteLabel(course.missing_prerequisite_ids) }}
        </p>
        <div class="tutorial-v2-actions">
          <button
            type="button"
            class="btn btn-primary btn-sm"
            :disabled="course.locked || store.loading"
            @click="openCourse(course)"
          >
            {{ actionLabel(course) }}
          </button>
          <button
            v-if="course.run"
            type="button"
            class="btn btn-secondary btn-sm"
            :disabled="store.loading"
            @click="resetCourse(course)"
          >
            重置
          </button>
        </div>
      </li>
    </ul>

    <details class="tutorial-v2-team">
      <summary>团队学习（企业管理员）</summary>
      <button type="button" class="btn btn-secondary btn-sm" @click="loadReports">查看团队学习</button>
      <p v-if="reportHint" class="tutorial-v2-report-hint">{{ reportHint }}</p>
      <ul v-if="store.reports.length" class="tutorial-v2-report-list">
        <li v-for="(report, index) in store.reports" :key="`${report.user_id}-${report.course_id}-${index}`">
          用户 {{ report.user_id }} · {{ report.course_id }} · {{ report.status }} ·
          {{ report.progress }}% · 尝试 {{ report.attempt_count }} 次
        </li>
      </ul>
    </details>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { TutorialCourseDTO } from '@/api/tutorialV2'
import { useTutorialV2Store } from '@/stores/tutorialV2'

const emit = defineEmits<{ close: [] }>()
const store = useTutorialV2Store()
const reportHint = ref('')

const titles: Record<string, string> = {
  'task-workspace': '智能对话与任务工作区',
  'master-data': '客户与产品建档',
  'sales-to-cash': '销售到收款完整闭环',
  'data-import': '业务文件导入',
  'evidence-trace': '结果核验与业务追踪',
}

function prerequisiteLabel(ids: string[]) {
  return ids.map((id) => titles[id] || id).join('、')
}

function statusLabel(status: TutorialCourseDTO['status']) {
  return {
    not_started: '未开始',
    active: '进行中',
    paused: '已保存',
    completed: '已完成',
    reset: '已重置',
  }[status] || status
}

function actionLabel(course: TutorialCourseDTO) {
  if (course.status === 'completed') return '复习'
  if (course.run) return '继续'
  return '开始'
}

async function openCourse(course: TutorialCourseDTO) {
  if (course.run?.status === 'completed') {
    await store.enterRun(course.run.id)
  } else {
    await store.startCourse(course.id)
  }
  emit('close')
}

async function resetCourse(course: TutorialCourseDTO) {
  if (!course.run) return
  const confirmed = window.confirm('重置会创建新的教学代次；旧教学数据 7 天后清理，学习证据继续保留。确定重置吗？')
  if (!confirmed) return
  await store.resetCourse(course.run.id)
  emit('close')
}

async function loadReports() {
  reportHint.value = ''
  try {
    const reports = await store.loadReports()
    reportHint.value = reports.length ? `共 ${reports.length} 条课程运行记录。` : '团队暂无学习记录。'
  } catch {
    reportHint.value = '只有企业 owner/admin 可以查看团队学习。'
  }
}

onMounted(() => {
  void store.loadCourses()
})
</script>

<style scoped>
.tutorial-v2-catalog { display: grid; gap: 12px; }
.tutorial-v2-catalog__head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.tutorial-v2-catalog__head p, .tutorial-v2-course-card p { margin: 4px 0 0; color: #56697a; line-height: 1.45; }
.tutorial-v2-space-badge { flex: 0 0 auto; border-radius: 999px; padding: 4px 9px; color: #7a3d00; background: #fff1cf; border: 1px solid #f0c56a; font-weight: 700; }
.tutorial-v2-upgrade { padding: 9px 10px; border-radius: 9px; color: #67551b; background: #fff9dc; border: 1px solid #eadb8a; }
.tutorial-v2-error { color: #9f2525; }
.tutorial-v2-course-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; }
.tutorial-v2-course-card { border: 1px solid #d9e3ec; border-radius: 12px; padding: 12px; background: #fff; display: grid; gap: 9px; }
.tutorial-v2-course-card__top { display: flex; justify-content: space-between; gap: 10px; }
.tutorial-v2-status { flex: 0 0 auto; font-size: 12px; color: #4b6378; }
.tutorial-v2-status[data-status='completed'] { color: #137247; font-weight: 700; }
.tutorial-v2-meta { display: flex; flex-wrap: wrap; gap: 6px 12px; color: #687a8b; font-size: 12px; }
.tutorial-v2-progress { height: 6px; overflow: hidden; border-radius: 999px; background: #e8eef3; }
.tutorial-v2-progress span { display: block; height: 100%; background: linear-gradient(90deg, #238bd3, #33b985); }
.tutorial-v2-locked { color: #9a651e !important; }
.tutorial-v2-actions { display: flex; gap: 8px; }
.tutorial-v2-team { border-top: 1px solid #e3eaf0; padding-top: 10px; }
.tutorial-v2-team summary { cursor: pointer; font-weight: 600; margin-bottom: 9px; }
.tutorial-v2-report-list { padding-left: 18px; max-height: 140px; overflow: auto; }
.tutorial-v2-report-hint { color: #66798a; }
</style>
