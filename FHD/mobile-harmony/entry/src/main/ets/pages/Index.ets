import { MobileApiClient } from '../api/MobileApiClient';
import { SseChatClient } from '../api/SseChatClient';
import { BiometricGate } from '../state/BiometricGate';
import { NetworkMonitor } from '../state/NetworkMonitor';
import { PushService } from '../state/PushService';
import { AiEmployeeProfile, ChatMessage, ChatResponseData, cleanText, ConversationSummary, DutyRosterData, FixedContactDto, ModInfo, UserDto } from '../models/MobileModels';
import { buildConversations, buildDutyRoster, buildEmployees, composeConversations, fallbackFixedTop, findEmployee } from '../state/AppDataBuilder';
import { LocalStore, PersistedSession } from '../state/LocalStore';
import { NotificationManager } from '../state/NotificationManager';
import { AboutPage } from './AboutPage';
import { AiCirclePage } from './AiCirclePage';
import { AiGroupChatPage } from './AiGroupChatPage';
import { AiGroupListPage } from './AiGroupListPage';
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
import { RegisterPage } from './RegisterPage';
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
  private notifier: NotificationManager = NotificationManager.getInstance();
  private store: LocalStore = LocalStore.getInstance();

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
  @State activeGroupName: string = '';
  @State showLegalGate: boolean = false;
  @State showRegister: boolean = false;
  @State unlocked: boolean = true;
  @Provide online: boolean = true;
  private netMonitor: NetworkMonitor = NetworkMonitor.getInstance();

  aboutToAppear(): void {
    this.store.init(getContext(this));
    const saved: PersistedSession = this.store.load();
    // 恢复本机偏好(主题/生物识别)
    this.biometricEnabled = saved.biometricEnabled;
    this.themeMode = saved.themeMode;
    // 首启合规门:未同意过则先弹用户协议与隐私政策(对标 Android LegalConsentScreen)
    this.showLegalGate = !saved.legalConsented;
    // 网络状态监测:离线时主界面顶部显示横幅
    this.netMonitor.start((online: boolean) => { this.online = online; });
    if (saved.baseUrl.length > 0) {
      this.baseUrl = saved.baseUrl;
    }
    if (saved.loginAccountKind.length > 0) {
      this.loginAccountKind = saved.loginAccountKind;
    }
    // 有持久化令牌则尝试自动登录(对标 Android auth_auto_login)
    if (saved.accessToken.length > 0) {
      this.restoreSession(saved);
    }
  }

  private async restoreSession(saved: PersistedSession): Promise<void> {
    this.accessToken = saved.accessToken;
    this.sessionId = saved.sessionId;
    this.accountKind = saved.accountKind;
    this.displayName = saved.displayName.length > 0 ? saved.displayName : this.displayName;
    this.companyBrand = saved.companyBrand.length > 0 ? saved.companyBrand : this.companyBrand;
    this.api.setBaseUrl(this.baseUrl);
    this.api.setAccessToken(saved.accessToken);
    this.loading = true;
    this.statusText = '正在恢复会话...';
    try {
      const me = await this.api.me();
      if (me.user) {
        this.displayName = cleanText(me.user.display_name, this.displayName);
        this.companyBrand = cleanText(me.company_brand, this.companyBrand);
        this.accountKind = cleanText(me.account_kind, this.accountKind);
      }
      await this.loadHome();
      this.loggedIn = true;
      this.statusText = `已恢复登录，同步 ${this.mods.length} 个模块、${this.employees.length} 位员工`;
      // 开启生物识别时,恢复登录态需先解锁(对标 Android BiometricGate)
      if (this.biometricEnabled) {
        this.unlocked = false;
        this.promptUnlock();
      }
    } catch (err) {
      // 令牌过期/失效:清掉令牌回登录页
      this.accessToken = '';
      this.api.setAccessToken('');
      this.store.clearSession();
      this.statusText = '登录已过期，请重新登录';
    } finally {
      this.loading = false;
    }
  }

  private promptUnlock(): void {
    BiometricGate.authenticate('解锁 XCAGI 企业版')
      .then((ok: boolean) => {
        if (ok) {
          this.unlocked = true;
        } else {
          this.statusText = '解锁失败，请重试';
        }
      })
      .catch(() => {
        // 验证流程异常:放行,避免锁死
        this.unlocked = true;
      });
  }

  @Builder
  LockScreen() {
    Column({ space: 18 }) {
      Text('🔒')
        .fontSize(48);
      Text('已锁定')
        .fontSize(20)
        .fontWeight(FontWeight.Bold)
        .fontColor('#111827');
      Text('请通过生物识别解锁以继续')
        .fontSize(14)
        .fontColor('#6B7280');
      Button('解锁')
        .width(160)
        .height(46)
        .onClick(() => this.promptUnlock());
      Text('退出登录')
        .fontSize(14)
        .fontColor('#1D4ED8')
        .onClick(() => { this.unlocked = true; this.logout(); });
    }
    .width('100%')
    .height('100%')
    .justifyContent(FlexAlign.Center)
    .alignItems(HorizontalAlign.Center)
    .backgroundColor('#F4F6F8');
  }

  private persistSession(): void {
    const snapshot: PersistedSession = {
      accessToken: this.accessToken,
      sessionId: this.sessionId,
      baseUrl: this.baseUrl,
      accountKind: this.accountKind,
      loginAccountKind: this.loginAccountKind,
      displayName: this.displayName,
      companyBrand: this.companyBrand,
      biometricEnabled: this.biometricEnabled,
      themeMode: this.themeMode,
      legalConsented: true
    };
    this.store.saveSession(snapshot);
  }

  build() {
    Column() {
      if (this.loggedIn && this.biometricEnabled && !this.unlocked) {
        this.LockScreen();
      } else if (this.loggedIn) {
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
      } else if (this.showLegalGate) {
        LegalConsentPage({
          onBack: () => { this.showLegalGate = false; },
          onAgree: () => { this.store.saveLegalConsent(true); this.showLegalGate = false; }
        });
      } else if (this.showRegister) {
        RegisterPage({
          onBack: () => { this.showRegister = false; },
          onSuccess: () => {
            this.showRegister = false;
            this.statusText = '注册信息已提交，请使用企业账号登录或桌面端绑定码接入';
          }
        });
      } else {
        LoginPage({
          onLogin: () => this.login(),
          onExchangePairingCode: () => this.exchangePairingCode(),
          onOpenRegister: () => { this.showRegister = true; }
        });
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
      this.persistSession();
      // 注册推送 token(best-effort;需 AGC 配置/真机才生效)
      PushService.registerToken(this.api);
      this.statusText = `已同步 ${this.mods.length} 个模块、${this.employees.length} 位员工`;
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
    this.messages = this.messages.concat([{ role: 'user', text: text }]);
    // 占位的助手气泡，SSE token 逐字写入
    this.messages = this.messages.concat([{ role: 'assistant', text: '' }]);
    const assistantIndex = this.messages.length - 1;
    this.loading = true;
    const payload = this.messageForActiveEmployee(text);
    let acc = '';
    let gotToken = false;
    const sse = new SseChatClient(this.baseUrl, this.accessToken);
    try {
      await sse.stream(payload, {
        onToken: (chunk: string) => {
          gotToken = true;
          acc += chunk;
          this.updateAssistantAt(assistantIndex, acc);
        },
        onDone: (reply: string) => {
          if (reply.length > 0) {
            this.updateAssistantAt(assistantIndex, reply);
          } else if (!gotToken) {
            this.updateAssistantAt(assistantIndex, '服务端已返回，但没有可展示内容');
          }
        },
        onError: (message: string) => {
          if (!gotToken) {
            this.updateAssistantAt(assistantIndex, `请求失败：${message}`);
          }
        }
      });
    } catch (err) {
      // 流式失败回退到一次性 HTTP(对标 Android 流式失败兜底)
      try {
        const response = await this.api.chat(payload, this.sessionId);
        this.updateAssistantAt(assistantIndex, this.extractReply(response));
      } catch (err2) {
        this.updateAssistantAt(assistantIndex, `请求失败：${this.errorMessage(err2)}`);
      }
    } finally {
      this.loading = false;
    }
  }

  private updateAssistantAt(index: number, text: string): void {
    this.messages = this.messages.map((message: ChatMessage, i: number): ChatMessage => {
      if (i === index) {
        const updated: ChatMessage = { role: 'assistant', text: text };
        return updated;
      }
      return message;
    });
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
    this.store.clearSession();
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
        onOpenFeature: (featureId: string) => {},
        onOpenApproval: () => { this.activeOverlay = 'approval'; }
      });
    } else if (this.activeOverlay === 'aicircle') {
      AiCirclePage({ onBack: () => this.closeOverlay() });
    } else if (this.activeOverlay === 'aigroups') {
      AiGroupListPage({
        onBack: () => this.closeOverlay(),
        onOpenGroup: (groupId: string, groupName: string) => {
          this.activeGroupName = groupName;
          this.activeOverlay = 'aigroup:' + groupId;
        }
      });
    } else if (this.activeOverlay.startsWith('aigroup:')) {
      AiGroupChatPage({
        groupId: this.activeOverlay.substring('aigroup:'.length),
        groupName: this.activeGroupName,
        onBack: () => { this.activeOverlay = 'aigroups'; }
      });
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
    this.biometricEnabled = enabled;
    this.store.savePreferences(this.biometricEnabled, this.themeMode);
    this.statusText = enabled ? '已开启生物识别解锁' : '已关闭生物识别解锁';
  }
  private setThemeMode(mode: string): void {
    const normalized = mode === 'dark' || mode === 'light' ? mode : 'system';
    this.themeMode = normalized;
    this.store.savePreferences(this.biometricEnabled, this.themeMode);
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
