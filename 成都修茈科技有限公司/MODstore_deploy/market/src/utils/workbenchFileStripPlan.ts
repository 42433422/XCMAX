/** 顶栏 `wb-home-file-strip` 最多同时露出的「已生成/下载」卡片数（不含上传附件）。 */
export const WB_HEADER_FILE_STRIP_MAX_VISIBLE = 3

/** 输入区 `wb-composer-file-stack` 最多同时露出的待发送附件卡片数。 */
export const WB_COMPOSER_ATTACHMENT_MAX_VISIBLE = 5

export type HeaderFileStripPlan = {
  stripAttachmentCount: number
  stripGeneratedCount: number
  overflowAttachmentCount: number
  overflowGeneratedCount: number
  overflowCount: number
}

export type HeaderGeneratedStripPlan = {
  stripGeneratedCount: number
  overflowGeneratedCount: number
  overflowCount: number
}

export type ComposerAttachmentStripPlan = {
  visibleCount: number
  overflowCount: number
}

/** 顶栏仅展示已生成/下载文件（与底部上传区隔离）。 */
export function planHeaderGeneratedStrip(
  generatedCount: number,
  maxVisible: number = WB_HEADER_FILE_STRIP_MAX_VISIBLE,
): HeaderGeneratedStripPlan {
  const cap = Math.max(0, Math.floor(maxVisible))
  const gen = Math.max(0, generatedCount)
  const stripGeneratedCount = Math.min(gen, cap)
  const overflowGeneratedCount = gen - stripGeneratedCount
  return {
    stripGeneratedCount,
    overflowGeneratedCount,
    overflowCount: overflowGeneratedCount,
  }
}

/** 输入区待发送附件可见数量；超出收入 AI 管家。 */
export function planComposerAttachmentStrip(
  attachmentCount: number,
  maxVisible: number = WB_COMPOSER_ATTACHMENT_MAX_VISIBLE,
): ComposerAttachmentStripPlan {
  const cap = Math.max(0, Math.floor(maxVisible))
  const att = Math.max(0, attachmentCount)
  const visibleCount = Math.min(att, cap)
  return {
    visibleCount,
    overflowCount: att - visibleCount,
  }
}

/**
 * @deprecated 顶栏已改为仅已生成文件；保留供旧测试与兼容引用。
 * 附件优先占满条带配额，剩余槽位给已生成文件；超出部分收入 AI 管家。
 */
export function planHeaderFileStrip(
  attachmentCount: number,
  generatedCount: number,
  maxVisible: number = WB_HEADER_FILE_STRIP_MAX_VISIBLE,
): HeaderFileStripPlan {
  const cap = Math.max(0, Math.floor(maxVisible))
  const att = Math.max(0, attachmentCount)
  const gen = Math.max(0, generatedCount)

  let stripAttachmentCount = Math.min(att, cap)
  let remaining = cap - stripAttachmentCount
  let stripGeneratedCount = Math.min(gen, remaining)
  remaining -= stripGeneratedCount

  // 已生成 Office 文件优先露至少 1 张卡片（避免附件占满条带后「已生成」完全不可见）
  if (gen > 0 && stripGeneratedCount === 0 && stripAttachmentCount > 0) {
    stripAttachmentCount = Math.max(0, stripAttachmentCount - 1)
    stripGeneratedCount = 1
  }

  const overflowAttachmentCount = att - stripAttachmentCount
  const overflowGeneratedCount = gen - stripGeneratedCount

  return {
    stripAttachmentCount,
    stripGeneratedCount,
    overflowAttachmentCount,
    overflowGeneratedCount,
    overflowCount: overflowAttachmentCount + overflowGeneratedCount,
  }
}
