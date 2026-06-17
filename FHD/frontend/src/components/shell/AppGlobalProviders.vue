<script setup lang="ts">
import AppDialogHost from '@/components/AppDialogHost.vue'
import GlobalLanGateModal from '@/components/lan/GlobalLanGateModal.vue'

defineProps<{
  showLanGate: boolean
}>()
</script>

<template>
  <AppDialogHost />
  <GlobalLanGateModal v-if="showLanGate" />
</template>
