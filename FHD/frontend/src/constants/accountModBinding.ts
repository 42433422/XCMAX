import { CLIENT_PRIMARY_ERP_MOD_ID } from '@/constants/genericModPack';

/** 太阳鸟演示/交付账号 → 客户主 ERP Mod（与 host_profiles client_primary_erp_mod_id 一致） */
export const SUNBIRD_CLIENT_MOD_ID = CLIENT_PRIMARY_ERP_MOD_ID;

const SUNBIRD_USERNAMES = new Set(['sunbird', 'SUNBIRD']);

export function isSunbirdAccountUsername(username: string | null | undefined): boolean {
  const u = String(username || '').trim();
  if (!u) return false;
  return SUNBIRD_USERNAMES.has(u) || u.toUpperCase() === 'SUNBIRD';
}

/** 登录/会话权益列表合并账号级默认 Mod */
export function augmentEntitledModIdsForAccount(
  username: string | null | undefined,
  entitledModIds: string[] | undefined,
): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const id of entitledModIds || []) {
    const s = String(id || '').trim();
    if (!s || seen.has(s)) continue;
    seen.add(s);
    out.push(s);
  }
  if (isSunbirdAccountUsername(username) && !seen.has(SUNBIRD_CLIENT_MOD_ID)) {
    out.unshift(SUNBIRD_CLIENT_MOD_ID);
    seen.add(SUNBIRD_CLIENT_MOD_ID);
  }
  return out;
}

export function preferredClientModIdForAccount(
  username: string | null | undefined,
): string {
  if (isSunbirdAccountUsername(username)) return SUNBIRD_CLIENT_MOD_ID;
  return '';
}

/** 仅太阳鸟交付账号自动绑定客户主 ERP；管理员/普通企业账号须靠 entitled 显式授权 */
export function shouldBindClientPrimaryErpMod(
  username: string | null | undefined,
  options?: { isAdminAccount?: boolean },
): boolean {
  if (options?.isAdminAccount) return false;
  return isSunbirdAccountUsername(username);
}
