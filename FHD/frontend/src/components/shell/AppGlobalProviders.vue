<script setup lang="ts">
import GlobalReadTokenPrompt from '@/fhd/GlobalReadTokenPrompt.vue'
import GlobalWriteTokenPrompt from '@/fhd/GlobalWriteTokenPrompt.vue'
import AppDialogHost from '@/components/AppDialogHost.vue'
import GlobalLanGateModal from '@/components/lan/GlobalLanGateModal.vue'

defineProps<{
  showLanGate: boolean
}>()
</script>

<template>
  <GlobalReadTokenPrompt api-base="" />
  <GlobalWriteTokenPrompt />
  <AppDialogHost />
  <GlobalLanGateModal v-if="showLanGate" />
</template>
