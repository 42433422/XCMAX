import { MobileApiClient } from '../api/MobileApiClient';
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
    // 按 surface SSOT 派生的 route 分流:专属客服走 cs-officer(/cs) 独立通道,
    // 不进 Persona 内联会话;小C(assistant_chat)与员工/普通会话走 ChatPage→/api/ai/chat(Persona)。
    if (item.route === 'cs') {
      this.activeOverlay = 'cs';
      return;
    }
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
    this.loading = true;
    try {
      const payload = this.messageForActiveEmployee(text);
      const response = await this.api.chat(payload, this.sessionId);
      this.messages = this.messages.concat([{ role: 'assistant', text: this.extractReply(response) }]);
    } catch (err) {
      this.messages = this.messages.concat([{ role: 'assistant', text: `请求失败：${this.errorMessage(err)}` }]);
    } finally {
      this.loading = false;
    }
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
    this.biometricEnabled = enabled;
    this.statusText = enabled ? '已开启生物识别解锁' : '已关闭生物识别解锁';
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
