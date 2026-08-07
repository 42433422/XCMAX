<template>
  <section v-if="showIntakeBlock" class="cs-block cs-block-biz">
    <h4 class="cs-block-title">需求采集</h4>
    <p class="cs-block-desc">{{ description }}</p>
    <input
      v-model="demandIntake.clientName"
      type="text"
      class="cs-input"
      placeholder="默认填匹配的公司名，勿用登录账号"
    />
    <textarea v-model="demandIntake.brief" rows="2" class="cs-input" placeholder="业务背景 *" />
    <div class="cs-block-actions">
      <button
        type="button"
        class="btn btn-xs btn-accent"
        :disabled="demandIntake.loading || !demandIntake.brief.trim()"
        @click="$emit('generate')"
      >
        {{ demandIntake.loading ? '生成中…' : '生成话术' }}
      </button>
      <button type="button" class="btn btn-xs" :disabled="intakeLinkLoading" @click="$emit('open-form')">
        打开官网表单
      </button>
      <button v-if="demandIntake.messageText" type="button" class="btn btn-xs" @click="$emit('copy-message')">
        复制话术
      </button>
    </div>
    <div v-if="intakeSubmissionSummary" class="cs-intake-summary">
      <p class="cs-intake-summary__title">
        客户已提交需求
        <span v-if="intakeSubmittedAt" class="cs-intake-summary__time">{{ formatPassivePollTime(intakeSubmittedAt) }}</span>
      </p>
      <dl class="cs-intake-summary__dl">
        <template v-for="row in intakeSubmissionSummary" :key="row.label">
          <dt>{{ row.label }}</dt>
          <dd>{{ row.value }}</dd>
        </template>
      </dl>
    </div>
    <pre v-if="demandIntake.messageText" class="cs-preview">{{ demandIntake.messageText }}</pre>
  </section>
</template>

<script setup lang="ts">
import { formatPassivePollTime } from '../composables/useCustomerServiceFormat'

export type DemandIntakeState = {
  brief: string
  clientName: string
  formUrl: string
  signedFormUrl: string
  messageText: string
  loading: boolean
}

defineProps<{
  showIntakeBlock: boolean
  description: string
  demandIntake: DemandIntakeState
  intakeLinkLoading: boolean
  intakeSubmissionSummary: Array<{ label: string; value: string }> | null
  intakeSubmittedAt: string
}>()

defineEmits<{
  (e: 'generate'): void
  (e: 'open-form'): void
  (e: 'copy-message'): void
}>()
</script>

<style scoped>
.cs-block {
  background: #f8fafc; border: 1px solid #e8ecf2; border-radius: 10px; padding: 12px;
  display: flex; flex-direction: column; gap: 8px;
}
.cs-block-biz { background: #fff; }
.cs-block-title { margin: 0; font-size: 13px; font-weight: 600; color: #334155; }
.cs-block-desc { margin: 0; font-size: 12px; color: #64748b; line-height: 1.5; }
.cs-block-actions { display: flex; flex-wrap: wrap; gap: 6px; }
.cs-input {
  width: 100%; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 10px;
  font-size: 13px; box-sizing: border-box; background: #fff;
}
.cs-preview {
  font-size: 12px; line-height: 1.55; padding: 10px; background: #fff; border-radius: 8px;
  border: 1px solid #e2e8f0; white-space: pre-wrap; max-height: 160px; overflow: auto; margin: 0;
}
.cs-intake-summary {
  margin-top: 10px; padding: 10px 12px; border-radius: 8px;
  background: #f0fdf4; border: 1px solid #bbf7d0;
}
.cs-intake-summary__title { margin: 0 0 8px; font-size: 12px; font-weight: 600; color: #166534; }
.cs-intake-summary__time { font-weight: 400; color: #64748b; margin-left: 6px; }
.cs-intake-summary__dl {
  margin: 0; display: grid; grid-template-columns: 4.5em 1fr; gap: 4px 10px; font-size: 12px;
}
.cs-intake-summary__dl dt { color: #64748b; margin: 0; }
.cs-intake-summary__dl dd { margin: 0; color: #1e293b; white-space: pre-wrap; }
.muted { color: #94a3b8; }
.btn-xs { padding: 5px 12px; font-size: 12px; border-radius: 6px; border: 1px solid #e8ecf2; background: #fff; cursor: pointer; }
.btn-xs:hover { border-color: #cbd5e1; }
.btn-accent { background: #4a6cf7; border-color: #4a6cf7; color: #fff; }
.btn-accent:hover { opacity: 0.92; }
.btn-accent:disabled { opacity: 0.5; cursor: not-allowed; }
</style>