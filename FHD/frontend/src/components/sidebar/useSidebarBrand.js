/**
 * 侧边栏品牌区：Logo 兜底链、标题/副标题、已加载 Mod 徽标（拆分自 components/Sidebar.vue，行为保持一致）。
 */
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useIndustryStore } from '@/stores/industry'
import { useModsStore } from '@/stores/mods'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { ADMIN_OPERATOR_BRAND_SUBTITLE, ADMIN_OPERATOR_BRAND_TITLE } from '@/constants/adminOperatorNav'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { DEFAULT_INDUSTRY_ID } from '@/constants/industryDefaults'
import { getIndustryPreset } from '@/constants/industryPresets'
import { useIndustryUiText } from '@/composables/useIndustryUiText'
import { isPlatformShellModeEnabled } from '@/constants/platformShellMode'

export function useSidebarBrand() {
  const isSandboxMode = new URLSearchParams(window.location.search).has('sandbox')
  const isPlatformShellMode = isPlatformShellModeEnabled()

  function startupAsset(fileName) {
    const base = String(import.meta.env.BASE_URL || '/')
    return `${base}startup/${fileName}`.replace(/([^:]\/)\/+/g, '$1')
  }

  /** 与开屏 / 登录同源：带 XC 字标；PNG 透明底，JPG 作兜底 */
  const brandLogoCandidates = [startupAsset('xc-logo-text.png'), startupAsset('xc-logo-text.jpg'), startupAsset('xc-logo-base.jpg')]

  const industryStore = useIndustryStore()
  const modsStore = useModsStore()
  const accountProfileStore = useAccountProfileStore()
  const { modsForUi } = storeToRefs(modsStore)
  const { isAdminAccount, displayBrand } = storeToRefs(accountProfileStore)
  const { assistantSubtitle } = useIndustryUiText()

  function shortModLabel(name) {
    const s = String(name || '').trim()
    if (!s) return 'Mod'
    return s.length > 8 ? `${s.slice(0, 7)}…` : s
  }

  const loadedModChips = computed(() =>
    (modsForUi.value || []).map((m) => ({
      id: m.id,
      shortLabel: shortModLabel((m.name && String(m.name).trim()) || m.id),
      fullName: (m.name && String(m.name).trim()) || m.id,
    })),
  )

  const primaryModChip = computed(() => {
    const chips = loadedModChips.value
    return chips.length > 0 ? chips[0] : null
  })

  const sidebarLogoSrc = ref(brandLogoCandidates[0])
  let brandLogoFallbackIndex = 0

  function onSidebarLogoError() {
    brandLogoFallbackIndex += 1
    if (brandLogoFallbackIndex < brandLogoCandidates.length) {
      sidebarLogoSrc.value = brandLogoCandidates[brandLogoFallbackIndex]
      return
    }
    if (sidebarLogoSrc.value !== `${import.meta.env.BASE_URL}vite.svg`) {
      sidebarLogoSrc.value = `${import.meta.env.BASE_URL}vite.svg`
    }
  }
  const sidebarSystemSubtitle = assistantSubtitle

  const sidebarBrandTitle = computed(() => {
    if (isAdminConsoleSpa() && isAdminAccount.value) return ADMIN_OPERATOR_BRAND_TITLE
    if (isSandboxMode) return '沙箱测试'
    if (isPlatformShellMode) return 'XCAGI 平台壳'
    const id = String(industryStore.currentIndustryId || DEFAULT_INDUSTRY_ID).trim() || DEFAULT_INDUSTRY_ID
    const name = getIndustryPreset(id).name
    return name.includes('助手') ? name : `${name}助手`
  })

  const sidebarBrandSubtitle = computed(() => {
    if (isAdminConsoleSpa() && isAdminAccount.value) return ADMIN_OPERATOR_BRAND_SUBTITLE
    if (isSandboxMode) return 'MODstore 在线测试'
    if (isPlatformShellMode) return '通用宿主 · 能力由 Mod 提供'
    const brand = String(displayBrand.value || '').trim()
    if (brand) return brand
    return sidebarSystemSubtitle.value
  })

  return {
    sidebarLogoSrc,
    onSidebarLogoError,
    sidebarBrandTitle,
    sidebarBrandSubtitle,
    primaryModChip,
  }
}
