import { ref } from 'vue'

/** 移动端联系页 AI 填表弹窗（挂到 CorpButlerRoot，避免欢迎区卸载时消失） */
export const contactIntakeModalOpen = ref(false)
export const contactIntakeFillCompleted = ref(false)

export function openContactIntakeModal() {
  contactIntakeModalOpen.value = true
}

export function closeContactIntakeModal() {
  contactIntakeModalOpen.value = false
}
