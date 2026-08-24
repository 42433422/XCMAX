<template>
  <div v-if="loading" class="page-view host-mod-loading" role="status" aria-live="polite" aria-busy="true">
    <div class="host-mod-loading__surface">
      <span class="host-mod-loading__pulse" aria-hidden="true"></span>
      <div>
        <strong>正在准备业务工作区</strong>
        <p>加载内置组件与当前组织配置…</p>
      </div>
    </div>
  </div>
  <component :is="View" v-else v-bind="bindProps" />
</template>

<script setup lang="ts">
import { computed, useAttrs } from 'vue'
import { useAdminModHostView } from '@/composables/useAdminModHostView'

defineOptions({ inheritAttrs: false })

const props = defineProps<{
  modId: string
  view: string
  title?: string
}>()

const attrs = useAttrs()
const { View, modProps, loading } = useAdminModHostView(props.modId, props.view, props.title || props.view.replace(/View$/, ''))

const bindProps = computed(() => ({ ...modProps, ...attrs }))
</script>

<style scoped>
.host-mod-loading {
  display: grid;
  min-height: 320px;
  place-items: center;
  padding: 32px;
}

.host-mod-loading__surface {
  display: flex;
  width: min(420px, 100%);
  align-items: center;
  gap: 16px;
  padding: 20px 22px;
  border: 1px solid rgba(47, 111, 237, 0.12);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.78);
  box-shadow: 0 18px 44px rgba(28, 67, 138, 0.08);
  color: #17335f;
}

.host-mod-loading__surface p {
  margin: 5px 0 0;
  color: #71809a;
  font-size: 13px;
}

.host-mod-loading__pulse {
  width: 13px;
  height: 13px;
  flex: 0 0 auto;
  border: 4px solid rgba(47, 111, 237, 0.17);
  border-top-color: #2f6fed;
  border-radius: 50%;
  animation: host-mod-spin 0.8s linear infinite;
}

@keyframes host-mod-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
