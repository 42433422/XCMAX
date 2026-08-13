<template>
  <Teleport to="body">
    <div v-if="run" class="tutorial-coach-shell" :class="{ 'is-paused': run.status === 'paused' }">
      <div class="tutorial-space-banner" role="status">
        <strong>{{ run.status === 'paused' ? '教学已保存' : '教学空间' }}</strong>
        <span v-if="run.status === 'paused'">当前未进入教学空间，请先返回当前步骤</span>
        <span v-else-if="run.status === 'completed'">复习模式只读；重置后才能重新操作</span>
        <span v-else>所有业务写入与正式企业数据隔离</span>
        <span>第 {{ run.generation }} 代 · {{ run.progress }}%</span>
      </div>
      <aside class="tutorial-coach" aria-label="实训教练">
        <header>
          <div>
            <span class="tutorial-coach__eyebrow">实训教练</span>
            <strong>{{ courseTitle }}</strong>
          </div>
          <button type="button" class="tutorial-coach__collapse" @click="collapsed = !collapsed">
            {{ collapsed ? '展开' : '收起' }}
          </button>
        </header>
        <template v-if="!collapsed && step && run.status !== 'paused' && run.status !== 'completed'">
          <div class="tutorial-coach__step">
            第 {{ currentIndex + 1 }} / {{ run.total_steps }} 步 · {{ step.title }}
          </div>
          <dl>
            <div><dt>目标</dt><dd>{{ step.goal }}</dd></div>
            <div><dt>你要做什么</dt><dd>{{ step.instruction }}</dd></div>
            <div><dt>成功标准</dt><dd>{{ step.success_criteria }}</dd></div>
            <div><dt>为什么</dt><dd>{{ step.why }}</dd></div>
            <div><dt>提示</dt><dd>{{ step.hint }}</dd></div>
            <div v-if="step.evidence"><dt>结果证据</dt><dd>{{ evidenceSummary }}</dd></div>
          </dl>
          <p v-if="store.verificationHint" class="tutorial-coach__result" :data-status="step.status">
            {{ store.verificationHint }}
          </p>
          <div class="tutorial-coach__actions">
            <button type="button" class="btn btn-primary btn-sm" @click="goOperate">去操作</button>
            <button
              type="button"
              class="btn btn-primary btn-sm"
              :disabled="store.verifying"
              @click="verify"
            >
              {{ store.verifying ? '验证中…' : '验证结果' }}
            </button>
            <button type="button" class="btn btn-secondary btn-sm" @click="leave">
              保存退出
            </button>
          </div>
          <a
            v-if="step.id === 'import-preview'"
            class="tutorial-coach__asset"
            :href="tutorialAssetUrl"
            download
          >下载内置教学 Excel</a>
        </template>
        <div v-else-if="!collapsed && run.status === 'completed'" class="tutorial-coach__complete">
          <span>课程已完成。复习模式只读，可逐步返回业务页面查看证据。</span>
          <ul class="tutorial-coach__review-list">
            <li v-for="item in run.steps" :key="item.id">
              <button type="button" @click="reviewStep(item)">{{ item.title }}</button>
              <span>{{ item.evidence?.result_code || 'verification_passed' }}</span>
            </li>
          </ul>
          <button type="button" class="btn btn-secondary btn-sm" @click="leave">退出教学</button>
        </div>
        <div v-else-if="!collapsed && run.status === 'paused'" class="tutorial-coach__paused">
          进度已保存。
          <button type="button" class="btn btn-primary btn-sm" @click="resume">返回当前步骤</button>
        </div>
      </aside>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import { useTutorialV2Store } from '@/stores/tutorialV2'
import { buildFullApiUrl } from '@/api/core'
import type { TutorialStepDTO } from '@/api/tutorialV2'

const store = useTutorialV2Store()
const { currentRun: run, currentStep: step } = storeToRefs(store)
const router = useRouter()
const route = useRoute()
const collapsed = ref(false)
const tutorialAssetUrl = buildFullApiUrl('/api/tutorial/v2/assets/business-import.xlsx')
let highlighted: Element | null = null
let highlightTimer: number | null = null

const courseTitle = computed(() => store.courses.find((course) => course.id === run.value?.course_id)?.title || '进阶实训')
const currentIndex = computed(() => run.value?.steps.findIndex((item) => item.id === step.value?.id) ?? 0)
const evidenceSummary = computed(() => {
  const evidence = step.value?.evidence
  if (!evidence) return '尚未验证'
  const counts = Object.entries(evidence.counts).map(([key, value]) => `${key}: ${value}`).join('，')
  return counts || evidence.result_code
})

function clearHighlight() {
  highlighted?.classList.remove('xcagi-tutorial-target-highlight')
  highlighted = null
  if (highlightTimer !== null) window.clearTimeout(highlightTimer)
  highlightTimer = null
}

async function goOperate() {
  if (!step.value || !run.value) return
  if (run.value.status === 'paused') await store.enterRun(run.value.id)
  await router.push({ name: step.value.route_name }).catch(() => undefined)
  store.markTargetVisited()
  window.setTimeout(() => {
    clearHighlight()
    try {
      highlighted = document.querySelector(step.value?.target_selector || '')
    } catch {
      highlighted = null
    }
    highlighted?.classList.add('xcagi-tutorial-target-highlight')
    highlightTimer = window.setTimeout(clearHighlight, 8000)
  }, 80)
}

async function verify() {
  await store.verifyCurrent(String(route.name || ''))
}

async function leave() {
  clearHighlight()
  await store.leaveCurrent()
}

async function resume() {
  if (!run.value) return
  await store.enterRun(run.value.id)
  await goOperate()
}

async function reviewStep(item: TutorialStepDTO) {
  await router.push({ name: item.route_name }).catch(() => undefined)
}

onMounted(() => {
  void store.loadCourses().catch(() => undefined)
  void store.restoreCurrent()
})
onBeforeUnmount(clearHighlight)
</script>

<style>
.tutorial-coach-shell { position: fixed; inset: 0; pointer-events: none; z-index: 4700; }
.tutorial-space-banner { pointer-events: auto; position: fixed; top: 0; left: 50%; transform: translateX(-50%); display: flex; gap: 12px; align-items: center; padding: 7px 16px; border: 1px solid #e6b64f; border-top: 0; border-radius: 0 0 12px 12px; background: #fff4d6; color: #6e4100; box-shadow: 0 4px 18px rgba(76, 49, 5, .16); }
.tutorial-coach { pointer-events: auto; position: fixed; right: 20px; bottom: 20px; width: min(390px, calc(100vw - 32px)); max-height: calc(100vh - 92px); overflow: auto; border: 1px solid #cbd9e4; border-radius: 16px; padding: 14px; background: rgba(255, 255, 255, .98); box-shadow: 0 18px 50px rgba(25, 47, 66, .24); }
.tutorial-coach header { display: flex; justify-content: space-between; gap: 12px; }
.tutorial-coach header > div { display: grid; }
.tutorial-coach__eyebrow { color: #2678ad; font-size: 12px; font-weight: 700; }
.tutorial-coach__collapse { border: 0; background: transparent; color: #4e6f86; cursor: pointer; }
.tutorial-coach__step { margin-top: 10px; padding: 7px 9px; border-radius: 8px; background: #edf6fc; color: #205f87; font-weight: 700; }
.tutorial-coach dl { margin: 10px 0; display: grid; gap: 8px; }
.tutorial-coach dl > div { display: grid; grid-template-columns: 78px 1fr; gap: 8px; }
.tutorial-coach dt { color: #38566c; font-weight: 700; }
.tutorial-coach dd { margin: 0; color: #4f6270; line-height: 1.45; }
.tutorial-coach__actions { display: flex; flex-wrap: wrap; gap: 8px; }
.tutorial-coach__result { padding: 8px 9px; border-radius: 8px; background: #f7f4e8; color: #755b16; }
.tutorial-coach__result[data-status='passed'] { background: #e9f8f0; color: #146541; }
.tutorial-coach__asset { display: inline-block; margin-top: 10px; color: #1877ad; font-weight: 600; }
.tutorial-coach__paused, .tutorial-coach__complete { margin-top: 12px; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.tutorial-coach__complete { align-items: stretch; flex-direction: column; }
.tutorial-coach__review-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 6px; }
.tutorial-coach__review-list li { display: flex; justify-content: space-between; gap: 8px; color: #5f7180; font-size: 12px; }
.tutorial-coach__review-list button { border: 0; padding: 0; background: transparent; color: #1877ad; cursor: pointer; text-align: left; }
.xcagi-tutorial-target-highlight { position: relative !important; outline: 4px solid #f4b942 !important; outline-offset: 4px !important; box-shadow: 0 0 0 10px rgba(244, 185, 66, .22) !important; z-index: 4600 !important; }
@media (max-width: 720px) {
  .tutorial-space-banner { width: calc(100vw - 24px); justify-content: center; flex-wrap: wrap; gap: 5px 10px; font-size: 12px; }
  .tutorial-coach { right: 12px; bottom: 76px; width: calc(100vw - 24px); }
}
</style>
