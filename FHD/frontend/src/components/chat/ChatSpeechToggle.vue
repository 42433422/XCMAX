<template>
  <ElButton
    text
    circle
    size="small"
    :type="enabled ? 'primary' : 'info'"
    :aria-label="$t('chat.ttsToggle')"
    :aria-pressed="enabled"
    :title="$t(enabled ? 'chat.ttsOn' : 'chat.ttsOff')"
    @click="$emit('update:enabled', !enabled)"
  >
    <i class="fa fa-volume-up speech-icon" :class="{ 'speech-icon--muted': !enabled }" aria-hidden="true"></i>
  </ElButton>
</template>

<script setup lang="ts">
import { ElButton } from 'element-plus'

defineProps<{ enabled: boolean }>()
defineEmits<{ 'update:enabled': [enabled: boolean] }>()
</script>

<style scoped>
.speech-icon { position: relative; font-size: 15px; }
.speech-icon--muted::after {
  content: '';
  position: absolute;
  inset-inline-start: -1px;
  inset-block-start: 50%;
  inline-size: calc(100% + 2px);
  border-block-start: 1.5px solid currentColor;
  transform: rotate(-45deg);
}
</style>
