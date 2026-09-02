<script setup lang="ts">
// 拆分自 HomeView.vue 模板（原第 3–65 行）；模板逐字迁移，点击事件改为 emits，行为不变。
import type { RouteLocationRaw } from 'vue-router'

defineProps<{
  isLoggedIn: boolean
  userLabel: string
  workbenchLink: RouteLocationRaw
  mobileNavOpen: boolean
}>()

defineEmits<{
  (e: 'toggle-nav'): void
  (e: 'close-nav'): void
}>()
</script>

<template>
  <header class="landing-nav">
    <div class="container">
      <div class="landing-nav-inner">
        <router-link to="/about" class="landing-logo" @click="$emit('close-nav')">XC AGI</router-link>
        <nav class="landing-nav-links" aria-label="主导航">
          <router-link :to="{ name: 'ai-store' }" class="nav-ghost">AI 市场</router-link>
          <a href="/download" class="nav-ghost" target="_blank" rel="noopener">软件下载</a>
          <router-link :to="workbenchLink" class="nav-ghost">进入工作台</router-link>
          <router-link
            v-if="!isLoggedIn"
            to="/register"
            class="nav-primary"
          >免费注册</router-link>
          <span
            v-else
            class="nav-user"
            :title="userLabel"
          >{{ userLabel }}</span>
        </nav>
        <button
          type="button"
          class="landing-nav-toggle"
          :class="{ 'landing-nav-toggle--open': mobileNavOpen }"
          :aria-label="mobileNavOpen ? '关闭菜单' : '打开菜单'"
          :aria-expanded="mobileNavOpen"
          aria-controls="landing-mobile-nav"
          @click="$emit('toggle-nav')"
        >
          <span aria-hidden="true"></span>
          <span aria-hidden="true"></span>
          <span aria-hidden="true"></span>
        </button>
      </div>
    </div>
    <div
      v-if="mobileNavOpen"
      class="landing-nav-overlay"
      aria-hidden="true"
      @click="$emit('close-nav')"
    ></div>
    <nav
      id="landing-mobile-nav"
      class="landing-nav-drawer"
      :class="{ 'landing-nav-drawer--open': mobileNavOpen }"
      aria-label="移动端菜单"
    >
      <router-link :to="{ name: 'ai-store' }" class="landing-nav-drawer-link" @click="$emit('close-nav')">AI 市场</router-link>
      <a href="/download" class="landing-nav-drawer-link" target="_blank" rel="noopener" @click="$emit('close-nav')">软件下载</a>
      <router-link :to="workbenchLink" class="landing-nav-drawer-link" @click="$emit('close-nav')">
        {{ isLoggedIn ? '进入工作台' : '登录 / 工作台' }}
      </router-link>
      <router-link :to="{ name: 'plans' }" class="landing-nav-drawer-link" @click="$emit('close-nav')">会员方案</router-link>
      <a href="/services.html" class="landing-nav-drawer-link" @click="$emit('close-nav')">官网产品中心</a>
      <router-link
        v-if="!isLoggedIn"
        to="/register"
        class="landing-nav-drawer-link landing-nav-drawer-link--primary"
        @click="$emit('close-nav')"
      >免费注册</router-link>
      <span v-else class="landing-nav-drawer-user" :title="userLabel">{{ userLabel }}</span>
    </nav>
  </header>
</template>

<style scoped src="./home-view.css"></style>
