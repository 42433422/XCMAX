<template>
  <Teleport to="body">
    <div class="voice-call-overlay" role="dialog" aria-modal="true" aria-label="语音通话">
      <div class="voice-call-topbar">
        <button type="button" class="voice-call-collapse" title="收起并挂断" @click="$emit('hangup')">
          <i class="fa fa-angle-down" aria-hidden="true"></i>
        </button>
        <span class="voice-call-caption">语音通话</span>
        <span class="voice-call-placeholder" aria-hidden="true"></span>
      </div>

      <div class="voice-call-main">
        <div class="voice-call-avatar" aria-hidden="true">
          <i class="fa fa-headset"></i>
        </div>
        <div class="voice-call-name">{{ title }}</div>
        <div class="voice-call-duration">{{ durationText }}</div>
        <div class="voice-call-status">
          <span v-if="busy" class="voice-call-spinner" aria-hidden="true"></span>
          {{ statusText }}
        </div>

        <div class="voice-call-transcript">
          <div v-if="heardText" class="voice-call-line">
            <div class="voice-call-line-label">你</div>
            <div class="voice-call-line-text voice-call-line-text--user">{{ heardText }}</div>
          </div>
          <div v-if="replyText" class="voice-call-line">
            <div class="voice-call-line-label">{{ title }}</div>
            <div class="voice-call-line-text">{{ replyText }}</div>
          </div>
          <div v-if="errorText && !ended" class="voice-call-error">{{ errorText }}</div>
        </div>
      </div>

      <div class="voice-call-controls">
        <button type="button" class="voice-call-control" :class="{ active: muted }" @click="$emit('toggle-mute')">
          <span class="voice-call-control-icon"><i class="fa" :class="muted ? 'fa-microphone-slash' : 'fa-microphone'" aria-hidden="true"></i></span>
          <span class="voice-call-control-label">{{ muted ? '取消静音' : '静音' }}</span>
        </button>
        <button type="button" class="voice-call-control voice-call-control--danger" @click="$emit('hangup')">
          <span class="voice-call-control-icon"><i class="fa fa-phone" aria-hidden="true"></i></span>
          <span class="voice-call-control-label">挂断</span>
        </button>
        <button type="button" class="voice-call-control" :class="{ active: speakerOn }" @click="$emit('toggle-speaker')">
          <span class="voice-call-control-icon"><i class="fa" :class="speakerOn ? 'fa-volume-up' : 'fa-volume-off'" aria-hidden="true"></i></span>
          <span class="voice-call-control-label">免提</span>
        </button>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { VoiceCallStage } from '@/composables/useVoiceCall'

const props = withDefaults(defineProps<{
  title?: string
  stage: VoiceCallStage
  durationText: string
  statusText: string
  heardText?: string
  replyText?: string
  errorText?: string
  muted?: boolean
  speakerOn?: boolean
}>(), {
  title: '通用助手',
  heardText: '',
  replyText: '',
  errorText: '',
  muted: false,
  speakerOn: true,
})

defineEmits<{
  (event: 'hangup'): void
  (event: 'toggle-mute'): void
  (event: 'toggle-speaker'): void
}>()

const busy = computed(() => ['listening', 'thinking', 'speaking'].includes(props.stage))
const ended = computed(() => props.stage === 'ended')
</script>

<style scoped>
.voice-call-overlay {
  position: fixed;
  inset: 0;
  z-index: 4000;
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, #16181f 0%, #101116 100%);
  color: #fff;
}

.voice-call-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px 0;
}

.voice-call-collapse {
  width: 40px;
  height: 40px;
  border: none;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.8);
  cursor: pointer;
  font-size: 18px;
}

.voice-call-caption {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.65);
}

.voice-call-placeholder {
  width: 40px;
}

.voice-call-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 40px 28px 12px;
  overflow: hidden;
}

.voice-call-avatar {
  width: 108px;
  height: 108px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 42px;
  color: #fff;
  background: radial-gradient(circle at 30% 25%, #5b8cff 0%, #3a5bd9 55%, #23347f 100%);
  box-shadow: 0 12px 32px rgba(58, 91, 217, 0.35);
}

.voice-call-name {
  margin-top: 18px;
  font-size: 22px;
  font-weight: 600;
}

.voice-call-duration {
  margin-top: 6px;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.55);
  font-variant-numeric: tabular-nums;
}

.voice-call-status {
  margin-top: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: rgba(255, 255, 255, 0.72);
}

.voice-call-spinner {
  width: 13px;
  height: 13px;
  border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.25);
  border-top-color: #6f9bff;
  animation: voice-call-spin 0.9s linear infinite;
}

@keyframes voice-call-spin {
  to { transform: rotate(360deg); }
}

.voice-call-transcript {
  margin-top: 26px;
  width: 100%;
  max-width: 640px;
  overflow-y: auto;
}

.voice-call-line + .voice-call-line {
  margin-top: 14px;
}

.voice-call-line-label {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.4);
}

.voice-call-line-text {
  margin-top: 4px;
  font-size: 15px;
  line-height: 1.55;
  color: #fff;
  white-space: pre-wrap;
  word-break: break-word;
}

.voice-call-line-text--user {
  color: rgba(255, 255, 255, 0.68);
}

.voice-call-error {
  margin-top: 14px;
  text-align: center;
  font-size: 13px;
  color: #ffb25e;
}

.voice-call-controls {
  display: flex;
  align-items: center;
  justify-content: space-around;
  padding: 12px 56px 38px;
}

.voice-call-control {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  border: none;
  background: transparent;
  color: rgba(255, 255, 255, 0.7);
  cursor: pointer;
}

.voice-call-control-icon {
  width: 62px;
  height: 62px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  color: #fff;
  background: rgba(255, 255, 255, 0.1);
  transition: background 0.15s ease;
}

.voice-call-control.active .voice-call-control-icon {
  background: rgba(255, 255, 255, 0.22);
}

.voice-call-control--danger .voice-call-control-icon {
  background: #e5484d;
}

.voice-call-control-label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.6);
}
</style>
