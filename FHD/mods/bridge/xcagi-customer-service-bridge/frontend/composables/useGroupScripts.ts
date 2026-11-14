import { computed } from 'vue'
import { appAlert } from '@/utils/appDialog'
import type { WorkbenchCtx } from './workbenchContext'

/** 群组话术生成与复制。 */
export function useGroupScripts(ctx: WorkbenchCtx) {
  const { deps } = ctx
  const { currentStageId } = deps

  const groupScriptActionLabel = computed(() => {
    if (currentStageId.value === 'intake_done') return '需求确认'
    if (currentStageId.value === 'negotiating') return '议价'
    return '报价'
  })

  function groupClientDisplayName() {
    const n = ctx.intakePrefillGreetingName().trim()
    return n || '您好'
  }

  function groupScriptForStage(): string {
    const name = groupClientDisplayName()
    if (currentStageId.value === 'intake_done') {
      return (
        `${name}，您好！\n\n` +
        '我们已收到并核对您提交的需求信息。请确认目前理解的范围是否准确：\n' +
        '· 实施范围：（请按档案补充）\n' +
        '· 期望交付时间：（请补充）\n' +
        '· 需对接的系统：（请补充）\n\n' +
        '若无补充，我们将在 1 个工作日内于本群发送正式报价方案；有变更请直接在本群回复即可。'
      )
    }
    if (currentStageId.value === 'negotiating') {
      return (
        `${name}，感谢您的反馈。\n\n` +
        '关于价格与交付条件，我们可以在以下范围内协调（请按实际情况修改后发送）：\n' +
        '· 可调整项：范围精简 / 分期交付 / 付款方式等\n' +
        '· 当前方案报价：（请填写金额与说明）\n\n' +
        '您看这样是否可行？确认后我们更新方案并进入合同签署流程。'
      )
    }
    return (
      `${name}，您好！\n\n` +
      '根据目前确认的需求范围，我方初步报价如下（请按实际情况填写后发送）：\n' +
      '· 实施范围：\n' +
      '· 费用：    元（含税/不含税请说明）\n' +
      '· 周期：约    周\n\n' +
      '详细说明见上文/附件。如需调整范围或预算，请在本群直接回复，我们再议。'
    )
  }

  async function copyGroupScript(text: string) {
    if (!text.trim()) return
    try {
      await navigator.clipboard.writeText(text)
      await appAlert('已复制话术')
    } catch {
      await appAlert('复制失败')
    }
  }

  return {
    groupScriptActionLabel,
    groupScriptForStage,
    copyGroupScript,
  }
}