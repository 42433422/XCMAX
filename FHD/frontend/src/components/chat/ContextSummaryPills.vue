<template>
  <div v-if="parsed.chips.length" class="context-summary">
    <span class="context-summary__label" aria-hidden="true">
      <svg class="context-summary__icon" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path
          d="M8 1.5a4 4 0 0 0-4 4v1.25H3.5a1 1 0 0 0-1 1V12a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1V7.75a1 1 0 0 0-1-1H12V5.5a4 4 0 0 0-4-4Z"
          stroke="currentColor"
          stroke-width="1.2"
        />
      </svg>
      上下文
    </span>
    <span v-for="(chip, idx) in parsed.chips" :key="idx" class="context-summary__chip">{{ chip }}</span>
    <span v-if="parsed.total != null" class="context-summary__count">{{ parsed.total }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { parseContextSummary } from '@/utils/parseContextSummary'

const props = defineProps<{
  summary?: string
}>()

const parsed = computed(() => parseContextSummary(props.summary))
</script>
