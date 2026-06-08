/** localStorage：普通界面下是否走专业意图 API（档位 UI 关闭时不应启用） */
export const PRO_INTENT_EXPERIENCE_KEY = 'xcagi_pro_intent_experience'

/**
 * 客户端本地档位 UI（顶栏角标、侧栏普通/专业切换、聊天页意图体验勾选）。
 * 等级与报价改由服务端下发后再开启；关闭时统一按普通级基线运行。
 */
export const CLIENT_MODE_TIERS_UI_ENABLED = false

export function isClientModeTiersUiEnabled(): boolean {
  return CLIENT_MODE_TIERS_UI_ENABLED
}

/** 清除本地档位偏好，避免隐藏 UI 后仍走专业意图链路 */
export function resetClientModeTierLocalState(): void {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(PRO_INTENT_EXPERIENCE_KEY, '0')
  } catch {
    /* ignore */
  }
}
