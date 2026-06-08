<template>
  <div class="page-view mod-required-view">
    <div class="page-content">
      <div class="card" style="max-width: 560px; margin: 48px auto; padding: 24px;">
        <h2 style="margin: 0 0 12px;">{{ title || '功能未启用' }}</h2>
        <p class="muted" style="margin: 0 0 16px; line-height: 1.6;">
          干净通用宿主未安装 Mod <code>{{ modId }}</code>。
          可从 <code>mods-export-2026-06-07/</code> 回装到 <code>FHD/mods/</code> 后刷新。
        </p>
        <router-link class="btn btn-secondary btn-sm" :to="{ name: 'chat' }">返回智能对话</router-link>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  modId: string
  title?: string
}>()
</script>
