<script setup lang="ts">
import { useModAuthoringContext } from '../composables/useModAuthoringContext'

const { checklist, artifactNote } = useModAuthoringContext()
</script>

<template>
  <div>
    <h3 v-if="$slots.title" class="sub-title">
      <slot name="title" />
    </h3>
    <h3 v-else class="sub-title">结构</h3>
    <ul class="checklist">
      <li v-for="row in checklist" :key="row.key" :class="{ ok: row.ok, warn: !row.ok }">
        <span class="mark">{{ row.ok ? '✓' : '○' }}</span>
        {{ row.label }}
        <span v-if="row.hint" class="hint">{{ row.hint }}</span>
      </li>
    </ul>
    <div v-if="artifactNote" class="artifact-note">{{ artifactNote }}</div>
  </div>
</template>
