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
.route-fallback__card { max-width: 520px; padding: 32px 28px; border: 1px solid rgba(15, 76, 129, .1); border-radius: 16px; background: rgba(255, 255, 255, .96); box-shadow: 0 4px 18px rgba(15, 76, 129, .07); text-align: center; color: #172033; }
.route-fallback__icon { color: #1677ff; font-size: 34px; }
.route-fallback__card h2 { margin: 12px 0 8px; font-size: 18px; }
.route-fallback__card p { margin: 0; color: #64748b; font-size: 13px; line-height: 1.7; }
.route-fallback__card code { padding: 1px 6px; border-radius: 6px; background: #f1f5f9; color: #334155; word-break: break-all; }
.route-fallback__actions { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; margin-top: 18px; }
.route-fallback__btn { height: 34px; padding: 0 14px; border: 1px solid #d0d7e2; border-radius: 8px; background: #fff; color: #172033; font-size: 13px; cursor: pointer; }
.route-fallback__btn.is-primary { border-color: #1677ff; background: #1677ff; color: #fff; }
</style>
