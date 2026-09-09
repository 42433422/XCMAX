<template>
  <RouterLink v-if="valid" :to="{ path: resolveErpPagePath('/print'), query: { label_job: valid } }">打开标签预览与确认</RouterLink>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { resolveErpPagePath } from '@/utils/erpPagePaths'
const props = defineProps<{ jobId?: unknown }>()
const valid = computed(() => typeof props.jobId === 'string' && /^[a-f0-9]{32}$/.test(props.jobId) ? props.jobId : '')
</script>
