/**
 * `员工.png`（576×1024）上的可点击功能区，坐标为相对原图的百分比 0–100。
 * 量法与 `yuangongStitchHotspots.ts` 相同。
 */
export type YuangongEmployeeHotspot = {
  id: string
  /** 路由 name（vue-router） */
  routeName: string
  leftPct: number
  topPct: number
  widthPct: number
  heightPct: number
  /** 可见说明 / 屏幕阅读器 */
  label: string
  ariaLabel?: string
}

/**
 * 右侧三本蓝色资料夹 → 原材料仓库（业务上的「库表/库存」入口）
 */
export const YUANGONG_EMPLOYEE_HOTSPOTS: YuangongEmployeeHotspot[] = [
  {
    id: 'binders-database',
    routeName: 'materials',
    leftPct: 66,
    topPct: 34,
    widthPct: 28,
    heightPct: 24,
    label: '资料库（原材料仓库）',
    ariaLabel: '打开原材料仓库，查看库存与物料数据',
  },
]
