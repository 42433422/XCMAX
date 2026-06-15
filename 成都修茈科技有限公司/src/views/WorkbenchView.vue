<template>
  <div class="workbench">
    <header class="workbench-bar">
      <div class="workbench-bar-inner">
        <h1 class="workbench-title">工作台</h1>
        <nav class="workbench-tabs" aria-label="工作台导航">
          <router-link
            :to="{ name: 'workbench-repository' }"
            class="workbench-tab"
            active-class="workbench-tab--active"
          >
            Mod 仓库
          </router-link>
        </nav>
      </div>
    </header>
    <main class="workbench-main">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.workbench {
  min-height: 100%;
  background: #0a0a0a;
}

.workbench-bar {
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(0, 0, 0, 0.45);
}

.workbench-bar-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 1rem 1rem 0.75rem;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 1rem 1.5rem;
}

.workbench-title {
  margin: 0;
  font-size: 1.125rem;
  font-weight: 600;
  color: #ffffff;
}

.workbench-tabs {
  display: flex;
  gap: 0.25rem;
}

.workbench-tab {
  padding: 0.4rem 0.85rem;
  border-radius: 6px;
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.45);
  text-decoration: none;
}

.workbench-tab:hover {
  color: rgba(255, 255, 255, 0.85);
  background: rgba(255, 255, 255, 0.06);
}

.workbench-tab--active {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.1);
}

.workbench-main {
  flex: 1;
}
</style>
