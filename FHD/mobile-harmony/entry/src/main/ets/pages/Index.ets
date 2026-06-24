import { MobileApiClient } from '../api/MobileApiClient';
import { SseChatClient, SseRecentMessage } from '../api/SseChatClient';
import { SessionStore, SessionSnapshot } from '../state/SessionStore';
import { ConnectivityMonitor } from '../state/ConnectivityMonitor';
import { BiometricGate } from '../state/BiometricGate';
import { OfflineDb } from '../state/OfflineDb';
import { MobileSyncRepository, SyncSummary } from '../state/MobileSyncRepository';
import { Analytics } from '../state/Analytics';
import common from '@ohos.app.ability.common';
import { AiEmployeeProfile, ChatMessage, ChatResponseData, cleanText, ConversationSummary, DutyRosterData, FixedContactDto, ModInfo, UserDto } from '../models/MobileModels';
import { buildConversations, buildDutyRoster, buildEmployees, composeConversations, fallbackFixedTop, findEmployee } from '../state/AppDataBuilder';
import { NotificationManager } from '../state/NotificationManager';
import { AboutPage } from './AboutPage';
import { AiCirclePage } from './AiCirclePage';
import { ApprovalPage } from './ApprovalPage';
import { BridgePage } from './BridgePage';
import { CsChatPage } from './CsChatPage';
import { DutyRosterPage } from './DutyRosterPage';
import { EnterprisePage } from './EnterprisePage';
import { EnterpriseModulePage } from './EnterpriseModulePage';
import { ImMessengerPage } from './ImMessengerPage';
import { LegalConsentPage } from './LegalConsentPage';
import { LoginPage } from './LoginPage';
import { LongTailPage } from './LongTailPage';
import { MainShell } from './MainShell';
import { MarketListPage } from './MarketListPage';
import { ModWebViewPage } from './ModWebViewPage';
import { NotificationListPage } from './NotificationListPage';
import { OcrPage } from './OcrPage';
import { ScanQrPage } from './ScanQrPage';
import { SettingsPage } from './SettingsPage';

const DEFAULT_BASE_URL = 'http://127.0.0.1:5000/';
const TAB_MESSAGES = 0;

function emptyDutyRoster(): DutyRosterData {
  return { areas: [], totalPlanned: 0, totalOnDuty: 0 };
}

@Entry
@Component
struct Index {
  private api: MobileApiClient = new MobileApiClient(DEFAULT_BASE_URL);
  private sse: SseChatClient = new SseChatClient();
  private session: SessionStore = new SessionStore();
  private connectivity: ConnectivityMonitor = new ConnectivityMonitor();
  private db: OfflineDb = new OfflineDb();
  private sync: MobileSyncRepository | null = null;
  private notifier: NotificationManager = NotificationManager.getInstance();

  @Provide baseUrl: string = DEFAULT_BASE_URL;
  @Provide username: string = '';
  @Provide password: string = '';
  @Provide pairingCode: string = '';
  @Provide accessToken: string = '';
  @Provide sessionId: string = '';
  @Provide displayName: string = '企业用户';
  @Provide companyBrand: string = '修辞企业版';
  @Provide accountKind: string = 'enterprise';
  @Provide loginAccountKind: string = 'admin';
  @Provide statusText: string = '连接企业端移动服务';
  @Provide loading: boolean = false;
  @Provide isOnline: boolean = true;
  @State loggedIn: boolean = false;
  @Provide selectedTab: number = TAB_MESSAGES;
  @Provide selectedEmployeeKey: string = '';
  @Provide activeConversationId: string = '';
  @Provide activeConversationTitle: string = '小C助理';
  @Provide activeEmployeeKey: string = '';
  @Provide chatInput: string = '';
  @Provide messages: ChatMessage[] = [{ role: 'assistant', text: '已准备连接企业端。登录后，我会按企业端已安装员工和两个固定入口展示会话。' }];
  @Provide mods: ModInfo[] = [];
  @Provide employees: AiEmployeeProfile[] = [];
  @Provide fixedTop: FixedContactDto[] = fallbackFixedTop('enterprise');
  @Provide fixedBottom: FixedContactDto[] = [];
  @Provide conversations: ConversationSummary[] = buildConversations([]);
  @Provide dutyRoster: DutyRosterData = emptyDutyRoster();
  // 设置模块状态：对齐 Android AppViewModel.biometricEnabled / themeMode
  @Provide biometricEnabled: boolean = false;
  @Provide themeMode: string = 'system';
  @Provide showSettings: boolean = false;
  @State showDutyRoster: boolean = false;
  @State activeOverlay: string = '';

  aboutToAppear(): void {
    this.db.init(getContext(this) as common.Context).then(() => {}, () => {});
    this.restoreSession();
    this.connectivity.start((online: boolean) => {
      this.isOnline = online;
      if (!online) {
        this.statusText = '网络已断开，正在重连…';
      }
    });
  }

  aboutToDisappear(): void {
    this.connectivity.stop();
  }

  // 冷启动恢复持久化的登录态（对齐 Android 自动恢复会话），失败则停留登录页。
  private async restoreSession(): Promise<void> {
    try {
      await this.session.init(getContext(this) as common.Context);
      const snap = await this.session.load();
      if (snap.baseUrl.length > 0) {
        this.baseUrl = snap.baseUrl;
        this.api.setBaseUrl(snap.baseUrl);
      }
      if (snap.accessToken.length > 0) {
        this.accessToken = snap.accessToken;
        this.api.setAccessToken(snap.accessToken);
        this.sessionId = snap.sessionId;
        this.accountKind = cleanText(snap.accountKind, this.accountKind);
        this.loginAccountKind = cleanText(snap.loginAccountKind, this.loginAccountKind);
        this.displayName = cleanText(snap.displayName, this.displayName);
        this.companyBrand = cleanText(snap.companyBrand, this.companyBrand);
        this.loggedIn = true;
        this.statusText = '已恢复登录，正在同步企业数据...';
        await this.loadHome();
        this.statusText = `已恢复登录 · ${this.mods.length} 个模块、${this.employees.length} 位员工`;
        this.triggerSync();
      }
    } catch (err) {
      // 恢复失败不致命：停留在登录页。
    }
  }

  // 登录成功后持久化会话，供下次冷启动恢复。
  private async persistSession(): Promise<void> {
    const snap: SessionSnapshot = {
      baseUrl: this.baseUrl,
      accessToken: this.accessToken,
      sessionId: this.sessionId,
      accountKind: this.accountKind,
      loginAccountKind: this.loginAccountKind,
      displayName: this.displayName,
      companyBrand: this.companyBrand
    };
    try {
      await this.session.saveAuth(snap);
    } catch (err) {
    }
  }

  // 登出清除持久化会话（fire-and-forget）。
  private clearSession(): void {
    this.session.clear().then(() => {}, () => {});
  }

  build() {
    Column() {
      if (this.loggedIn) {
        Stack() {
          MainShell({
            onOpenConversation: (item: ConversationSummary) => this.openConversation(item),
            onSendChatMessage: () => this.sendChatMessage(),
            onStartEmployeeChat: (key: string) => this.startEmployeeChat(key),
            onRefreshHome: () => this.refreshHome(),
            onLogout: () => this.logout(),
            onOpenSettings: () => this.openSettings(),
            onOpenDutyRoster: () => this.openDutyRoster(),
            onOpenOverlay: (name: string) => this.openOverlay(name)
          });
          if (this.showSettings) {
            SettingsPage({
              onBack: () => this.closeSettings(),
              onSetBiometric: (enabled: boolean) => this.setBiometricEnabled(enabled),
              onSetThemeMode: (mode: string) => this.setThemeMode(mode),
              onSubmitFeedback: (message: string, onDone: () => void) => this.submitFeedback(message, onDone),
              onCheckForUpdate: () => this.checkForUpdate()
            });
          }
          if (this.showDutyRoster) {
            DutyRosterPage({
              onBack: () => this.closeDutyRoster(),
              onStartEmployeeChat: (key: string) => this.startEmployeeChatFromDuty(key)
            });
          }
          if (this.activeOverlay.length > 0) {
            this.OverlayLayer();
          }
        }
        .width('100%')
        .height('100%');
      } else {
        LoginPage({ onLogin: () => this.login(), onExchangePairingCode: () => this.exchangePairingCode() });
      }
    }
    .width('100%').height('100%').backgroundColor('#F4F6F8');
  }

  private async login(): Promise<void> {
    if (this.loading) return;
    if (this.username.trim().length === 0 || this.password.length === 0) {
      this.statusText = this.loginAccountKind === 'admin' ? '请输入管理员账号和密码' : '请输入企业账号和密码';
      return;
    }
    this.loading = true;
    this.statusText = '正在验证账号...';
    this.api.setBaseUrl(this.baseUrl);
    try {
      const data = await this.api.login(this.username, this.password, this.loginAccountKind);
      const token = cleanText(data.access_token);
      if (token.length === 0) throw new Error('服务端未返回访问令牌');
      const user: UserDto = data.user || {};
      this.accessToken = token;
      this.api.setAccessToken(token);
      this.sessionId = cleanText(data.session_id, `harmony-${new Date().getTime()}`);
      this.displayName = cleanText(user.display_name, cleanText(user.username, this.username));
      this.companyBrand = cleanText(data.company_brand, '修辞企业版');
      this.accountKind = cleanText(data.account_kind, this.loginAccountKind);
      this.loggedIn = true;
      this.statusText = '登录成功，正在同步账号信息...';
      const me = await this.api.me();
      if (me.user) {
        this.displayName = cleanText(me.user.display_name, this.displayName);
        this.companyBrand = cleanText(me.company_brand, this.companyBrand);
        this.accountKind = cleanText(me.account_kind, this.accountKind);
      }
      this.statusText = '正在同步企业数据...';
      await this.loadHome();
      this.statusText = `已同步 ${this.mods.length} 个模块、${this.employees.length} 位员工`;
      await this.persistSession();
      this.triggerSync();
      Analytics.logKv('login_success', 'kind', this.accountKind);
    } catch (err) {
      this.statusText = `登录失败：${this.errorMessage(err)}`;
    } finally {
      this.loading = false;
    }
  }
  private async exchangePairingCode(): Promise<void> {
    if (this.loading) return;
    if (this.pairingCode.trim().length === 0) {
      this.statusText = '请输入桌面端绑定码';
      return;
    }
    this.loading = true;
    this.api.setBaseUrl(this.baseUrl);
    this.statusText = '正在交换绑定码...';
    try {
      const data = await this.api.pairingExchange(this.pairingCode);
      const host = cleanText(data.host);
      const port = data.port || 0;
      const apiBaseUrl = cleanText(data.api_base_url || data.base_url || '');
      if (apiBaseUrl.length > 0) {
        this.baseUrl = apiBaseUrl.endsWith('/') ? apiBaseUrl : `${apiBaseUrl}/`;
      } else if (host.length > 0 && port > 0) {
        this.baseUrl = `http://${host}:${port}/`;
      } else {
        throw new Error('绑定返回地址无效');
      }
      this.api.setBaseUrl(this.baseUrl);
      await this.session.saveBaseUrl(this.baseUrl);
      this.statusText = `已切换到 ${this.baseUrl}`;
    } catch (err) {
      this.statusText = `绑定失败：${this.errorMessage(err)}`;
    } finally {
      this.loading = false;
    }
  }
  private async loadHome(): Promise<void> {
    let mods: ModInfo[] = [];
    const home = await this.api.home();
    if (home.mods && home.mods.length > 0) mods = home.mods;
    else { const modData = await this.api.mods(); mods = modData.items || []; }
    this.mods = mods;
    this.employees = buildEmployees(mods);
    // 固定联系人按端 SSOT 派生(后端 /contacts/fixed);旧后端/失败回退到按端兜底
    let top: FixedContactDto[] = fallbackFixedTop(this.accountKind);
    let bottom: FixedContactDto[] = [];
    try {
      const fixed = await this.api.contactsFixed();
      if (fixed.top.length > 0) {
        top = fixed.top;
      }
      bottom = fixed.bottom;
    } catch (err) {
      // 端点不可用:保留按端兜底(小C + 企业端专属客服),无超级员工
      console.info('contactsFixed unavailable, using fallback: ' + this.errorMessage(err));
    }
    this.fixedTop = top;
    this.fixedBottom = bottom;
    this.conversations = composeConversations(top, this.employees, bottom);
    this.dutyRoster = buildDutyRoster(mods);
  }
  private async refreshHome(): Promise<void> {
    if (this.loading) return;
    this.loading = true;
    this.statusText = '正在刷新企业数据...';
    try {
      await this.loadHome();
      this.statusText = `已刷新 ${this.mods.length} 个模块、${this.employees.length} 位员工`;
    } catch (err) {
      this.statusText = `刷新失败：${this.errorMessage(err)}`;
    } finally {
      this.loading = false;
    }
  }
  private openConversation(item: ConversationSummary): void {
    this.activeConversationId = item.id;
    this.activeConversationTitle = item.title;
    this.activeEmployeeKey = item.employeeKey;
    this.messages = [{ role: 'assistant', text: `${item.title} 已就绪。${item.employeeKey.length > 0 ? '这位员工来自企业端已安装模块。' : '这是固定服务入口。'}` }];
  }
  private startEmployeeChat(employeeKey: string): void {
    const employee = findEmployee(this.employees, employeeKey);
    if (!employee) return;
    this.selectedEmployeeKey = '';
    this.selectedTab = TAB_MESSAGES;
    this.openConversation({
      id: `employee:${employee.key}`, title: employee.name, subtitle: employee.summary,
      badge: '已安装', avatar: employee.avatarText, source: employee.modName, employeeKey: employee.key
    });
  }
  private async sendChatMessage(): Promise<void> {
    if (this.loading) return;
    const text = this.chatInput.trim();
    if (text.length === 0) return;
    this.chatInput = '';
    // 当前轮之前的历史作为 recent_messages 上下文（对齐 Android SseChatClient）。
    const recent = this.recentMessagesContext();
    this.messages = this.messages.concat([{ role: 'user', text: text }]);
    this.loading = true;
    const payload = this.messageForActiveEmployee(text);
    // 占位 assistant 气泡，token 到达即流式追加。
    this.messages = this.messages.concat([{ role: 'assistant', text: '' }]);
    const assistantIndex = this.messages.length - 1;
    let acc = '';
    try {
      await this.sse.streamChat(
        this.api.getBaseUrl(), payload, this.accessToken, 0, recent, '',
        {
          onToken: (t: string) => {
            acc += t;
            this.updateAssistantAt(assistantIndex, acc);
          },
          onDone: (full: string) => {
            const finalText = cleanText(full, acc.length > 0 ? acc : '（无回复）');
            this.updateAssistantAt(assistantIndex, finalText);
            this.cacheTurn(text, finalText);
            Analytics.log('chat_done');
          },
          onError: (msg: string) => {
            this.updateAssistantAt(assistantIndex, acc.length > 0 ? acc : `请求失败：${msg}`);
          }
        }
      );
    } catch (err) {
      this.updateAssistantAt(assistantIndex, `请求失败：${this.errorMessage(err)}`);
    } finally {
      this.loading = false;
    }
  }

  // 取最近 6 条非空消息作为 recent_messages 上下文（{role, content}）。
  private recentMessagesContext(): SseRecentMessage[] {
    const out: SseRecentMessage[] = [];
    const history = this.messages;
    const start = history.length > 6 ? history.length - 6 : 0;
    for (let i = start; i < history.length; i++) {
      const m = history[i];
      if (m.text.trim().length > 0) {
        out.push({ role: m.role, content: m.text });
      }
    }
    return out;
  }

  // 流式更新指定下标的 assistant 气泡（复制数组触发 ArkUI 刷新）。
  private updateAssistantAt(index: number, text: string): void {
    if (index < 0 || index >= this.messages.length) return;
    const copy = this.messages.slice();
    copy[index] = { role: 'assistant', text: text };
    this.messages = copy;
  }

  // 把一轮对话写入离线缓存（供冷启动秒出 / sync 增量同步复用）。
  private cacheTurn(userText: string, assistantText: string): void {
    const key = this.activeConversationId.length > 0 ? this.activeConversationId : 'default';
    const now = new Date().getTime();
    this.db.cacheChat(key, 'user', userText, now).then(() => {}, () => {});
    this.db.cacheChat(key, 'assistant', assistantText, now + 1).then(() => {}, () => {});
  }

  // 触发增量同步（拉远端变更写离线缓存），登录/冷启动恢复后调用。
  private triggerSync(): void {
    if (this.sync === null) {
      this.sync = new MobileSyncRepository(this.api, this.db, this.session);
    }
    this.sync.pullAndCache().then((r: SyncSummary) => {
      Analytics.logKv('sync', 'ai', r.aiCount.toString());
      if (r.ok && (r.aiCount > 0 || r.approvalCount > 0)) {
        this.statusText = `已同步 ${r.aiCount} 条对话、${r.approvalCount} 条审批`;
      }
    }, () => {});
  }
  private messageForActiveEmployee(text: string): string {
    if (this.activeEmployeeKey.length === 0) return text;
    const employee = findEmployee(this.employees, this.activeEmployeeKey);
    if (!employee) return text;
    return `请以企业端员工「${employee.name}」身份处理：${text}\n来源模块：${employee.modName}\n员工标识：${employee.employeeId}\n接口路径：${employee.apiBasePath}`;
  }
  private extractReply(response: ChatResponseData): string {
    const direct = cleanText(response.reply);
    if (direct.length > 0) return direct;
    if (response.data) {
      const nested = cleanText(response.data.reply, cleanText(response.data.content, cleanText(response.data.message)));
      if (nested.length > 0) return nested;
    }
    return cleanText(response.message, '服务端已返回，但没有可展示内容');
  }
  private logout(): void {
    this.accessToken = ''; this.sessionId = ''; this.api.setAccessToken('');
    this.loggedIn = false; this.selectedTab = TAB_MESSAGES; this.selectedEmployeeKey = '';
    this.activeConversationId = ''; this.mods = []; this.employees = [];
    this.conversations = buildConversations([]); this.dutyRoster = emptyDutyRoster();
    this.statusText = '已退出企业账号';
    this.showSettings = false; this.showDutyRoster = false; this.notifier.unregister();
    this.clearSession();
  }
  private errorMessage(err: object): string { return cleanText((err as Error).message, '未知错误'); }

  // ── 设置模块：对齐 Android AppViewModel ──
  private openSettings(): void {
    this.showSettings = true;
  }
  private closeSettings(): void {
    this.showSettings = false;
  }

  // ── 员工入岗 / 值班编制 ──
  private openDutyRoster(): void {
    this.showDutyRoster = true;
  }
  private closeDutyRoster(): void {
    this.showDutyRoster = false;
  }
  private startEmployeeChatFromDuty(employeeKey: string): void {
    this.showDutyRoster = false;
    this.startEmployeeChat(employeeKey);
  }

  // ── 全部功能 overlay（审批/通知/客服/IM/企业/AI圈子/扫码/OCR/市场/服务桥/长尾/关于） ──
  private openOverlay(name: string): void {
    this.activeOverlay = name;
  }
  private closeOverlay(): void {
    this.activeOverlay = '';
  }

  @Builder
  OverlayLayer() {
    if (this.activeOverlay === 'approval') {
      ApprovalPage({ onBack: () => this.closeOverlay() });
    } else if (this.activeOverlay === 'notifications') {
      NotificationListPage({ onBack: () => this.closeOverlay() });
    } else if (this.activeOverlay === 'cs') {
      CsChatPage({ onBack: () => this.closeOverlay() });
    } else if (this.activeOverlay === 'im') {
      ImMessengerPage({ onBack: () => this.closeOverlay() });
    } else if (this.activeOverlay === 'enterprise') {
      EnterprisePage({
        onBack: () => this.closeOverlay(),
        onOpenModule: (moduleId: string) => {
          this.activeOverlay = 'enterprise_module:' + moduleId;
        }
      });
    } else if (this.activeOverlay.startsWith('enterprise_module:')) {
      EnterpriseModulePage({
        moduleId: this.activeOverlay.substring('enterprise_module:'.length),
        moduleTitle: '企业模块',
        onBack: () => { this.activeOverlay = 'enterprise'; },
        onOpenFeature: (featureId: string) => {}
      });
    } else if (this.activeOverlay === 'aicircle') {
      AiCirclePage({ onBack: () => this.closeOverlay() });
    } else if (this.activeOverlay === 'scan') {
      ScanQrPage({ onBack: () => this.closeOverlay(), onScanResult: (result: string) => this.closeOverlay() });
    } else if (this.activeOverlay === 'ocr') {
      OcrPage({ onBack: () => this.closeOverlay() });
    } else if (this.activeOverlay === 'market') {
      MarketListPage({ onBack: () => this.closeOverlay(), onOpenMod: (modId: string) => {
        this.activeOverlay = 'modweb:' + modId;
      }});
    } else if (this.activeOverlay.startsWith('modweb:')) {
      ModWebViewPage({
        modId: this.activeOverlay.substring('modweb:'.length),
        modTitle: 'MOD',
        onBack: () => { this.activeOverlay = 'market'; }
      });
    } else if (this.activeOverlay === 'bridge') {
      BridgePage({ onBack: () => this.closeOverlay() });
    } else if (this.activeOverlay === 'longtail') {
      LongTailPage({ onBack: () => this.closeOverlay() });
    } else if (this.activeOverlay === 'about') {
      AboutPage({ onBack: () => this.closeOverlay(), onCheckUpdate: () => {} });
    }
  }
  private setBiometricEnabled(enabled: boolean): void {
    if (!enabled) {
      this.biometricEnabled = false;
      this.statusText = '已关闭生物识别解锁';
      return;
    }
    if (!BiometricGate.canAuthenticate()) {
      this.biometricEnabled = false;
      this.statusText = '本设备不支持生物识别/设备密码';
      return;
    }
    this.statusText = '请完成生物识别校验以开启';
    BiometricGate.prompt((success: boolean) => {
      this.biometricEnabled = success;
      this.statusText = success ? '已开启生物识别解锁' : '生物识别校验未通过，未开启';
    });
  }
  private setThemeMode(mode: string): void {
    const normalized = mode === 'dark' || mode === 'light' ? mode : 'system';
    this.themeMode = normalized;
    this.statusText = `主题模式：${normalized === 'dark' ? '深色' : normalized === 'light' ? '浅色' : '跟随系统'}`;
  }
  private submitFeedback(message: string, onDone: () => void): void {
    const text = message.trim();
    if (text.length === 0) return;
    this.statusText = '正在提交反馈...';
    // 复用 chat 通道转发反馈，避免新增端点；与 Android repo.submitFeedback 行为对齐
    this.api.chat(`[用户反馈] ${text}`, this.sessionId)
      .then(() => {
        this.statusText = '感谢您的反馈，我们会尽快处理';
        onDone();
      })
      .catch((err: object) => {
        this.statusText = `反馈提交失败：${this.errorMessage(err)}`;
      });
  }
  private checkForUpdate(): void {
    this.statusText = '正在检查更新...';
    this.api.home()
      .then(() => {
        this.statusText = '已是最新版本';
      })
      .catch((err: object) => {
        this.statusText = `检查更新失败：${this.errorMessage(err)}`;
      });
  }
}
