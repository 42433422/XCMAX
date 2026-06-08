<template>
  <div class="wallet-layout">
    <nav class="wallet-tabs" aria-label="钱包分区">
      <router-link :to="{ name: 'wallet' }" class="wallet-tab">资金与记录</router-link>
      <router-link :to="{ name: 'wallet-purchased' }" class="wallet-tab">已购资产</router-link>
    </nav>
    <router-view />
  </div>
</template>

<script setup lang="ts"></script>

<style scoped>
/* 原 App .main-content 的横向 gutter 已下放到各页；钱包区统一左右留白 */
.wallet-layout {
  width: 100%;
  padding: 0 clamp(12px, 3.5vw, 40px);
  box-sizing: border-box;
}
.wallet-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 20px;
  flex-wrap: wrap;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.wallet-tab {
  display: inline-block;
  padding: 10px 16px 12px;
  font-size: 14px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.5);
  text-decoration: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition:
    color 0.15s,
    border-color 0.15s;
}
.wallet-tab:hover {
  color: rgba(255, 255, 255, 0.85);
}
.wallet-tab.router-link-active {
  color: #fff;
  border-bottom-color: #6366f1;
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Light theme overrides
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
html[data-workbench-theme='light'] .wallet-tabs {
  border-bottom-color: rgba(0, 0, 0, 0.08);
}
html[data-workbench-theme='light'] .wallet-tab {
  color: #86868b;
}
html[data-workbench-theme='light'] .wallet-tab:hover {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .wallet-tab.router-link-active {
  color: #1d1d1f;
  border-bottom-color: #0071e3;
}
</style>
