/**
 * StitchStage 常量（由 StitchStage.vue 原文机械切分而来，数值与语义保持不变）。
 */

/** 中键 = auxiliary button */
export const MIDDLE_BUTTON = 1

/** 缩放工具栏：下限 / 步进 / 上限 */
export const minZoom = 0.25
export const maxZoom = 2.5
export const zoomStep = 0.25

/**
 * 四工位拼接：单格缩放。默认按「舞台视口宽度」反算，使条带 + 外框余量与可视区域接近（全图时 zoom≈100%），
 * 避免固定 3.35 导致画布过宽、长期靠缩小显示。
 */
export const COMPOSED_SCALE_MIN = 0.55
export const COMPOSED_SCALE_MAX = 5.5
export const COMPOSED_SCALE_FALLBACK = 3.35
/** 与 computeFitZoom 内边距一致 */
export const COMPOSED_FIT_PAD = 20
/** 与模板 composedStripW 外框水平余量一致 */
export const COMPOSED_OUTER_WIDTH_EXTRA = 0
/**
 * 默认让横条几乎铺满舞台宽（保留 ~6% 安全留白以避免轻微溢出 / clampPan 抖动），
 * 同时不超过视口高度的安全上限——避免全景空一大片黑底而像素只占左上角。
 */
export const COMPOSED_TARGET_SHRINK = 0.94
/** 视口高度的最大占比上限：strip 高 = baseH × scale，超过此比例则按高反算 scale */
export const COMPOSED_TARGET_HEIGHT_RATIO = 0.78
/** 裁边后逻辑格高约 58px，scale 后低于此像素则人物头部与上半身难以辨认 */
export const COMPOSED_MIN_STATION_H_PX = 96
/** 相邻工位格水平重叠（px），盖住 contain 左右留白与亚像素竖缝，横条视觉上连成一体 */
export const COMPOSED_CELL_OVERLAP_PX = 3
/** 每排八工位：左四无缝 + 过道 + 右四无缝；超过八人换下一排 */
export const COMPOSED_SLOTS_PER_ROW = 8
export const COMPOSED_LEFT_GROUP_SIZE = 4
/** 左四与右四之间的过道宽度（随格宽缩放） */
export const COMPOSED_MID_GAP_MIN_PX = 36
export const COMPOSED_MID_GAP_RATIO = 0.48
/** 多排之间的垂直间距（仅超过一排时出现） */
export const COMPOSED_ROW_GAP_PX = 10
/** 与 `.stitch-composed` 外框余量一致（无边框/内边距时为 0） */
export const COMPOSED_ROOT_VERTICAL_CHROME = 0

/**
 * 横拼格宽/高的「逻辑画布」：素材若是高清大图（远大于像素精灵），natural 尺寸会把单格算成上千像素，
 * scale 被下限夹死后仍塞不进视口，表现为工位层空白或错位。此时回退设计稿 80×58 做布局，图片仍 object-fit 缩进格内。
 */
export const COMPOSED_DESK_LAYOUT_MAX_DIM = 240
