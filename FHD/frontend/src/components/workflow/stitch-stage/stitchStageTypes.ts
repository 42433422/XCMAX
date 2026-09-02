/**
 * StitchStage 共享类型（由 StitchStage.vue 原文机械切分而来）。
 */
import type { YuangongStitchHotspot } from '@/constants/yuangongStitchHotspots'
import type { StitchEmployeePlacement } from '@/constants/yuangongStitchPlacements'
import type { WorkflowEmployeeDeskRow } from '@/composables/useWorkflowEmployeeDesks'
import type { EnterpriseOrgLayer } from '@/constants/enterpriseWorkflowEstablishment'

/** StitchStage 对外 props（与原 defineProps 完全一致） */
export type StitchStageProps = {
  /** tutorial：底图 + 可选锚点叠层；composed：每排左四+过道+右四，按人数自动多排 */
  mode?: 'tutorial' | 'composed'
  imageSrc: string
  selectedEmpId: string | null
  hotspots: YuangongStitchHotspot[]
  /** 用于热点按钮的无障碍名称解析 */
  resolveHotspotLabel?: (empId: string) => string
  /** 与右侧列表同源；tutorial 模式可在图上叠层，composed 模式用于四格 */
  desks?: WorkflowEmployeeDeskRow[]
  stationPlacements?: StitchEmployeePlacement[]
  resolveStationAriaLabel?: (empId: string) => string
  /**
   * composed：是否在条带下铺一张横向全景（默认 `stitch-tutorial.png`，可用 `imageSrc` 覆盖）。
   * 为 false 时仍用逐格 desk 叠在渐变底上。
   */
  useComposedPanorama?: boolean
  /** pixel：像素风舞台；office：与员工空间 / 六部门浅色主题对齐 */
  visualSkin?: 'pixel' | 'office'
  /**
   * composed 布局：strip = 每排左四+过道+右四横拼；establishment = 企业六编制列式工位图。
   */
  composedLayout?: 'strip' | 'establishment'
}

/** composed 工位槽位（员工行 + id） */
export type StitchComposedSlot = { empId: string; row: WorkflowEmployeeDeskRow }

/** 每排左四 + 右四分组 */
export type StitchComposedRowGroups = { left: StitchComposedSlot[]; right: StitchComposedSlot[] }

/** 企业编制列（zone + 槽位） */
export type StitchEstablishmentColumn = { zone: EnterpriseOrgLayer; slots: StitchComposedSlot[] }
