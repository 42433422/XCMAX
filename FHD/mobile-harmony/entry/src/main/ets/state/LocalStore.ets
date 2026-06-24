// 本地持久化(对标 Android SessionStore + DataStore)。
//
// 用 @ohos.data.preferences 把登录态与用户偏好持久化到应用沙箱,
// 使 App 重启后无需重新登录、保留主题/生物识别/合规同意等设置。
// 仅存非高敏字段 + 访问令牌(应用沙箱默认隔离);如需更强保护可后续接 HUKS。

import dataPreferences from '@ohos.data.preferences';
import common from '@ohos.app.ability.common';

const STORE_NAME: string = 'xcagi_session';

const K_ACCESS_TOKEN: string = 'access_token';
const K_SESSION_ID: string = 'session_id';
const K_BASE_URL: string = 'base_url';
const K_ACCOUNT_KIND: string = 'account_kind';
const K_LOGIN_ACCOUNT_KIND: string = 'login_account_kind';
const K_DISPLAY_NAME: string = 'display_name';
const K_COMPANY_BRAND: string = 'company_brand';
const K_BIOMETRIC: string = 'biometric_enabled';
const K_THEME_MODE: string = 'theme_mode';
const K_LEGAL_CONSENT: string = 'legal_consented';

/** 持久化的会话快照(恢复登录态用)。 */
export interface PersistedSession {
  accessToken: string;
  sessionId: string;
  baseUrl: string;
  accountKind: string;
  loginAccountKind: string;
  displayName: string;
  companyBrand: string;
  biometricEnabled: boolean;
  themeMode: string;
  legalConsented: boolean;
}

export class LocalStore {
  private static instance: LocalStore | null = null;
  private pref: dataPreferences.Preferences | null = null;

  static getInstance(): LocalStore {
    if (LocalStore.instance === null) {
      LocalStore.instance = new LocalStore();
    }
    return LocalStore.instance;
  }

  /** 在 Index.aboutToAppear 用 getContext(this) 初始化一次。 */
  init(context: common.Context): void {
    if (this.pref !== null) {
      return;
    }
    try {
      this.pref = dataPreferences.getPreferencesSync(context, { name: STORE_NAME });
    } catch (err) {
      console.error('LocalStore init failed: ' + ((err as Error).message));
    }
  }

  private readString(key: string, fallback: string): string {
    if (this.pref === null) {
      return fallback;
    }
    const value = this.pref.getSync(key, fallback);
    return typeof value === 'string' ? value : fallback;
  }

  private readBool(key: string, fallback: boolean): boolean {
    return this.readString(key, fallback ? '1' : '0') === '1';
  }

  private writeString(key: string, value: string): void {
    if (this.pref === null) {
      return;
    }
    this.pref.putSync(key, value);
  }

  /** 把内存中字段写回磁盘(putSync 入内存,flush 落盘)。 */
  private async flush(): Promise<void> {
    if (this.pref === null) {
      return;
    }
    try {
      await this.pref.flush();
    } catch (err) {
      console.error('LocalStore flush failed: ' + ((err as Error).message));
    }
  }

  /** 读出整份会话快照。 */
  load(): PersistedSession {
    return {
      accessToken: this.readString(K_ACCESS_TOKEN, ''),
      sessionId: this.readString(K_SESSION_ID, ''),
      baseUrl: this.readString(K_BASE_URL, ''),
      accountKind: this.readString(K_ACCOUNT_KIND, 'enterprise'),
      loginAccountKind: this.readString(K_LOGIN_ACCOUNT_KIND, 'admin'),
      displayName: this.readString(K_DISPLAY_NAME, ''),
      companyBrand: this.readString(K_COMPANY_BRAND, ''),
      biometricEnabled: this.readBool(K_BIOMETRIC, false),
      themeMode: this.readString(K_THEME_MODE, 'system'),
      legalConsented: this.readBool(K_LEGAL_CONSENT, false)
    };
  }

  /** 登录成功后保存会话(令牌+账号信息)。 */
  saveSession(session: PersistedSession): void {
    this.writeString(K_ACCESS_TOKEN, session.accessToken);
    this.writeString(K_SESSION_ID, session.sessionId);
    this.writeString(K_BASE_URL, session.baseUrl);
    this.writeString(K_ACCOUNT_KIND, session.accountKind);
    this.writeString(K_LOGIN_ACCOUNT_KIND, session.loginAccountKind);
    this.writeString(K_DISPLAY_NAME, session.displayName);
    this.writeString(K_COMPANY_BRAND, session.companyBrand);
    this.flush();
  }

  /** 单独持久化偏好(设置页改动后调用)。 */
  savePreferences(biometricEnabled: boolean, themeMode: string): void {
    this.writeString(K_BIOMETRIC, biometricEnabled ? '1' : '0');
    this.writeString(K_THEME_MODE, themeMode);
    this.flush();
  }

  /** 持久化合规同意标记(首启同意后)。 */
  saveLegalConsent(consented: boolean): void {
    this.writeString(K_LEGAL_CONSENT, consented ? '1' : '0');
    this.flush();
  }

  /** 退出登录:清掉令牌与会话,但保留主题/合规等本机偏好。 */
  clearSession(): void {
    this.writeString(K_ACCESS_TOKEN, '');
    this.writeString(K_SESSION_ID, '');
    this.writeString(K_DISPLAY_NAME, '');
    this.flush();
  }
}
