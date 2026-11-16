<template>
  <img
    class="production-employee-launcher-svg"
    :class="{ 'production-employee-launcher-svg--sm': size === 'sm' }"
    :src="privateDeliveryIcon"
    alt=""
    aria-hidden="true"
    draggable="false"
  />
</template>

<script setup lang="ts">
import privateDeliveryIcon from '@/assets/icons/private-delivery.png'

withDefaults(
  defineProps<{
    size?: 'md' | 'sm'
  }>(),
  { size: 'md' },
)
</script>

<style scoped>
.production-employee-launcher-svg {
  width: 52px;
  height: 52px;
  display: block;
  object-fit: cover;
  border-radius: 12px;
}
.production-employee-launcher-svg--sm {
  width: 28px;
  height: 28px;
  border-radius: 7px;
}
</style>
