import { ref } from 'vue'

/** 编制图内「客户/管理」视图切换（替代 MODstore authStore） */
const currentMode = ref<'admin' | 'client'>('admin')

export function useMarketAdminGraphAuth() {
  return {
    currentMode,
    setClientMode() {
      currentMode.value = 'client'
    },
    setAdminMode() {
      currentMode.value = 'admin'
    },
  }
}
