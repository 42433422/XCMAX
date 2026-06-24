import preferences from '@ohos.data.preferences';
import common from '@ohos.app.ability.common';

// 登录态持久化，对齐 Android core/datastore/SessionStore.kt 的核心会话字段：
// host / access_token / session_id / account_kind / login_account_kind / display_name / company_brand。
// 冷启动恢复登录态，避免每次重开都要重新登录。
// 说明：本端只持久化会话恢复所需字段；记住密码/凭证加密(CredentialCipher)暂未纳入。

const STORE_NAME = 'xcagi_session';
const K_BASE = 'fhd_host';
const K_TOKEN = 'fhd_access_token';
const K_SESSION = 'fhd_session_id';
const K_ACCOUNT = 'account_kind';
const K_LOGIN_KIND = 'login_account_kind';
const K_DISPLAY = 'display_name';
const K_BRAND = 'company_brand';

export interface SessionSnapshot {
  baseUrl: string;
  accessToken: string;
  sessionId: string;
  accountKind: string;
  loginAccountKind: string;
  displayName: string;
  companyBrand: string;
}

export class SessionStore {
  private store: preferences.Preferences | null = null;

  async init(context: common.Context): Promise<void> {
    if (this.store !== null) {
      return;
    }
    const options: preferences.Options = { name: STORE_NAME };
    this.store = await preferences.getPreferences(context, options);
  }

  async load(): Promise<SessionSnapshot> {
    const s = this.store;
    if (s === null) {
      return SessionStore.empty();
    }
    const snap: SessionSnapshot = {
      baseUrl: await SessionStore.getStr(s, K_BASE),
      accessToken: await SessionStore.getStr(s, K_TOKEN),
      sessionId: await SessionStore.getStr(s, K_SESSION),
      accountKind: await SessionStore.getStr(s, K_ACCOUNT),
      loginAccountKind: await SessionStore.getStr(s, K_LOGIN_KIND),
      displayName: await SessionStore.getStr(s, K_DISPLAY),
      companyBrand: await SessionStore.getStr(s, K_BRAND)
    };
    return snap;
  }

  async saveAuth(snap: SessionSnapshot): Promise<void> {
    const s = this.store;
    if (s === null) {
      return;
    }
    await s.put(K_BASE, snap.baseUrl);
    await s.put(K_TOKEN, snap.accessToken);
    await s.put(K_SESSION, snap.sessionId);
    await s.put(K_ACCOUNT, snap.accountKind);
    await s.put(K_LOGIN_KIND, snap.loginAccountKind);
    await s.put(K_DISPLAY, snap.displayName);
    await s.put(K_BRAND, snap.companyBrand);
    await s.flush();
  }

  async saveBaseUrl(baseUrl: string): Promise<void> {
    const s = this.store;
    if (s === null) {
      return;
    }
    await s.put(K_BASE, baseUrl);
    await s.flush();
  }

  async syncCursor(): Promise<number> {
    const s = this.store;
    if (s === null) {
      return 0;
    }
    const v: preferences.ValueType = await s.get('sync_cursor', 0);
    return typeof v === 'number' ? (v as number) : 0;
  }

  async setSyncCursor(cursor: number, lastSyncAt: string): Promise<void> {
    const s = this.store;
    if (s === null) {
      return;
    }
    await s.put('sync_cursor', cursor);
    await s.put('last_sync_at', lastSyncAt);
    await s.flush();
  }

  async lastSyncAt(): Promise<string> {
    const s = this.store;
    if (s === null) {
      return '';
    }
    return SessionStore.getStr(s, 'last_sync_at');
  }

  async clear(): Promise<void> {
    const s = this.store;
    if (s === null) {
      return;
    }
    await s.clear();
    await s.flush();
  }

  private static async getStr(s: preferences.Preferences, key: string): Promise<string> {
    const v: preferences.ValueType = await s.get(key, '');
    return typeof v === 'string' ? (v as string) : '';
  }

  private static empty(): SessionSnapshot {
    return {
      baseUrl: '', accessToken: '', sessionId: '', accountKind: '',
      loginAccountKind: '', displayName: '', companyBrand: ''
    };
  }
}
