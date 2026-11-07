<script setup lang="ts">
defineProps<{
  employee: 'database' | 'knowledge'
  name: string
  role: string
  outcome: string
  lines: string[]
}>()
</script>

<template>
  <article class="work-status-report" :data-employee="employee" :aria-label="`${name}工作情况回报`">
    <header class="work-status-report__person">
      <span class="work-status-report__mark" aria-hidden="true">{{ name.slice(0, 1) }}</span>
      <div>
        <h3 class="work-status-report__name">{{ name }}</h3>
        <p class="work-status-report__role">{{ role }}</p>
      </div>
    </header>
    <p class="work-status-report__outcome">{{ outcome }}</p>
    <ul class="work-status-report__breakdown">
      <li v-for="line in lines" :key="line">{{ line }}</li>
    </ul>
  </article>
</template>

<style scoped>
.work-status-report {
  display: flex;
  flex-direction: column;
  gap: var(--xc-space-2);
  width: min(40rem, 100%);
  box-sizing: border-box;
  padding: var(--xc-space-3);
  border: 1px solid var(--xc-color-border);
  border-radius: var(--xc-radius-lg);
  background: var(--xc-color-surface);
  color: var(--xc-color-text);
}
.work-status-report__person { display: flex; align-items: center; gap: var(--xc-space-3); }
.work-status-report__mark {
  flex: none;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--xc-color-primary);
  color: var(--xc-color-surface);
  font-size: 13px;
  font-weight: 600;
}
.work-status-report__name { margin: 0; font-size: 1rem; font-weight: 600; line-height: 1.3; }
.work-status-report__role { margin: 0; color: var(--xc-color-text-secondary); font-size: 13px; line-height: 1.4; }
.work-status-report__outcome {
  margin: 0;
  padding-top: var(--xc-space-2);
  border-top: 1px solid var(--xc-color-border);
  line-height: 1.5;
}
.work-status-report__breakdown {
  margin: 0;
  padding: var(--xc-space-2) 0 0;
  border-top: 1px solid var(--xc-color-border);
  list-style: none;
  color: var(--xc-color-text-secondary);
  font-size: 13px;
  line-height: 1.5;
}
</style>
