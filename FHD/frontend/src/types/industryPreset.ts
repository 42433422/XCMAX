/** 行业 UI 预设类型（与 constants/industryPresets、stores/hostConfig 解耦，避免循环依赖） */

export type IndustryQuickButton = { text: string; label: string }

export type IndustryPreset = {
  id: string
  name: string
  scenario: string
  welcomeIntro: string
  welcomeBullets: string[]
  quickButtons: IndustryQuickButton[]
  placeholderNormal: string
  placeholderPro: string
  menuLabels: Record<string, string>
  uiLabels: Record<string, string>
}
