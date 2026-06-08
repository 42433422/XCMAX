/**
 * 拼接图 `stitch-tutorial.png` 上的可点击热点（相对**原图像素**的百分比 0–100）。
 *
 * 量取方式：在图像编辑器中框选某员工区域，记录 x、y、width、height（像素），则：
 * - leftPct = (x / imageWidth) × 100
 * - topPct = (y / imageHeight) × 100
 * - widthPct = (width / imageWidth) × 100
 * - heightPct = (height / imageHeight) × 100
 *
 * `empId` 须与副窗 / useWorkflowEmployeeDesks 中的 id 一致（如 label_print）。
 * 未在此列出的员工仅出现在右侧列表，图面无热点。
 */
export type YuangongStitchHotspot = {
  empId: string
  leftPct: number
  topPct: number
  widthPct: number
  heightPct: number
  /** 可选，用于按钮无障碍名称 */
  label?: string
}

/** 首期留空：按上图方式填入后，全景页舞台即可点击对应区域选中员工 */
export const YUANGONG_STITCH_HOTSPOTS: YuangongStitchHotspot[] = []
