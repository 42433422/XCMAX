<script setup lang="ts">
import { defineAsyncComponent } from 'vue'

const ImMessengerView = defineAsyncComponent(() => import('../ImMessengerView.vue'))
</script>

<template>
  <ImMessengerView />
</template>
