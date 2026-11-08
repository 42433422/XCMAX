<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  employee: 'database' | 'knowledge'
  name: string
  role: string
  outcome: string
  lines: string[]
}>()

const spoken = computed(() => {
  const text = props.lines.filter(Boolean).join('，')
  if (!text) return ''
  return /[。！？]$/.test(text) ? text : `${text}。`
})
const unfinished = computed(() => props.outcome.includes('没有做完'))
</script>

<template>
  <article class="workbook-node work-utterance" :data-employee="employee" :data-finished="unfinished ? 'false' : 'true'" :aria-label="`${name}工作情况回报`">
    <span class="workbook-node__dot" :class="{ 'workbook-node__dot--quiet': unfinished }" aria-hidden="true"></span>
    <div class="workbook-node__body">
      <p class="workbook-node__who"><span class="work-utterance__name">{{ name }}</span><span class="work-utterance__role">{{ role }}</span></p>
      <p class="work-utterance__words">
        <span class="work-utterance__outcome">{{ outcome }}</span>
        <span v-if="spoken" class="work-utterance__detail">{{ spoken }}</span>
      </p>
    </div>
  </article>
</template>

<style scoped>
.work-utterance {
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  color: var(--xc-color-text);
}
.workbook-node__who { margin: 0; display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--xc-space-2); }
.work-utterance__name { font-size: 13px; font-weight: 600; line-height: 1.4; }
.work-utterance__role { color: var(--xc-color-text-secondary); font-size: 13px; line-height: 1.4; }
.work-utterance__words { margin: var(--xc-space-1) 0 0; max-width: 40rem; font-size: 15px; line-height: 1.65; }
.work-utterance__outcome { color: var(--xc-color-text); }
.work-utterance__detail { display: block; margin-top: var(--xc-space-1); color: var(--xc-color-text-secondary); }
</style>
