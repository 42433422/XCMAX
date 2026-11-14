<template>
  <img
    class="modstore-launcher-svg"
    :class="{ 'modstore-launcher-svg--sm': size === 'sm' }"
    :src="modStoreIcon"
    alt=""
    aria-hidden="true"
    draggable="false"
  />
</template>

<script setup lang="ts">
import modStoreIcon from '@/assets/icons/modstore.png'

withDefaults(
  defineProps<{
    size?: 'md' | 'sm'
  }>(),
  { size: 'md' },
)
</script>

<style scoped>
.modstore-launcher-svg {
  width: 52px;
  height: 52px;
  display: block;
  object-fit: cover;
  border-radius: 12px;
}
.modstore-launcher-svg--sm {
  width: 28px;
  height: 28px;
  border-radius: 7px;
}
</style>
