<template>
  <section class="tutorial-v2-catalog" aria-label="进阶教程课程目录">
    <div class="tutorial-v2-catalog__head">
      <div>
        <strong>进阶教程 · 跟着做就能学会</strong>
        <p>第一次使用也没关系。每一步只做三件事：打开页面、照着提示操作、让系统检查。</p>
      </div>
      <span class="tutorial-v2-space-badge">教学空间</span>
    </div>

    <ol class="tutorial-v2-howto" aria-label="学习方法">
      <li><strong>1</strong><span>按顺序选一门课</span></li>
      <li><strong>2</strong><span>每次只完成一个动作</span></li>
      <li><strong>3</strong><span>做完点“检查一下”</span></li>
    </ol>
    <div class="tutorial-v2-upgrade" role="status">
      这是新版动手教程。旧教程记录还在，但建议从第 1 门重新学一次。
    </div>
    <div v-if="store.errorHint" class="tutorial-v2-error" role="alert">{{ store.errorHint }}</div>
    <div v-if="store.loading && !store.courses.length" class="tutorial-v2-loading">正在加载课程…</div>

    <ul v-else class="tutorial-v2-course-list">
      <li v-for="(course, index) in store.courses" :key="course.id" class="tutorial-v2-course-card">
        <div class="tutorial-v2-course-card__top">
          <div>
            <span class="tutorial-v2-course-card__number">课程 {{ index + 1 }}</span>
            <strong>{{ course.title }}</strong>
            <p>{{ course.summary }}</p>
          </div>
          <span class="tutorial-v2-status" :data-status="course.status">
            {{ statusLabel(course.status) }}
          </span>
        </div>
        <div class="tutorial-v2-meta">
          <span>约 {{ course.estimated_minutes }} 分钟</span>
          <span>{{ progressLabel(course) }}</span>
          <span v-if="course.prerequisite_ids.length">
            开始前先完成：{{ prerequisiteLabel(course.prerequisite_ids) }}
          </span>
          <span v-else>现在就可以开始</span>
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
      <summary>我是管理员：查看团队学习情况</summary>
      <button type="button" class="btn btn-secondary btn-sm" @click="loadReports">查看团队进度</button>
      <p v-if="reportHint" class="tutorial-v2-report-hint">{{ reportHint }}</p>
      <ul v-if="store.reports.length" class="tutorial-v2-report-list">
        <li v-for="(report, index) in store.reports" :key="`${report.user_id}-${report.course_id}-${index}`">
          {{ report.user_name || `成员 #${report.user_id}` }} · {{ courseLabel(String(report.course_id || '')) }} · {{ reportStatusLabel(String(report.status || '')) }} ·
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

function courseLabel(id: string) {
  return titles[id] || '进阶课程'
}

function reportStatusLabel(status: string) {
  return ({ active: '进行中', paused: '已保存', completed: '已完成', reset: '已重置' } as Record<string, string>)[status] || '未开始'
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

function progressLabel(course: TutorialCourseDTO) {
  if (!course.run) return `共 ${course.steps.length} 步`
  return `已完成 ${course.run.completed_steps} / ${course.run.total_steps} 步`
}

function actionLabel(course: TutorialCourseDTO) {
  if (course.status === 'completed') return '查看学习成果'
  if (course.run) return '继续学习'
  return '开始学习'
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
  const confirmed = window.confirm('重新学习会清空本轮练习并从第一步开始。你公司的正式数据不会受影响；旧练习数据会在 7 天后自动清理。确定重新开始吗？')
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
    reportHint.value = '只有企业负责人或管理员可以查看团队学习情况。'
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
.tutorial-v2-howto { list-style: none; padding: 10px 12px; margin: 0; display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; border-radius: 10px; background: #f2f8fc; }
.tutorial-v2-howto li { display: flex; gap: 8px; align-items: center; color: #3f5c70; font-size: 13px; }
.tutorial-v2-howto strong { display: grid; place-items: center; flex: 0 0 24px; height: 24px; border-radius: 50%; background: #2678ad; color: #fff; }
.tutorial-v2-error { color: #9f2525; }
.tutorial-v2-course-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; }
.tutorial-v2-course-card { border: 1px solid #d9e3ec; border-radius: 12px; padding: 12px; background: #fff; display: grid; gap: 9px; }
.tutorial-v2-course-card__top { display: flex; justify-content: space-between; gap: 10px; }
.tutorial-v2-course-card__number { display: block; margin-bottom: 3px; color: #2678ad; font-size: 11px; font-weight: 700; }
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
@media (max-width: 720px) {
  .tutorial-v2-howto { grid-template-columns: 1fr; }
}
</style>
