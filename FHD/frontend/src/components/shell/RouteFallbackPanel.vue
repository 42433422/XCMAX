<template>
  <main class="route-fallback" role="alert" :aria-label="TITLES[mode]">
    <section class="route-fallback__card">
      <i class="fa route-fallback__icon" :class="mode === 'not-found' ? 'fa-compass' : 'fa-refresh'" aria-hidden="true"></i>
      <h2>{{ TITLES[mode] }}</h2>
      <p v-if="mode === 'not-found'">地址 <code>{{ path }}</code> 没有对应页面，可能是链接写错或页面已调整。可以从左侧导航进入，或回到首页。</p>
      <p v-else-if="mode === 'chunk-error'">打开 <code>{{ path }}</code> 时页面文件没有加载成功，可能是网络中断或刚发布了新版本。刷新后会重新加载。</p>
      <p v-else>打开 <code>{{ path }}</code> 时页面内容没有显示出来，可能是返回的数据和页面预期不一致。可以刷新重试，或先去其他页面。</p>
      <div class="route-fallback__actions">
        <button v-if="mode !== 'not-found'" type="button" class="route-fallback__btn is-primary" @click="reload">刷新页面</button>
        <button type="button" class="route-fallback__btn" :class="{ 'is-primary': mode === 'not-found' }" @click="goHome">回到首页</button>
        <button type="button" class="route-fallback__btn" @click="goBack">返回上一页</button>
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

const props = withDefaults(defineProps<{ mode?: 'not-found' | 'chunk-error' | 'render-error'; path?: string }>(), { mode: 'not-found', path: '' })
const TITLES = { 'not-found': '没有找到这个页面', 'chunk-error': '页面资源加载失败', 'render-error': '页面显示出错' } as const
const emit = defineEmits<{ dismiss: [] }>()
const router = useRouter()

function goHome() {
  emit('dismiss')
  void router.push('/')
}
function goBack() {
  emit('dismiss')
  router.back()
}
function reload() {
  const base = String(import.meta.env.BASE_URL || '/').replace(/\/$/, '')
  window.location.assign(`${base}${props.path || '/'}`)
}
</script>

<style scoped>
.route-fallback { display: flex; flex: 1 1 auto; align-items: center; justify-content: center; padding: 32px 20px; box-sizing: border-box; overflow: auto; }
.route-fallback__card { max-width: 520px; padding: 32px 28px; border: 1px solid var(--xc-color-border); border-radius: var(--xc-radius-xl); background: var(--xc-color-surface); box-shadow: var(--xc-shadow-sm); text-align: center; color: var(--xc-color-text); }
.route-fallback__icon { color: var(--xc-color-primary); font-size: 34px; }
.route-fallback__card h2 { margin: 12px 0 8px; font-size: 18px; }
.route-fallback__card p { margin: 0; color: var(--xc-color-muted); font-size: var(--xc-font-md); line-height: 1.7; }
.route-fallback__card code { padding: 1px 6px; border-radius: var(--xc-radius-sm); background: var(--xc-color-surface-3); color: var(--xc-color-text-secondary); word-break: break-all; }
.route-fallback__actions { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; margin-top: 18px; }
.route-fallback__btn { min-height: 36px; padding: 0 14px; border: 1px solid var(--xc-color-border-strong); border-radius: var(--xc-radius-md); background: var(--xc-color-surface); color: var(--xc-color-text); font: inherit; cursor: pointer; }
.route-fallback__btn.is-primary { border-color: var(--xc-color-primary); background: var(--xc-color-primary); color: var(--xc-color-surface); }
.route-fallback__btn:focus-visible { outline: 2px solid var(--xc-color-primary); outline-offset: 3px; }
</style>
