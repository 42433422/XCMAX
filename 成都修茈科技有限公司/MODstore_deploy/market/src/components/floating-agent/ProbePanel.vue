<script setup lang="ts">
import { ref, computed, nextTick, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useAgentStore } from '../../stores/agent'
import type { AgentHandleInputFn } from '../../composables/agent/agentEngineInjection'
import AgentStatusBar from './AgentStatusBar.vue'
import AgentChatHistory from './AgentChatHistory.vue'
import ButlerFilesDrawer from './ButlerFilesDrawer.vue'
import { useButlerWorkbenchTrayStore } from '../../stores/butlerWorkbenchTray'
import { useButlerDownloadHistoryStore } from '../../stores/butlerDownloadHistory'
import { useWorkbenchTheme } from '../../composables/useWorkbenchTheme'
import { getActionLog } from '../../composables/agent/useActionExecutor'
import { saveCorpBallPosition } from '../../corp-butler/corpBallPosition'
import {
  isCorpProactiveIntroEnabled,
  setCorpProactiveIntroEnabled,
  stopCorpIntroSpeech,
} from '../../corp-butler/corpPageIntro'
import type { QuickAction } from '../../content/siteKnowledge'

const props = withDefaults(
  defineProps<{
    corpMode?: boolean
    handleInput: AgentHandleInputFn
    runIntakeTask?: (action: QuickAction) => Promise<void>
  }>(),
  { corpMode: false, runIntakeTask: undefined },
)

const emit = defineEmits<{
  (e: 'proactive-intro-change', enabled: boolean): void
}>()

const agentStore = useAgentStore()
const trayStore = useButlerWorkbenchTrayStore()
const historyStore = useButlerDownloadHistoryStore()
const { mode, position, focusFilesDrawer } = storeToRefs(agentStore)
const { overflowCount } = storeToRefs(trayStore)
const filesDrawerRef = ref<InstanceType<typeof ButlerFilesDrawer> | null>(null)
const { isLightTheme } = useWorkbenchTheme()

const showFilesDrawer = computed(
  () => overflowCount.value > 0 || historyStore.records.length > 0,
)

watch(focusFilesDrawer, (focus) => {
  if (!focus) return
  void nextTick(() => {
    const el = filesDrawerRef.value?.$el as HTMLElement | undefined
    el?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
    agentStore.clearFilesDrawerFocus()
  })
})

const panelRef = ref<HTMLDivElement | null>(null)
const draft = ref('')

const panelStyle = computed(() => {
  const bx = position.value.x
  const by = position.value.y
  const panelW = 340
  const panelH = props.corpMode ? 420 : 460
  const margin = 12

  let left = bx + 32 - panelW / 2
  let top = by - panelH - margin

  left = Math.max(8, Math.min(window.innerWidth - panelW - 8, left))
  top = Math.max(8, Math.min(window.innerHeight - panelH - 8, top))

  const base = {
    left: `${left}px`,
    top: `${top}px`,
    width: `${panelW}px`,
  }
  if (props.corpMode) return base
  return { ...base, height: `${panelH}px` }
})

let panelDragStartX = 0
let panelDragStartY = 0
let isPanelDragging = false

function onHeaderPointerDown(e: PointerEvent) {
  if (e.button !== 0) return
  isPanelDragging = true
  panelDragStartX = e.clientX
  panelDragStartY = e.clientY
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
}

function onHeaderPointerMove(e: PointerEvent) {
  if (!isPanelDragging) return
  const dx = e.clientX - panelDragStartX
  const dy = e.clientY - panelDragStartY
  panelDragStartX = e.clientX
  panelDragStartY = e.clientY
  if (props.corpMode) {
    const p = saveCorpBallPosition(position.value.x + dx, position.value.y + dy)
    agentStore.savePosition(p.x, p.y)
    return
  }
  agentStore.savePosition(position.value.x + dx, position.value.y + dy)
}

function onHeaderPointerUp() {
  isPanelDragging = false
}
</script>

<template>
  <div>
    <AgentStatusBar v-if="!corpMode" :mode="mode" @stop="agentStore.setMode('idle')" />
    <AgentChatHistory :corp-mode="corpMode" @quick="() => {}" @task="() => {}" />
  </div>
</template>

<style scoped>
/* probe */
</style>
