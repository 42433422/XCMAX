<template>
  <span class="pack-type-icon" :class="`pack-type-icon--${kind}`" :title="title" aria-hidden="true">
    <svg v-if="kind === 'ppt'" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="3" y="4" width="18" height="16" rx="2" fill="#D24726" />
      <path d="M7 9h10M7 12h8M7 15h6" stroke="#fff" stroke-width="1.5" stroke-linecap="round" />
    </svg>
    <svg v-else-if="kind === 'excel'" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="3" y="4" width="18" height="16" rx="2" fill="#217346" />
      <path d="M8 8v8M12 8v8M16 8v8M7 12h10" stroke="#fff" stroke-width="1.2" stroke-linecap="round" />
    </svg>
    <svg v-else-if="kind === 'csv'" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="3" y="4" width="18" height="16" rx="2" fill="#0E7C86" />
      <text x="12" y="15" text-anchor="middle" fill="#fff" font-size="7" font-weight="700" font-family="system-ui,sans-serif">CSV</text>
    </svg>
    <svg v-else-if="kind === 'pdf'" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="3" y="4" width="18" height="16" rx="2" fill="#E5252A" />
      <text x="12" y="15" text-anchor="middle" fill="#fff" font-size="7" font-weight="700" font-family="system-ui,sans-serif">PDF</text>
    </svg>
    <svg v-else-if="kind === 'word'" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="3" y="4" width="18" height="16" rx="2" fill="#2B579A" />
      <path d="M8 9l2 6 2-6 2 6 2-6" stroke="#fff" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
    <svg v-else-if="kind === 'report'" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="3" y="4" width="18" height="16" rx="2" fill="#7C3AED" />
      <path d="M8 9h8M8 12h8M8 15h5" stroke="#fff" stroke-width="1.5" stroke-linecap="round" />
      <circle cx="17" cy="16" r="2" fill="#FBBF24" />
    </svg>
    <svg v-else-if="kind === 'office'" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="2" y="5" width="9" height="14" rx="1.5" fill="#217346" />
      <rect x="13" y="5" width="9" height="14" rx="1.5" fill="#D24726" />
      <path d="M5 9h3M5 12h3M16 9h3M16 12h3" stroke="#fff" stroke-width="1" stroke-linecap="round" />
    </svg>
    <svg v-else viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="4" y="5" width="16" height="14" rx="2" fill="rgba(96,165,250,0.35)" stroke="#60a5fa" stroke-width="1.2" />
      <circle cx="12" cy="12" r="3" fill="#60a5fa" />
    </svg>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { employeePackIconKind, type EmployeePackIconKind } from '../../constants/officeEmployeePack'

const props = defineProps<{
  pkgId?: string | null
  kind?: EmployeePackIconKind
}>()

const kind = computed(() => props.kind || employeePackIconKind(props.pkgId))

const titleMap: Record<EmployeePackIconKind, string> = {
  ppt: 'PPT',
  excel: 'Excel',
  csv: 'CSV',
  pdf: 'PDF',
  word: 'Word',
  report: '报告 / 附属包',
  office: '办公员工包',
  generic: 'AI 员工',
}

const title = computed(() => titleMap[kind.value] || 'AI 员工')
</script>

<style scoped>
.pack-type-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border-radius: 8px;
  overflow: hidden;
}

.pack-type-icon svg {
  width: 32px;
  height: 32px;
  display: block;
}
</style>
