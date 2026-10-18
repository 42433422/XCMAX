<template>
  <RouteFallbackPanel v-if="failed" mode="render-error" :path="path" class="route-view-shell" @dismiss="failed = false" />
  <slot v-else />
</template>

<script setup lang="ts">
import { getCurrentInstance, nextTick, onErrorCaptured, ref, watch } from 'vue'
import RouteFallbackPanel from './RouteFallbackPanel.vue'

/** 管理端页面渲染/初始化出错时显示可见提示，代替空白主区域；错误照常交给全局 errorHandler 记录。 */
const props = defineProps<{ path: string }>()
const failed = ref(false)
const self = getCurrentInstance()
watch(() => props.path, () => { failed.value = false })
onErrorCaptured((_err, _instance, info) => {
  // 只拦渲染和 setup 阶段（生产构建里 info 是 …#runtime-1 / …#runtime-0）；按钮点击等异步错误不替换整页。
  // 只有页面因此真的没有内容时才换成提示，局部组件出错但页面仍有内容时保持原样。
  if (/^(render function|setup function)$|#runtime-[01]$/.test(String(info))) {
    void nextTick(() => {
      const el = self?.subTree?.el as Node | null | undefined
      if (!el || !String(el.textContent || '').trim()) failed.value = true
    })
  }
  return true
})
</script>
