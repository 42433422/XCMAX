<template>
  <img
    class="aiopen-launcher-svg"
    :src="aiOpenIcon"
    alt=""
    aria-hidden="true"
    draggable="false"
  />
</template>

<script setup lang="ts">
import aiOpenIcon from '@/assets/icons/aiopen.png'
</script>

<style scoped>
.aiopen-launcher-svg {
  width: 52px;
  height: 52px;
  display: block;
  object-fit: cover;
  border-radius: 12px;
}
</style>
