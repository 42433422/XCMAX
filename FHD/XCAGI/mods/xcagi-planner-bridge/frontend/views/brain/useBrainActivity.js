import { ref } from 'vue'

/** 活动流（拆分自 BrainView.vue，逻辑不变） */
export function useBrainActivity() {
  const activityLines = ref([{ ts: '--:--:--', msg: '等待接入事件源…' }])

  function pushActivity(msg) {
    const d = new Date()
    const ts = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
    activityLines.value = [{ ts, msg }, ...activityLines.value].slice(0, 12)
  }

  return { activityLines, pushActivity }
}
