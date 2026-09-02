// 行业预设：选择与应用到 manifest（原单体实现原样迁移；modData 的同步 watch 由 façade 注册）。
import { computed, ref } from 'vue'
import type { Ref } from 'vue'
import { getIndustryPreset, listIndustryPresets, manifestIndustryFromPreset } from '@/constants/industryPresets'
import type { LooseRecord } from '../../types'
import type { Flash, SaveManifest } from './core'

export interface IndustryDeps {
  manifestText: Ref<string>
  saveManifest: SaveManifest
  flash: Flash
}

export function createIndustry(deps: IndustryDeps) {
  const { manifestText, saveManifest, flash } = deps

  const industryPresetList = listIndustryPresets()
  const selectedIndustryPreset = ref('通用')
  const selectedIndustryScenario = computed(() => getIndustryPreset(selectedIndustryPreset.value).scenario)

  async function applyIndustryPresetToManifest() {
    let parsed: LooseRecord
    try {
      parsed = JSON.parse(manifestText.value) as LooseRecord
    } catch (e) {
      flash('JSON 解析失败: ' + ((e as Error)?.message || String(e)), false)
      return
    }
    parsed.industry = manifestIndustryFromPreset(selectedIndustryPreset.value)
    const preset = getIndustryPreset(selectedIndustryPreset.value)
    if (parsed.frontend && typeof parsed.frontend === 'object') {
      const fe = parsed.frontend as LooseRecord
      const shell = fe.shell && typeof fe.shell === 'object' ? (fe.shell as LooseRecord) : {}
      fe.shell = shell
      const settings = shell.settings && typeof shell.settings === 'object' ? (shell.settings as LooseRecord) : {}
      shell.settings = settings
      settings.default_industry = preset.id
      settings.industry_options = industryPresetList.map((p) => p.id)
    }
    manifestText.value = JSON.stringify(parsed, null, 2)
    const menuCount = Array.isArray((parsed.frontend as LooseRecord | undefined)?.menu)
      ? ((parsed.frontend as LooseRecord).menu as unknown[]).length
      : 0
    await saveManifest({
      successMessage: `行业已保存：${preset.name}（菜单 ${menuCount} 项）`,
      flashDurationMs: 4000,
    })
  }

  return {
    industryPresetList,
    selectedIndustryPreset,
    selectedIndustryScenario,
    applyIndustryPresetToManifest,
  }
}
