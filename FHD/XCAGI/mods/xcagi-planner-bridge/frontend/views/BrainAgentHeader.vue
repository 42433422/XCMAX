<template>
  <div class="page-header brain-agent-header">
    <div class="brain-agent-title-row">
      <h2>{{ title }}</h2>
      <span class="brain-agent-badge" title="编排与观测控制台">Agent</span>
    </div>
    <p class="muted brain-sub">{{ subtitle }}</p>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, required: true },
})
</script>

<style>
.brain-layout--private { display: block; }
.brain-layout--private .brain-main { width: 100%; }
</style>

