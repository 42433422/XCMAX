<script setup>
// 新手教程标签页：由 TopAssistantFloat.vue 模板机械切分而来（行为保持不变）。
import TutorialCourseCatalog from '@/components/tutorial/TutorialCourseCatalog.vue'
import { DEFAULT_TUTORIAL_TRACK_ID } from '@/constants/productFlow'

defineProps({
  showAdvancedCourses: { type: Boolean, default: false },
  tutorialTracks: { type: Array, default: () => [] },
  advancedTrackHint: { type: String, default: '' },
})

defineEmits(['back', 'close', 'start'])
</script>

<template>
  <div class="assistant-body assistant-body-tutorial">
    <div v-if="showAdvancedCourses" class="tutorial-v2-panel">
      <button type="button" class="btn btn-secondary btn-sm tutorial-v2-back" @click="$emit('back')">
        返回教程选择
      </button>
      <TutorialCourseCatalog @close="$emit('close')" />
    </div>
    <div v-else class="tutorial-track-pick">
      <div class="tutorial-track-heading">选择教程</div>
      <p class="tutorial-track-lead">默认路线「宿主入门」：认识XC → 行业定型 → 准备菜单。</p>
      <ul class="tutorial-track-list">
        <li
          v-for="(track, index) in tutorialTracks"
          :key="track.id"
          class="tutorial-track-card"
        >
          <div class="tutorial-track-card-main">
            <div class="tutorial-track-card-title">{{ track.title }}</div>
            <p class="tutorial-track-card-summary">{{ track.summary }}</p>
            <p v-if="track.id === 'advanced'" class="tutorial-track-card-extra muted">
              {{ advancedTrackHint }}
            </p>
            <p v-else-if="track.id !== DEFAULT_TUTORIAL_TRACK_ID" class="tutorial-track-card-extra muted">
              扩展说明 · 未接入 V2 服务端验证器，不计入正式课程完成
            </p>
          </div>
          <button
            type="button"
            class="btn btn-sm"
            :class="index === 0 || track.recommended ? 'btn-primary' : 'btn-secondary'"
            :title="track.description"
            @click="$emit('start', track.id)"
          >
            开始
          </button>
        </li>
      </ul>
      <details class="tutorial-track-details">
        <summary>路线说明</summary>
        <p
          v-for="track in tutorialTracks"
          :key="`${track.id}-desc`"
          class="tutorial-track-hint"
        >
          <strong>{{ track.title }}</strong> — {{ track.description }}
        </p>
      </details>
    </div>
  </div>
</template>

<style scoped src="./top-assistant-float.css"></style>
