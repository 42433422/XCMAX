<template>
  <div class="discover-view">
    <header class="discover-view__header">
      <h1>发现</h1>
      <p>工作台、扩展与市场、常用工具</p>
    </header>

    <section class="discover-section">
      <h2>工作台</h2>
      <button type="button" class="discover-cell" @click="openWorkbench">
        <i class="fa fa-th-large" aria-hidden="true"></i>
        <div>
          <strong>工作台</strong>
          <span>MODstore 网页版 · 完整 Mod 能力</span>
        </div>
        <i class="fa fa-chevron-right muted" aria-hidden="true"></i>
      </button>
    </section>

    <section class="discover-section">
      <h2>扩展与市场</h2>
      <button type="button" class="discover-cell" @click="goMods">
        <i class="fa fa-puzzle-piece" aria-hidden="true"></i>
        <div>
          <strong>MOD 市场</strong>
          <span>浏览与安装行业 Mod</span>
        </div>
        <i class="fa fa-chevron-right muted" aria-hidden="true"></i>
      </button>
      <button type="button" class="discover-cell" @click="goTools">
        <i class="fa fa-wrench" aria-hidden="true"></i>
        <div>
          <strong>工具箱</strong>
          <span>更多扩展能力与实用工具</span>
        </div>
        <i class="fa fa-chevron-right muted" aria-hidden="true"></i>
      </button>
    </section>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router';

const router = useRouter();
const modstoreWebUrl = String(
  import.meta.env.VITE_MODSTORE_WEB_URL || 'https://xiu-ci.com/market/workbench/unified',
).replace(/\/$/, '');

function openWorkbench() {
  window.open(modstoreWebUrl, '_blank', 'noopener,noreferrer');
}

function goMods() {
  void router.push({ name: 'mod-store' });
}

function goTools() {
  void router.push({ name: 'tools' });
}
</script>

<style scoped>
.discover-view {
  padding: var(--xc-space-4);
  padding-bottom: calc(72px + env(safe-area-inset-bottom, 0));
  max-width: 720px;
}

.discover-view__header h1 {
  margin: 0 0 4px;
  font-size: var(--xc-font-2xl);
  color: var(--xc-color-text);
}

.discover-view__header p {
  margin: 0 0 var(--xc-space-5);
  color: var(--xc-color-muted);
  font-size: var(--xc-font-sm);
}

.discover-section {
  margin-bottom: var(--xc-space-5);
}

.discover-section h2 {
  margin: 0 0 var(--xc-space-2);
  font-size: var(--xc-font-xs);
  font-weight: var(--xc-font-weight-semibold);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--xc-color-muted);
}

.discover-cell {
  width: 100%;
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: var(--xc-space-3);
  align-items: center;
  padding: var(--xc-space-4);
  margin-bottom: var(--xc-space-2);
  border: 1px solid var(--xc-color-border);
  border-radius: var(--xc-radius-lg);
  background: var(--xc-color-surface);
  text-align: left;
  cursor: pointer;
  transition:
    border-color var(--xc-transition-fast),
    transform var(--xc-transition-fast);
}

.discover-cell:active {
  transform: scale(0.98);
}

.discover-cell strong {
  display: block;
  color: var(--xc-color-text);
  font-size: var(--xc-font-md);
}

.discover-cell span {
  display: block;
  margin-top: 2px;
  color: var(--xc-color-muted);
  font-size: var(--xc-font-sm);
}

.discover-cell > .fa:first-child {
  width: 28px;
  text-align: center;
  color: var(--xc-color-primary);
  font-size: 18px;
}

.muted {
  color: var(--xc-color-disabled);
  font-size: 12px;
}
</style>
