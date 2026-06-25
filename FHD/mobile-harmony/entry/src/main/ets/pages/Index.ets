import { MobileApiClient } from '../api/MobileApiClient';
import { SseChatClient } from '../api/SseChatClient';
import { BiometricGate } from '../state/BiometricGate';
import { NetworkMonitor } from '../state/NetworkMonitor';
import { PushService } from '../state/PushService';
import { AiEmployeeProfile, ChatMessage, ChatResponseData, cleanText, ConversationSummary, DutyRosterData, FixedContactDto, ModInfo, RelayDesktop, RelayTask, RelayTaskResult, SuperEmployeeDispatch, SuperEmployeeInvokeData, SuperEmployeeMessageRow, UserDto } from '../models/MobileModels';
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
import { MeetingMinutesPage } from './MeetingMinutesPage';
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
  private sse: SseChatClient = new SseChatClient();
  private session: SessionStore = new SessionStore();
  private connectivity: ConnectivityMonitor = new ConnectivityMonitor();
  private db: OfflineDb = new OfflineDb();
  private sync: MobileSyncRepository | null = null;
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
  @Provide isOnline: boolean = true;
  @State loggedIn: boolean = false;
  @Provide selectedTab: number = TAB_MESSAGES;
  @Provide selectedEmployeeKey: string = '';
  @Provide activeConversationId: string = '';
  @Provide activeConversationTitle: string = '小C助理';
  @Provide activeEmployeeKey: string = '';
  @Provide chatInput: string = '';
  // 超级员工派工模式三态控件（自动/直答/多设备），仅 super:* 会话生效。
  @Provide superDispatchMode: string = 'auto';
  // 已绑定的桌面执行端 relay_id（非空 → 超级员工走 relay 离线中继；空 → 走 direct）。
  @Provide relayDesktopId: string = '';
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
              onCheckForUpdate: () => this.checkForUpdate(),
              onBindRelayDesktop: (code: string, onDone: (ok: boolean, msg: string) => void) => this.bindRelayDesktop(code, onDone)
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
      // 恢复 relay 绑定（已绑定桌面 → 超级员工走离线中继；未绑定不影响其它功能）。
      await this.refreshRelayBinding();
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
    // 当前轮之前的历史作为 recent_messages 上下文（对齐 Android SseChatClient）。
    const recent = this.recentMessagesContext();
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
      const superTool = this.superToolForConversation(this.activeConversationId);
      if (superTool.length > 0) {
        // 超级员工会话：走派工/中继通路（不走 SSE 流式）。
        await this.sendSuperEmployeeMessage(superTool, text);
      } else {
        // 普通会话：SSE 流式逐字写入，失败回退一次性 HTTP（见 catch）。
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
      }
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

  // ── 超级员工派工（对标安卓 streamCodexSuperEmployeeChat 的 direct 分支）──
  // convId 'super:codex'/'super:claude' → 工具名；其它 → 空（走通用聊天）。
  private superToolForConversation(convId: string): string {
    if (convId === 'super:claude') return 'claude';
    if (convId === 'super:codex') return 'codex';
    return '';
  }

  private async sendSuperEmployeeMessage(tool: string, text: string): Promise<void> {
    // 已绑定桌面执行端 → 走 relay 离线中继（手机不在电脑旁也能派工）；否则 direct。
    if (this.relayDesktopId.length > 0) {
      await this.sendSuperEmployeeViaRelay(tool, text);
      return;
    }
    const data = await this.api.superEmployeeInvoke(tool, text, this.superDispatchMode);
    const immediate = this.superImmediateReply(data);
    if (immediate.length > 0) {
      // CLI 直答（直答档/自动档闲聊）：立即拿到答案。
      this.messages = this.messages.concat([{ role: 'assistant', text: immediate }]);
      return;
    }
    // 多设备派工：先占位，再轮询回写结果，替换占位。
    this.messages = this.messages.concat([{ role: 'assistant', text: '已派发到多设备，执行中…' }]);
    const requestId = this.superRequestId(data);
    const reply = await this.pollSuperEmployeeReply(tool, requestId);
    const finalText = reply.length > 0 ? reply : '任务已提交，稍后回到此会话可查看执行结果。';
    this.messages = this.messages.slice(0, this.messages.length - 1).concat([{ role: 'assistant', text: finalText }]);
  }

  private superImmediateReply(data: SuperEmployeeInvokeData): string {
    const am: SuperEmployeeMessageRow | undefined = data.assistant_message;
    if (!am) return '';
    const role = (am.role || '').trim().toLowerCase();
    const kind = (am.kind || '').trim().toLowerCase();
    const body = (am.body || '').trim();
    if (body.length === 0) return '';
    // 派工占位（"思考中…"/调度器）走 system/dispatcher，不算直答，交给轮询。
    if (role === 'system' || kind === 'dispatcher') return '';
    return body;
  }

  private superRequestId(data: SuperEmployeeInvokeData): string {
    const d: SuperEmployeeDispatch | undefined = data.dispatch;
    if (d && (d.request_id || '').trim().length > 0) return (d.request_id || '').trim();
    const am: SuperEmployeeMessageRow | undefined = data.assistant_message;
    if (am && (am.dispatch_request_id || '').trim().length > 0) return (am.dispatch_request_id || '').trim();
    return '';
  }

  private async pollSuperEmployeeReply(tool: string, requestId: string): Promise<string> {
    for (let i = 0; i < 60; i++) {
      await this.sleep(2000);
      let rows: SuperEmployeeMessageRow[] = [];
      try {
        rows = await this.api.superEmployeeMessages(tool);
      } catch (err) {
        // 轮询期间瞬时错误忽略，继续等待回写。
        continue;
      }
      const hit = this.matchSuperResult(rows, requestId);
      if (hit.length > 0) return hit;
    }
    return '';
  }

  // 倒序找到与本次请求匹配的助手结果消息（跳过 system/dispatcher 派工占位）。
  private matchSuperResult(rows: SuperEmployeeMessageRow[], requestId: string): string {
    for (let i = rows.length - 1; i >= 0; i--) {
      const row: SuperEmployeeMessageRow = rows[i];
      const role = (row.role || '').trim().toLowerCase();
      const kind = (row.kind || '').trim().toLowerCase();
      const body = (row.body || '').trim();
      const rid = (row.dispatch_request_id || '').trim();
      if (role !== 'assistant') continue;
      if (kind === 'dispatcher') continue;
      if (requestId.length > 0 && rid !== requestId) continue;
      if (body.length === 0) continue;
      return body;
    }
    return '';
  }

  private sleep(ms: number): Promise<void> {
    return new Promise<void>((resolve: () => void) => {
      setTimeout(() => { resolve(); }, ms);
    });
  }

  // ── 超级员工 relay 离线通路（对标安卓 streamRelayCodexTask）──
  private async sendSuperEmployeeViaRelay(tool: string, text: string): Promise<void> {
    const kind = tool === 'claude' ? 'claude.invoke' : 'codex.invoke';
    const task = await this.api.relayCreateTask(this.relayDesktopId, kind, text, this.superDispatchMode);
    const taskId = (task.task_id || '').trim();
    if (taskId.length === 0) {
      this.messages = this.messages.concat([{ role: 'assistant', text: '中继任务创建失败：未找到已绑定的电脑执行端。' }]);
      return;
    }
    this.messages = this.messages.concat([{ role: 'assistant', text: '已经云中继派发到电脑执行端，执行中…' }]);
    const reply = await this.pollRelayTask(taskId);
    const finalText = reply.length > 0 ? reply : '电脑执行端暂未回写结果，任务仍在后台运行，可稍后回到此会话查看。';
    this.messages = this.messages.slice(0, this.messages.length - 1).concat([{ role: 'assistant', text: finalText }]);
  }

  // 轮询中继任务直到终态。done/completed → 取结果；failed/blocked/cancelled → 错误文案。
  private async pollRelayTask(taskId: string): Promise<string> {
    for (let i = 0; i < 90; i++) {
      await this.sleep(2000);
      let task: RelayTask = {};
      try {
        task = await this.api.relayTaskStatus(taskId);
      } catch (err) {
        continue;
      }
      const status = (task.status || '').trim().toLowerCase();
      if (status === 'done' || status === 'completed') {
        return this.relayTaskResultText(task);
      }
      if (status === 'failed' || status === 'blocked' || status === 'cancelled') {
        const detail = this.relayTaskResultText(task);
        return detail.length > 0 ? detail : '电脑执行端执行失败。';
      }
    }
    return '';
  }

  // 结果取值：error → codex.assistant_message.body → reply（与安卓 relayTaskResultText 同构）。
  private relayTaskResultText(task: RelayTask): string {
    const result: RelayTaskResult | undefined = task.result;
    if (!result) return '';
    const err = (result.error || '').trim();
    if (err.length > 0) return err;
    const codex: SuperEmployeeInvokeData | undefined = result.codex;
    if (codex) {
      const am: SuperEmployeeMessageRow | undefined = codex.assistant_message;
      const body = ((am ? am.body : '') || '').trim();
      if (body.length > 0) return body;
    }
    const reply = (result.reply || '').trim();
    if (reply.length > 0) return reply;
    return '';
  }

  // 设置页"绑定电脑执行端"：6 位设备码 → relay_id，绑定后超级员工自动走 relay。
  private async bindRelayDesktop(code: string, onDone: (ok: boolean, msg: string) => void): Promise<void> {
    const clean = code.trim();
    if (clean.length !== 6) {
      onDone(false, '请输入 6 位设备码');
      return;
    }
    try {
      const data = await this.api.relayConfirmCode(clean);
      const relayId = (data.relay_id || (data.desktop ? data.desktop.relay_id : '') || '').trim();
      if (relayId.length === 0) {
        onDone(false, '绑定响应缺少 relay_id');
        return;
      }
      this.relayDesktopId = relayId;
      onDone(true, '已绑定电脑执行端，超级员工任务将派到该电脑。');
    } catch (err) {
      onDone(false, `绑定失败：${this.errorMessage(err)}`);
    }
  }

  // 登录后自动恢复 relay 绑定：账号下已绑定唯一桌面 → 直接采用，免去再次输码。
  private async refreshRelayBinding(): Promise<void> {
    try {
      const desktops: RelayDesktop[] = await this.api.relayDesktops();
      for (let i = 0; i < desktops.length; i++) {
        const rid = (desktops[i].relay_id || '').trim();
        if (rid.length > 0) {
          this.relayDesktopId = rid;
          return;
        }
      }
    } catch (err) {
      // 没有绑定或接口不可用时静默：超级员工回退 direct 通路。
      console.info('refreshRelayBinding skipped: ' + this.errorMessage(err));
    }
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
    } else if (this.activeOverlay === 'meeting') {
      MeetingMinutesPage({ onBack: () => this.closeOverlay() });
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
