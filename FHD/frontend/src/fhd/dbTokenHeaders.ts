export const LS_DB_READ_TOKEN = 'xcagi_db_read_token';
export const LS_DB_WRITE_TOKEN = 'xcagi_db_write_token';
export const LS_DB_TOKENS_BY_MOD = 'xcagi_db_tokens_by_mod';

export const FHD_STORED_DB_TOKENS_CHANGED_EVENT = 'fhd:stored-db-tokens-changed';
export const FHD_DB_READ_UNLOCKED_EVENT = 'fhd-db-read-unlocked';
export const FHD_DB_WRITE_UNLOCKED_EVENT = 'fhd-db-write-unlocked';
export const XCAGI_PRODUCTS_SIDEBAR_ACTIVATED = 'xcagi:products-sidebar-activated';
export const XCAGI_PROMPT_DB_READ_TOKEN_EVENT = 'xcagi:prompt-db-read-token';
export const XCAGI_PROMPT_DB_WRITE_TOKEN_EVENT = 'xcagi:prompt-db-write-token';

export type DbTokensStatus = {
  read_token_configured: boolean;
  write_token_configured: boolean;
  active_mod_id?: string;
};

export type ProductsReadLockState = 'open' | 'locked_no_token' | 'locked_bad_token';

export interface ProductsReadProbeOptions {
  allowStoredTokenBypassGrace?: boolean;
}

function clearLegacyTokenStorage(): void {
  if (typeof localStorage === 'undefined') return;
  localStorage.removeItem(LS_DB_READ_TOKEN);
  localStorage.removeItem(LS_DB_WRITE_TOKEN);
  localStorage.removeItem(LS_DB_TOKENS_BY_MOD);
}

export function isProductsReadGateGraceActive(): boolean {
  return false;
}

export function touchProductsReadGateGrace(): void {}

export async function fetchDbTokensStatus(apiBase = ''): Promise<DbTokensStatus> {
  const r = await fetch(`${apiBase}/api/fhd/db-tokens/status`);
  if (!r.ok) throw new Error(`db-tokens/status ${r.status}`);
  return r.json();
}

export function readStoredDbTokensForMod(_modId: string): { read: string; write: string } {
  return { read: '', write: '' };
}

export function saveStoredDbTokensForMod(modId: string, _read: string, _write: string): void {
  clearLegacyTokenStorage();
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(FHD_STORED_DB_TOKENS_CHANGED_EVENT, { detail: { modId } }));
  }
}

export function readStoredDbTokens(): { read: string; write: string } {
  return { read: '', write: '' };
}

export function saveStoredDbTokens(_read: string, _write: string): void {
  clearLegacyTokenStorage();
}

export function saveStoredReadToken(_read: string): void {
  clearLegacyTokenStorage();
}

export function saveStoredWriteToken(_write: string): void {
  clearLegacyTokenStorage();
}

export async function getProductsReadLockState(
  _apiBase = '',
  _options: ProductsReadProbeOptions = {}
): Promise<ProductsReadLockState> {
  return 'open';
}

export async function probeProductsReadAccess(
  _apiBase = '',
  _options: ProductsReadProbeOptions = {}
): Promise<boolean> {
  return true;
}

export function urlNeedsDbReadToken(_rawUrl: string): boolean {
  return false;
}

export function shouldAttachDbReadToken(_rawUrl: string, _method: string): boolean {
  return false;
}

export function armNextPlannerChatDbWriteToken(): void {}

export function isPlannerChatDbWriteTokenArmed(): boolean {
  return false;
}

export function consumePlannerChatDbWriteTokenArm(): void {}

export function notifyDbReadTokenRequiredAfter403(
  _status: number,
  _requestUrl: string,
  _method: string
): void {}

export function notifyDbWriteTokenRequiredAfter403(
  _status: number,
  _requestUrl: string,
  _method: string
): void {}

export function urlNeedsDbWriteToken(_rawUrl: string, _method: string): boolean {
  return false;
}

export function combinedRequestUrl(config: { baseURL?: string; url?: string }): string {
  const u = config.url || '';
  if (/^https?:\/\//i.test(u)) return u;
  const b = (config.baseURL || '').replace(/\/$/, '');
  const path = u.startsWith('/') ? u : `/${u}`;
  return b ? `${b}${path}` : path;
}

export function dbReadHeaders(_options: { ignoreGrace?: boolean } = {}): Record<string, string> {
  return {};
}

export function dbWriteHeaders(): Record<string, string> {
  return {};
}
