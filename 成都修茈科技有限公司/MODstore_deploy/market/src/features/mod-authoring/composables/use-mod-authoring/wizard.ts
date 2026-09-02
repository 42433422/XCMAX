// 向导草稿：名称/一句话介绍草稿与保存（原单体实现原样迁移；同步 watch 由 façade 注册）。
import { ref } from 'vue'
import type { Ref } from 'vue'
import type { LooseRecord } from '../../types'
import type { Flash, SaveManifest } from './core'

export interface WizardDeps {
  manifestText: Ref<string>
  saveManifest: SaveManifest
  flash: Flash
}

export function createWizard(deps: WizardDeps) {
  const { manifestText, saveManifest, flash } = deps

  const nameDraft = ref('')
  const descriptionDraft = ref('')

  async function saveDescriptionFromWizard() {
    const name = nameDraft.value.trim()
    const desc = descriptionDraft.value.trim()
    if (!name) {
      flash('请填写 Mod 名称', false)
      return false
    }
    if (!desc) {
      flash('请填写一句话介绍', false)
      return false
    }
    let parsed: LooseRecord
    try {
      parsed = JSON.parse(manifestText.value) as LooseRecord
    } catch (e) {
      flash('JSON 解析失败: ' + ((e as Error)?.message || String(e)), false)
      return false
    }
    parsed.name = name
    parsed.description = desc
    const fe = parsed.frontend
    if (fe && typeof fe === 'object' && Array.isArray((fe as LooseRecord).menu)) {
      const menu = (fe as LooseRecord).menu as LooseRecord[]
      if (menu[0] && typeof menu[0] === 'object') {
        menu[0].label = name
      }
    }
    manifestText.value = JSON.stringify(parsed, null, 2)
    await saveManifest({ successMessage: '名称与介绍已保存' })
    return true
  }

  return {
    nameDraft,
    descriptionDraft,
    saveDescriptionFromWizard,
  }
}
