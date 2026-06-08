/**
 * 全景拼接图上叠加的实时工位（`YuangongStation`）锚点。
 * 坐标为相对原图宽高的百分比；锚点默认在工位**底部中心**（像站在地面上）。
 *
 * 若与 `stitch-tutorial.png` 里桌椅位置对不齐，请在此改 leftPct/topPct/scale；
 * 扩展包员工可追加条目，`empId` 须与 manifest / 列表一致。
 */
export type StitchEmployeePlacement = {
  empId: string
  leftPct: number
  topPct: number
  /** 相对组件基准 80×58 的放大倍数，默认 4 */
  scale?: number
}

/** 内置四条占位：沿画面偏下横排，需按你的原图微调 */
export const YUANGONG_STITCH_STATION_PLACEMENTS: StitchEmployeePlacement[] = [
  { empId: 'label_print', leftPct: 14, topPct: 82, scale: 4.2 },
  { empId: 'shipment_mgmt', leftPct: 36, topPct: 82, scale: 4.2 },
  { empId: 'receipt_confirm', leftPct: 62, topPct: 82, scale: 4.2 },
  { empId: 'wechat_msg', leftPct: 86, topPct: 82, scale: 4.2 },
]
