import {
  XCAGI_AI_DEVELOPER_MODE_KEY,
  XCAGI_AI_ELEVATED_TOKEN_KEY
} from '@/utils/xcagiStorageKeys';

/** P1 默认；开启开发者模式且填写提升口令后与服务器 FHD_AI_ELEVATED_TOKEN 一致则为 P2。 */
export function getAiTierHttpHeaders(): Record<string, string> {
  try {
    const dev = window.localStorage.getItem(XCAGI_AI_DEVELOPER_MODE_KEY) === '1';
    const tok = String(window.localStorage.getItem(XCAGI_AI_ELEVATED_TOKEN_KEY) || '').trim();
    if (dev && tok) {
      return {
        'X-XCAGI-AI-Tier': 'p2',
        'X-XCAGI-Elevated-Token': tok
      };
    }
  } catch {
    /* ignore */
  }
  return { 'X-XCAGI-AI-Tier': 'p1' };
}
