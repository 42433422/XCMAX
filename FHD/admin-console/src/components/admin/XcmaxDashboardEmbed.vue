<template>
  <div class="xcmax-dashboard-embed">
    <iframe
      :title="title"
      :src="src"
      class="xcmax-dashboard-embed__frame"
      referrerpolicy="no-referrer"
    />
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    src: string
    title?: string
  }>(),
  { title: 'XCMAX 全景' },
)
</script>

<style scoped>
.xcmax-dashboard-embed {
  width: 100%;
  min-height: min(72vh, 900px);
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
  background: #0f172a;
}
.xcmax-dashboard-embed__frame {
  width: 100%;
  height: min(72vh, 900px);
  border: 0;
  display: block;
}
</style>
