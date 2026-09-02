import { resolveEnterpriseModStack } from '@/utils/enterpriseModStackApi'
import { resolveEnterpriseOrgLayerForCatalogItem } from '@/constants/enterpriseWorkflowEstablishment'
import {
  catalogStoreCollection,
  STORE_COLLECTION_HOST_FOUNDATION,
  STORE_COLLECTION_INDUSTRY_MOD,
  STORE_COLLECTION_OFFICE_AUX,
  STORE_COLLECTION_OFFICE_EMPLOYEE,
  STORE_COLLECTION_WORKFLOW_EMPLOYEE,
} from '@/constants/genericModPack'
import type { EnterpriseOrgLayer } from '@/constants/enterpriseWorkflowEstablishment'
import type { ModStoreState, StoreModRow } from './useModStoreState'

export interface ModStoreMeta {
  modIconClass: (mod: StoreModRow) => string
  collectionLabel: (mod: StoreModRow) => string
  enterpriseLayerLabel: (mod: StoreModRow) => string
  enterpriseLayerTagStyle: (mod: StoreModRow) => Record<string, string>
  enterpriseModLabel: (mod: StoreModRow) => string
  isEmployeePackItem: (mod?: StoreModRow | null) => boolean
  marketItemKindLabel: (mod: StoreModRow) => string
  installSuccessMessage: (mod: StoreModRow, onboardNote?: string) => string
  marketModUrl: (mod: StoreModRow) => string
  resolveEnterpriseStack: () => Promise<void>
}

/** 标签/图标域（由 ModStore.vue 机械切出，行为不变）：卡片图标、企业层标签、跳转链接等纯派生逻辑 */
export function useModStoreMeta(state: ModStoreState, { marketBaseUrl }: { marketBaseUrl: string }): ModStoreMeta {
  const modIconClass = (mod: StoreModRow): string => {
    const sc = catalogStoreCollection(mod)
    if (sc === STORE_COLLECTION_HOST_FOUNDATION) return 'fa fa-cubes'
    if (sc === STORE_COLLECTION_OFFICE_EMPLOYEE) return 'fa fa-file-text-o'
    if (sc === STORE_COLLECTION_OFFICE_AUX) return 'fa fa-bar-chart'
    if (sc === STORE_COLLECTION_WORKFLOW_EMPLOYEE) return 'fa fa-users'
    if (sc === STORE_COLLECTION_INDUSTRY_MOD) return 'fa fa-industry'
    return mod?.icon || 'fa fa-puzzle-piece'
  }

  const collectionLabel = (mod: StoreModRow): string => {
    const sc = catalogStoreCollection(mod)
    if (sc === STORE_COLLECTION_HOST_FOUNDATION) return '宿主基础员工'
    if (sc === STORE_COLLECTION_OFFICE_EMPLOYEE) return '办公员工包'
    if (sc === STORE_COLLECTION_OFFICE_AUX) return '办公附属包1'
    if (sc === STORE_COLLECTION_WORKFLOW_EMPLOYEE) return '工作流员工'
    if (sc === STORE_COLLECTION_INDUSTRY_MOD) return '行业扩展'
    return ''
  }

  const enterpriseLayerForMod = (mod: StoreModRow): EnterpriseOrgLayer | undefined =>
    resolveEnterpriseOrgLayerForCatalogItem(mod || {})

  const enterpriseLayerLabel = (mod: StoreModRow): string => {
    const layer = enterpriseLayerForMod(mod)
    return layer ? `${layer.code} ${layer.label}` : ''
  }

  const isEmployeePackItem = (mod?: StoreModRow | null): boolean =>
    String(mod?.artifact || '')
      .trim()
      .toLowerCase() === 'employee_pack'

  const enterpriseModLabel = (mod: StoreModRow): string => {
    const art = String(mod?.artifact || '')
      .trim()
      .toLowerCase()
    if (art !== 'employee_pack' && art !== 'mod') return ''
    const label = state.enterpriseStackLabel.value
    return label ? `企业 Mod：${label}` : ''
  }

  const marketItemKindLabel = (mod: StoreModRow): string => (isEmployeePackItem(mod) ? '员工' : '扩展 Mod')

  const installSuccessMessage = (mod: StoreModRow, onboardNote = ''): string => {
    const kind = marketItemKindLabel(mod)
    return `${kind} ${mod.name} 安装成功！${onboardNote}`
  }

  const enterpriseLayerTagStyle = (mod: StoreModRow): Record<string, string> => {
    const layer = enterpriseLayerForMod(mod)
    if (!layer) return {}
    return {
      color: layer.color,
      borderColor: `${layer.color}66`,
      background: `${layer.color}14`,
    }
  }

  const marketModUrl = (mod: StoreModRow): string => {
    const id = encodeURIComponent(mod.pkg_id || mod.id || '')
    return `${marketBaseUrl}/mods/${id}`
  }

  const resolveEnterpriseStack = async (): Promise<void> => {
    const stack = await resolveEnterpriseModStack()
    state.enterpriseStackLabel.value = stack.stackLabel
  }

  return {
    modIconClass,
    collectionLabel,
    enterpriseLayerLabel,
    enterpriseLayerTagStyle,
    enterpriseModLabel,
    isEmployeePackItem,
    marketItemKindLabel,
    installSuccessMessage,
    marketModUrl,
    resolveEnterpriseStack,
  }
}
