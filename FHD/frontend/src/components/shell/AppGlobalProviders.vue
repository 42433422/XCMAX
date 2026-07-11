<script setup lang="ts">
import AppDialogHost from '@/components/AppDialogHost.vue'
import AdminEmployeeWorkNotificationBridge from '@/components/shell/AdminEmployeeWorkNotificationBridge.vue'
import GlobalLanGateModal from '@/components/lan/GlobalLanGateModal.vue'

defineProps<{
  showLanGate: boolean
}>()
</script>

<template>
  <AppDialogHost />
  <AdminEmployeeWorkNotificationBridge />
  <GlobalLanGateModal v-if="showLanGate" />
</template>
