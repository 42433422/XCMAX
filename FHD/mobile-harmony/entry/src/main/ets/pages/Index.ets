import { MobileApiClient } from '../api/MobileApiClient';
import {
  AiEmployeeProfile,
  ChatMessage,
  ChatResponseData,
  cleanText,
  ConversationSummary,
  firstChar,
  ModInfo,
  UserDto
} from '../models/MobileModels';
import { buildConversations, buildEmployees, findEmployee } from '../state/AppDataBuilder';

const DEFAULT_BASE_URL = 'http://127.0.0.1:5000/';
const TAB_MESSAGES = 0;
const TAB_CONTACTS = 1;
const TAB_DISCOVER = 2;
const TAB_PROFILE = 3;

@Entry
@Component
struct Index {
  private api: MobileApiClient = new MobileApiClient(DEFAULT_BASE_URL);

  @State private baseUrl: string = DEFAULT_BASE_URL;
  @State private username: string = '';
  @State private password: string = '';
  @State private pairingCode: string = '';
  @State private accessToken: string = '';
  @State private sessionId: string = '';
  @State private displayName: string = '企业用户';
  @State private companyBrand: string = '修辞企业版';
  @State private accountKind: string = 'enterprise';
  @State private loginAccountKind: string = 'admin';
  @State private statusText: string = '连接企业端移动服务';
  @State private loading: boolean = false;
  @State private loggedIn: boolean = false;
  @State private selectedTab: number = TAB_MESSAGES;
  @State private selectedEmployeeKey: string = '';
  @State private activeConversationId: string = '';
  @State private activeConversationTitle: string = '小C助理';
  @State private activeEmployeeKey: string = '';
  @State private chatInput: string = '';
  @State private messages: ChatMessage[] = [
    {
      role: 'assistant',
      text: '已准备连接企业端。登录后，我会按企业端已安装员工和两个固定入口展示会话。'
    }
  ];
  @State private mods: ModInfo[] = [];
  @State private employees: AiEmployeeProfile[] = [];
  @State private conversations: ConversationSummary[] = buildConversations([]);

  build() {
    Column() {
      if (this.loggedIn) {
        this.MainShell();
      } else {
        this.LoginScreen();
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor('#F4F6F8');
  }

  @Builder
  LoginScreen() {
    Scroll() {
      Column({ space: 18 }) {
        Row() {
          Row({ space: 12 }) {
            Text('XC')
              .width(52)
              .height(52)
              .borderRadius(16)
              .fontSize(18)
              .fontWeight(FontWeight.Bold)
              .fontColor('#FFFFFF')
              .textAlign(TextAlign.Center)
              .backgroundColor('#101827');

            Column({ space: 4 }) {
              Text('XCAGI 企业移动端')
                .fontSize(24)
                .fontWeight(FontWeight.Bold)
                .fontColor('#101827');
              Text('员工、会话、Codex 协同入口')
                .fontSize(14)
                .fontColor('#506074');
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1);
          }
          .layoutWeight(1);

          Text(this.loading ? '连接中' : '在线')
            .fontSize(12)
            .fontWeight(FontWeight.Medium)
            .fontColor(this.loading ? '#92400E' : '#166534')
            .padding({ left: 10, right: 10, top: 5, bottom: 5 })
            .backgroundColor(this.loading ? '#FEF3C7' : '#DCFCE7')
            .borderRadius(12);
        }
        .width('100%')
        .padding({ left: 22, right: 22, top: 28, bottom: 4 });

        Column({ space: 16 }) {
          Row() {
            Column({ space: 3 }) {
              Text('登录')
                .fontSize(21)
                .fontWeight(FontWeight.Bold)
                .fontColor('#111827');
              Text(this.loginAccountKind === 'admin' ? '管理端账号' : '企业端账号')
                .fontSize(13)
                .fontColor('#64748B');
            }
            .layoutWeight(1)
            .alignItems(HorizontalAlign.Start);

            Text(this.loginAccountKind === 'admin' ? '管理员' : '企业')
              .fontSize(12)
              .fontColor('#1D4ED8')
              .padding({ left: 10, right: 10, top: 5, bottom: 5 })
              .backgroundColor('#E8F0FF')
              .borderRadius(12);
          }
          .width('100%');

          Row() {
            Text('管理员账号')
              .layoutWeight(1)
              .height(38)
              .fontSize(14)
              .fontWeight(FontWeight.Medium)
              .fontColor(this.loginAccountKind === 'admin' ? '#FFFFFF' : '#475569')
              .textAlign(TextAlign.Center)
              .backgroundColor(this.loginAccountKind === 'admin' ? '#2563EB' : '#EEF2F7')
              .borderRadius(10)
              .onClick(() => {
                this.loginAccountKind = 'admin';
              });
            Text('企业账号')
              .layoutWeight(1)
              .height(38)
              .fontSize(14)
              .fontWeight(FontWeight.Medium)
              .fontColor(this.loginAccountKind === 'enterprise' ? '#FFFFFF' : '#475569')
              .textAlign(TextAlign.Center)
              .backgroundColor(this.loginAccountKind === 'enterprise' ? '#2563EB' : '#EEF2F7')
              .borderRadius(10)
              .onClick(() => {
                this.loginAccountKind = 'enterprise';
              });
          }
          .width('100%')
          .padding(4)
          .backgroundColor('#EEF2F7')
          .borderRadius(14);

          Column({ space: 8 }) {
            this.FieldLabel('服务地址');
            TextInput({ placeholder: '例如 http://192.168.1.10:17500', text: this.baseUrl })
              .height(50)
              .fontSize(15)
              .fontColor('#111827')
              .placeholderColor('#7B8794')
              .backgroundColor('#F8FAFC')
              .borderRadius(12)
              .border({ width: 1, color: '#D8E0EA' })
              .padding({ left: 14, right: 14 })
              .onChange((value: string) => {
                this.baseUrl = value;
              });
          }
          .width('100%');

          Column({ space: 8 }) {
            this.FieldLabel(this.loginAccountKind === 'admin' ? '管理员账号' : '企业账号');
            TextInput({
              placeholder: this.loginAccountKind === 'admin' ? '服务器后台管理员账号' : '企业端账号或邮箱',
              text: this.username
            })
              .height(50)
              .fontSize(15)
              .fontColor('#111827')
              .placeholderColor('#7B8794')
              .backgroundColor('#F8FAFC')
              .borderRadius(12)
              .border({ width: 1, color: '#D8E0EA' })
              .padding({ left: 14, right: 14 })
              .onChange((value: string) => {
                this.username = value;
              });
          }
          .width('100%');

          Column({ space: 8 }) {
            this.FieldLabel('密码');
            TextInput({
              placeholder: this.loginAccountKind === 'admin' ? '管理员登录密码' : '企业账号登录密码',
              text: this.password
            })
              .height(50)
              .fontSize(15)
              .fontColor('#111827')
              .placeholderColor('#7B8794')
              .backgroundColor('#F8FAFC')
              .borderRadius(12)
              .border({ width: 1, color: '#D8E0EA' })
              .padding({ left: 14, right: 14 })
              .type(InputType.Password)
              .onChange((value: string) => {
                this.password = value;
              });
          }
          .width('100%');

          Button(this.loading ? '登录中...' : (this.loginAccountKind === 'admin' ? '进入管理端' : '进入企业端'))
            .width('100%')
            .height(50)
            .fontSize(16)
            .fontWeight(FontWeight.Medium)
            .fontColor('#FFFFFF')
            .backgroundColor(this.loading ? '#94A3B8' : '#2563EB')
            .borderRadius(12)
            .enabled(!this.loading)
            .onClick(() => {
              this.login();
            });

          Row({ space: 8 }) {
            Text(this.statusText.indexOf('失败') >= 0 ? '!' : 'i')
              .width(22)
              .height(22)
              .borderRadius(11)
              .fontSize(12)
              .fontWeight(FontWeight.Bold)
              .fontColor(this.statusText.indexOf('失败') >= 0 ? '#B91C1C' : '#1D4ED8')
              .textAlign(TextAlign.Center)
              .backgroundColor(this.statusText.indexOf('失败') >= 0 ? '#FEE2E2' : '#E8F0FF');
            Text(this.statusText)
              .layoutWeight(1)
              .fontSize(13)
              .fontColor(this.statusText.indexOf('失败') >= 0 ? '#B91C1C' : '#35506B')
              .maxLines(3);
          }
          .width('100%')
          .padding({ left: 12, right: 12, top: 10, bottom: 10 })
          .backgroundColor(this.statusText.indexOf('失败') >= 0 ? '#FFF1F2' : '#F8FAFC')
          .borderRadius(12)
          .border({ width: 1, color: this.statusText.indexOf('失败') >= 0 ? '#FECACA' : '#E2E8F0' });
        }
        .width('100%')
        .padding(18)
        .margin({ left: 18, right: 18 })
        .backgroundColor('#FFFFFF')
        .borderRadius(18)
        .border({ width: 1, color: '#DDE5EF' });

        Column({ space: 12 }) {
          Row() {
            Text('桌面绑定')
              .fontSize(16)
              .fontWeight(FontWeight.Medium)
              .fontColor('#111827')
              .layoutWeight(1);
            Text('可选')
              .fontSize(12)
              .fontColor('#64748B')
              .padding({ left: 10, right: 10, top: 4, bottom: 4 })
              .backgroundColor('#F1F5F9')
              .borderRadius(10);
          }
          .width('100%');

          Row({ space: 10 }) {
            TextInput({ placeholder: '输入绑定码', text: this.pairingCode })
              .height(46)
              .fontSize(15)
              .fontColor('#111827')
              .placeholderColor('#7B8794')
              .backgroundColor('#F8FAFC')
              .borderRadius(12)
              .border({ width: 1, color: '#D8E0EA' })
              .padding({ left: 14, right: 14 })
              .layoutWeight(1)
              .onChange((value: string) => {
                this.pairingCode = value;
              });
            Button('绑定')
              .height(46)
              .fontSize(15)
              .fontColor('#1D4ED8')
              .backgroundColor('#E8F0FF')
              .borderRadius(12)
              .padding({ left: 18, right: 18 })
              .enabled(!this.loading)
              .onClick(() => {
                this.exchangePairingCode();
              });
          }
          .width('100%');
        }
        .width('100%')
        .padding(16)
        .margin({ left: 18, right: 18, bottom: 24 })
        .backgroundColor('#FFFFFF')
        .borderRadius(16)
        .border({ width: 1, color: '#DDE5EF' });
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start);
    }
    .width('100%')
    .height('100%')
    .backgroundColor('#F3F6FA');
  }

  @Builder
  MainShell() {
    Column() {
      this.TopBar();

      if (this.selectedTab === TAB_MESSAGES) {
        this.MessageArea();
      } else if (this.selectedTab === TAB_CONTACTS) {
        this.ContactsArea();
      } else if (this.selectedTab === TAB_DISCOVER) {
        this.DiscoverArea();
      } else {
        this.ProfileArea();
      }

      this.BottomNav();
    }
    .width('100%')
    .height('100%')
    .backgroundColor('#F4F6F8');
  }

  @Builder
  TopBar() {
    Row({ space: 12 }) {
      Column({ space: 2 }) {
        Text(this.companyBrand)
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .fontColor('#111827')
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis });
        Text(`${this.displayName} · ${this.accountKind === 'enterprise' ? '企业账号' : this.accountKind}`)
          .fontSize(13)
          .fontColor('#374151')
          .maxLines(1);
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);

      Text('i')
        .width(36)
        .height(36)
        .borderRadius(18)
        .fontSize(18)
        .fontWeight(FontWeight.Bold)
        .fontColor('#1D4ED8')
        .textAlign(TextAlign.Center)
        .backgroundColor('#E8F0FF')
        .border({ width: 1, color: '#C7D7FE' })
        .onClick(() => {
          this.selectedTab = TAB_PROFILE;
        });
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 14, bottom: 12 })
    .backgroundColor('#FFFFFF')
    .border({ width: { bottom: 1 }, color: '#E5E7EB' });
  }

  @Builder
  MessageArea() {
    if (this.activeConversationId.length > 0) {
      this.ChatArea();
    } else {
      Scroll() {
        Column({ space: 10 }) {
          Row() {
            Text('消息')
              .fontSize(24)
              .fontWeight(FontWeight.Bold)
              .fontColor('#111827')
              .layoutWeight(1);
            Text(`${this.conversations.length} 个会话`)
              .fontSize(13)
              .fontColor('#4B5563');
          }
          .width('100%')
          .padding({ left: 18, right: 18, top: 18 });

          ForEach(this.conversations, (item: ConversationSummary) => {
            this.ConversationRow(item);
          }, (item: ConversationSummary) => item.id);
        }
        .width('100%')
        .padding({ bottom: 18 });
      }
      .width('100%')
      .layoutWeight(1);
    }
  }

  @Builder
  ConversationRow(item: ConversationSummary) {
    Row({ space: 12 }) {
      this.Avatar(item.avatar, item.id === 'assistant' ? '#18A85F' : '#1D4ED8');

      Column({ space: 5 }) {
        Row({ space: 8 }) {
          Text(item.title)
            .fontSize(17)
            .fontWeight(FontWeight.Medium)
            .fontColor('#111827')
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .layoutWeight(1);
          Text(item.badge)
            .fontSize(12)
            .fontColor('#166534')
            .padding({ left: 8, right: 8, top: 3, bottom: 3 })
            .backgroundColor('#E7F7EE')
            .borderRadius(9);
        }
        .width('100%');

        Text(item.subtitle)
          .fontSize(14)
          .fontColor('#374151')
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis });

        Text(item.source === 'fixed' ? '固定入口' : item.source)
          .fontSize(12)
          .fontColor('#1D4ED8')
          .maxLines(1);
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);
    }
    .width('100%')
    .padding(14)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' })
    .onClick(() => {
      this.openConversation(item);
    });
  }

  @Builder
  ChatArea() {
    Column() {
      Row({ space: 10 }) {
        Text('<')
          .width(36)
          .height(36)
          .fontSize(22)
          .fontColor('#111827')
          .textAlign(TextAlign.Center)
          .onClick(() => {
            this.activeConversationId = '';
            this.activeEmployeeKey = '';
          });

        Column({ space: 2 }) {
          Text(this.activeConversationTitle)
            .fontSize(18)
            .fontWeight(FontWeight.Medium)
            .fontColor('#111827')
            .maxLines(1);
          Text(this.activeEmployeeKey.length > 0 ? '企业端已安装员工' : '固定服务入口')
            .fontSize(12)
            .fontColor('#4B5563');
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1);

        Text('i')
          .width(34)
          .height(34)
          .borderRadius(17)
          .fontSize(16)
          .fontWeight(FontWeight.Bold)
          .fontColor('#1D4ED8')
          .textAlign(TextAlign.Center)
          .backgroundColor('#E8F0FF')
          .onClick(() => {
            if (this.activeEmployeeKey.length > 0) {
              this.selectedEmployeeKey = this.activeEmployeeKey;
              this.selectedTab = TAB_CONTACTS;
              this.activeConversationId = '';
            } else {
              this.selectedTab = TAB_PROFILE;
              this.activeConversationId = '';
            }
          });
      }
      .width('100%')
      .padding({ left: 12, right: 14, top: 8, bottom: 8 })
      .backgroundColor('#FFFFFF')
      .border({ width: { bottom: 1 }, color: '#E5E7EB' });

      Scroll() {
        Column({ space: 12 }) {
          ForEach(this.messages, (message: ChatMessage, index: number) => {
            this.ChatBubble(message, index);
          }, (_message: ChatMessage, index: number) => `${index}`);
        }
        .width('100%')
        .padding({ left: 14, right: 14, top: 16, bottom: 16 });
      }
      .width('100%')
      .layoutWeight(1);

      Column({ space: 8 }) {
        Row({ space: 8 }) {
          this.ModeChip('快速', true);
          this.ModeChip('深度', false);
          this.ModeChip('识图', false);
        }
        .width('100%');

        Row({ space: 10 }) {
          TextInput({ placeholder: '发送消息', text: this.chatInput })
            .height(44)
            .fontSize(15)
            .fontColor('#111827')
            .placeholderColor('#6B7280')
            .backgroundColor('#FFFFFF')
            .borderRadius(12)
            .padding({ left: 14, right: 14 })
            .layoutWeight(1)
            .onChange((value: string) => {
              this.chatInput = value;
            });
          Button(this.loading ? '...' : '发送')
            .height(44)
            .fontSize(15)
            .fontColor('#FFFFFF')
            .backgroundColor('#2563EB')
            .borderRadius(12)
            .padding({ left: 18, right: 18 })
            .enabled(!this.loading)
            .onClick(() => {
              this.sendChatMessage();
            });
        }
        .width('100%');
      }
      .width('100%')
      .padding({ left: 12, right: 12, top: 10, bottom: 12 })
      .backgroundColor('#F4F6F8')
      .border({ width: { top: 1 }, color: '#E5E7EB' });
    }
    .width('100%')
    .layoutWeight(1);
  }

  @Builder
  ChatBubble(message: ChatMessage, index: number) {
    Row() {
      if (message.role === 'user') {
        Blank()
          .layoutWeight(1);
        Text(message.text)
          .fontSize(15)
          .fontColor('#FFFFFF')
          .lineHeight(22)
          .padding({ left: 14, right: 14, top: 10, bottom: 10 })
          .backgroundColor('#18A85F')
          .borderRadius(14)
          .constraintSize({ maxWidth: '78%' });
      } else {
        Text(message.text)
          .fontSize(15)
          .fontColor('#111827')
          .lineHeight(22)
          .padding({ left: 14, right: 14, top: 10, bottom: 10 })
          .backgroundColor('#FFFFFF')
          .borderRadius(14)
          .border({ width: 1, color: '#E5E7EB' })
          .constraintSize({ maxWidth: '78%' });
        Blank()
          .layoutWeight(1);
      }
    }
    .width('100%')
    .padding({ top: index === 0 ? 0 : 2 });
  }

  @Builder
  ContactsArea() {
    if (this.selectedEmployeeKey.length > 0) {
      this.EmployeeProfileArea();
    } else {
      Scroll() {
        Column({ space: 12 }) {
          Row() {
            Text('通讯录')
              .fontSize(24)
              .fontWeight(FontWeight.Bold)
              .fontColor('#111827')
              .layoutWeight(1);
            Text('企业同步')
              .fontSize(13)
              .fontColor('#166534')
              .padding({ left: 10, right: 10, top: 4, bottom: 4 })
              .backgroundColor('#E7F7EE')
              .borderRadius(10);
          }
          .width('100%')
          .padding({ left: 18, right: 18, top: 18 });

          this.FixedContact('小C助理', '企业 AI 助手，处理搜索、问答和跨工具操作', 'C');
          this.FixedContact('专属客服', '企业账号专属服务入口', '客');

          Row() {
            Text('企业端已安装 AI 员工')
              .fontSize(16)
              .fontWeight(FontWeight.Medium)
              .fontColor('#111827')
              .layoutWeight(1);
            Text(`${this.employees.length}`)
              .fontSize(13)
              .fontColor('#4B5563');
          }
          .width('100%')
          .padding({ left: 18, right: 18, top: 10 });

          if (this.employees.length === 0) {
            this.EmptyCard('暂无企业员工', '在企业端安装带工作流员工的 AI 模块后，这里会自动出现。');
          } else {
            ForEach(this.employees, (employee: AiEmployeeProfile) => {
              this.EmployeeRow(employee);
            }, (employee: AiEmployeeProfile) => employee.key);
          }
        }
        .width('100%')
        .padding({ bottom: 18 });
      }
      .width('100%')
      .layoutWeight(1);
    }
  }

  @Builder
  FixedContact(title: string, summary: string, avatar: string) {
    Row({ space: 12 }) {
      this.Avatar(avatar, avatar === 'C' ? '#18A85F' : '#2563EB');
      Column({ space: 5 }) {
        Text(title)
          .fontSize(17)
          .fontWeight(FontWeight.Medium)
          .fontColor('#111827');
        Text(summary)
          .fontSize(14)
          .fontColor('#374151')
          .maxLines(2);
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);
    }
    .width('100%')
    .padding(14)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  EmployeeRow(employee: AiEmployeeProfile) {
    Row({ space: 12 }) {
      this.Avatar(employee.avatarText, '#1D4ED8');
      Column({ space: 5 }) {
        Text(employee.name)
          .fontSize(17)
          .fontWeight(FontWeight.Medium)
          .fontColor('#111827')
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis });
        Text(employee.summary)
          .fontSize(14)
          .fontColor('#374151')
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis });
        Text(employee.modName)
          .fontSize(12)
          .fontColor('#1D4ED8')
          .maxLines(1);
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);
    }
    .width('100%')
    .padding(14)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' })
    .onClick(() => {
      this.selectedEmployeeKey = employee.key;
    });
  }

  @Builder
  EmployeeProfileArea() {
    Column() {
      Row({ space: 10 }) {
        Text('<')
          .width(36)
          .height(36)
          .fontSize(22)
          .fontColor('#111827')
          .textAlign(TextAlign.Center)
          .onClick(() => {
            this.selectedEmployeeKey = '';
          });
        Text('员工主页')
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .fontColor('#111827')
          .layoutWeight(1);
      }
      .width('100%')
      .padding({ left: 12, right: 18, top: 14, bottom: 10 })
      .backgroundColor('#FFFFFF')
      .border({ width: { bottom: 1 }, color: '#E5E7EB' });

      Scroll() {
        Column({ space: 14 }) {
          this.EmployeeProfileCard();
        }
        .width('100%')
        .padding({ left: 16, right: 16, top: 16, bottom: 24 });
      }
      .width('100%')
      .layoutWeight(1);
    }
    .width('100%')
    .layoutWeight(1);
  }

  @Builder
  EmployeeProfileCard() {
    Column({ space: 16 }) {
      Row({ space: 14 }) {
        this.Avatar(this.currentEmployeeAvatar(), '#1D4ED8');
        Column({ space: 5 }) {
          Text(this.currentEmployeeName())
            .fontSize(22)
            .fontWeight(FontWeight.Bold)
            .fontColor('#111827')
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis });
          Text(this.currentEmployeeTitle())
            .fontSize(14)
            .fontColor('#374151')
            .maxLines(2);
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1);
      }
      .width('100%');

      Text(this.currentEmployeeSummary())
        .width('100%')
        .fontSize(15)
        .fontColor('#111827')
        .lineHeight(22);

      this.InfoRow('来源模块', this.currentEmployeeModName());
      this.InfoRow('员工标识', this.currentEmployeeId());
      this.InfoRow('接口路径', this.currentEmployeeApiPath());
      this.InfoRow('电话通道', this.currentEmployeePhoneChannel());

      Row({ space: 10 }) {
        Button('发消息')
          .height(44)
          .fontSize(15)
          .fontColor('#FFFFFF')
          .backgroundColor('#18A85F')
          .borderRadius(12)
          .layoutWeight(1)
          .onClick(() => {
            this.startEmployeeChat(this.selectedEmployeeKey);
          });
        Button('返回列表')
          .height(44)
          .fontSize(15)
          .fontColor('#1D4ED8')
          .backgroundColor('#E8F0FF')
          .borderRadius(12)
          .layoutWeight(1)
          .onClick(() => {
            this.selectedEmployeeKey = '';
          });
      }
      .width('100%');
    }
    .width('100%')
    .padding(18)
    .backgroundColor('#FFFFFF')
    .borderRadius(16)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  DiscoverArea() {
    Scroll() {
      Column({ space: 12 }) {
        Row() {
          Text('AI交流圈')
            .fontSize(24)
            .fontWeight(FontWeight.Bold)
            .fontColor('#111827')
            .layoutWeight(1);
          Text(`${this.employees.length} 位员工`)
            .fontSize(13)
            .fontColor('#4B5563');
        }
        .width('100%')
        .padding({ left: 18, right: 18, top: 18 });

        if (this.employees.length === 0) {
          this.EmptyCard('等待企业端员工', '这里不会预置无关员工；企业端下载并启用 AI 员工后，动态内容会在这里生成。');
        } else {
          ForEach(this.employees, (employee: AiEmployeeProfile) => {
            this.CirclePost(employee);
          }, (employee: AiEmployeeProfile) => employee.key);
        }

        Column({ space: 10 }) {
          Text('移动端同步')
            .fontSize(16)
            .fontWeight(FontWeight.Medium)
            .fontColor('#111827');
          Text(`已连接 ${this.baseUrl}`)
            .fontSize(13)
            .fontColor('#374151')
            .maxLines(2);
          Row({ space: 8 }) {
            Text(`模块 ${this.mods.length}`)
              .fontSize(12)
              .fontColor('#1D4ED8')
              .padding({ left: 10, right: 10, top: 5, bottom: 5 })
              .backgroundColor('#E8F0FF')
              .borderRadius(10);
            Text(`员工 ${this.employees.length}`)
              .fontSize(12)
              .fontColor('#166534')
              .padding({ left: 10, right: 10, top: 5, bottom: 5 })
              .backgroundColor('#E7F7EE')
              .borderRadius(10);
          }
        }
        .width('100%')
        .padding(16)
        .margin({ left: 14, right: 14 })
        .backgroundColor('#FFFFFF')
        .borderRadius(14)
        .border({ width: 1, color: '#E5E7EB' });
      }
      .width('100%')
      .padding({ bottom: 20 });
    }
    .width('100%')
    .layoutWeight(1);
  }

  @Builder
  CirclePost(employee: AiEmployeeProfile) {
    Column({ space: 12 }) {
      Row({ space: 12 }) {
        this.Avatar(employee.avatarText, '#1D4ED8');
        Column({ space: 3 }) {
          Text(employee.name)
            .fontSize(17)
            .fontWeight(FontWeight.Medium)
            .fontColor('#111827')
            .maxLines(1);
          Text(employee.modName)
            .fontSize(13)
            .fontColor('#4B5563')
            .maxLines(1);
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1);
      }
      .width('100%');

      Text(employee.summary)
        .width('100%')
        .fontSize(15)
        .fontColor('#111827')
        .lineHeight(22)
        .maxLines(4)
        .textOverflow({ overflow: TextOverflow.Ellipsis });

      Row({ space: 8 }) {
        Text(employee.apiBasePath.length > 0 ? employee.apiBasePath : '企业工作流')
          .fontSize(12)
          .fontColor('#1D4ED8')
          .padding({ left: 10, right: 10, top: 5, bottom: 5 })
          .backgroundColor('#E8F0FF')
          .borderRadius(10);
        Text(employee.placeholder ? '待配置' : '可调用')
          .fontSize(12)
          .fontColor(employee.placeholder ? '#92400E' : '#166534')
          .padding({ left: 10, right: 10, top: 5, bottom: 5 })
          .backgroundColor(employee.placeholder ? '#FEF3C7' : '#E7F7EE')
          .borderRadius(10);
      }
      .width('100%');
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' })
    .onClick(() => {
      this.selectedEmployeeKey = employee.key;
      this.selectedTab = TAB_CONTACTS;
    });
  }

  @Builder
  ProfileArea() {
    Scroll() {
      Column({ space: 14 }) {
        Row({ space: 14 }) {
          this.Avatar(firstChar(this.displayName), '#18A85F');
          Column({ space: 4 }) {
            Text(this.displayName)
              .fontSize(22)
              .fontWeight(FontWeight.Bold)
              .fontColor('#111827')
              .maxLines(1);
            Text(this.accountKind === 'enterprise' ? '企业管理员账号' : this.accountKind)
              .fontSize(14)
              .fontColor('#374151');
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1);
        }
        .width('100%')
        .padding(18)
        .backgroundColor('#FFFFFF')
        .borderRadius(16)
        .border({ width: 1, color: '#E5E7EB' });

        Column({ space: 12 }) {
          Text('介绍')
            .fontSize(18)
            .fontWeight(FontWeight.Bold)
            .fontColor('#111827');
          Text('鸿蒙版已改为原生移动端：登录企业后端，读取企业端模块与员工，并在消息、通讯录、AI交流圈中使用同一批数据。')
            .fontSize(15)
            .fontColor('#111827')
            .lineHeight(22);
          Text('固定入口只保留小C助理和专属客服，其余 AI 员工全部来自企业端已安装模块。')
            .fontSize(15)
            .fontColor('#111827')
            .lineHeight(22);
        }
        .width('100%')
        .padding(18)
        .backgroundColor('#FFFFFF')
        .borderRadius(16)
        .border({ width: 1, color: '#E5E7EB' });

        Column({ space: 10 }) {
          this.InfoRow('企业', this.companyBrand);
          this.InfoRow('服务地址', this.baseUrl);
          this.InfoRow('已安装模块', `${this.mods.length}`);
          this.InfoRow('AI 员工', `${this.employees.length}`);
          this.InfoRow('会话入口', `${this.conversations.length}`);
        }
        .width('100%')
        .padding(18)
        .backgroundColor('#FFFFFF')
        .borderRadius(16)
        .border({ width: 1, color: '#E5E7EB' });

        Row({ space: 10 }) {
          Button('刷新同步')
            .height(44)
            .fontSize(15)
            .fontColor('#FFFFFF')
            .backgroundColor('#2563EB')
            .borderRadius(12)
            .layoutWeight(1)
            .enabled(!this.loading)
            .onClick(() => {
              this.refreshHome();
            });
          Button('退出')
            .height(44)
            .fontSize(15)
            .fontColor('#991B1B')
            .backgroundColor('#FEE2E2')
            .borderRadius(12)
            .layoutWeight(1)
            .onClick(() => {
              this.logout();
            });
        }
        .width('100%');
      }
      .width('100%')
      .padding({ left: 16, right: 16, top: 18, bottom: 24 });
    }
    .width('100%')
    .layoutWeight(1);
  }

  @Builder
  BottomNav() {
    Row() {
      this.NavItem('消息', TAB_MESSAGES);
      this.NavItem('通讯录', TAB_CONTACTS);
      this.NavItem('探索', TAB_DISCOVER);
      this.NavItem('我的', TAB_PROFILE);
    }
    .width('100%')
    .height(62)
    .padding({ left: 8, right: 8 })
    .backgroundColor('#FFFFFF')
    .border({ width: { top: 1 }, color: '#E5E7EB' });
  }

  @Builder
  NavItem(label: string, tab: number) {
    Column({ space: 4 }) {
      Text(this.navGlyph(tab))
        .fontSize(18)
        .fontColor(this.selectedTab === tab ? '#18A85F' : '#4B5563')
        .fontWeight(this.selectedTab === tab ? FontWeight.Bold : FontWeight.Regular);
      Text(label)
        .fontSize(12)
        .fontColor(this.selectedTab === tab ? '#18A85F' : '#4B5563');
    }
    .justifyContent(FlexAlign.Center)
    .alignItems(HorizontalAlign.Center)
    .layoutWeight(1)
    .height('100%')
    .onClick(() => {
      this.selectedTab = tab;
      this.activeConversationId = '';
    });
  }

  @Builder
  Avatar(text: string, color: string) {
    Text(text)
      .width(48)
      .height(48)
      .borderRadius(14)
      .fontSize(18)
      .fontWeight(FontWeight.Bold)
      .fontColor('#FFFFFF')
      .textAlign(TextAlign.Center)
      .backgroundColor(color);
  }

  @Builder
  ModeChip(label: string, active: boolean) {
    Text(label)
      .fontSize(12)
      .fontColor(active ? '#1D4ED8' : '#4B5563')
      .padding({ left: 10, right: 10, top: 5, bottom: 5 })
      .backgroundColor(active ? '#E8F0FF' : '#FFFFFF')
      .borderRadius(10)
      .border({ width: 1, color: active ? '#C7D7FE' : '#E5E7EB' });
  }

  @Builder
  FieldLabel(label: string) {
    Text(label)
      .fontSize(13)
      .fontColor('#111827')
      .fontWeight(FontWeight.Medium)
      .width('100%');
  }

  @Builder
  EmptyCard(title: string, subtitle: string) {
    Column({ space: 8 }) {
      Text(title)
        .fontSize(16)
        .fontWeight(FontWeight.Medium)
        .fontColor('#111827');
      Text(subtitle)
        .fontSize(14)
        .fontColor('#374151')
        .lineHeight(20)
        .textAlign(TextAlign.Center);
    }
    .width('100%')
    .padding(18)
    .margin({ left: 14, right: 14 })
    .alignItems(HorizontalAlign.Center)
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  InfoRow(label: string, value: string) {
    Row({ space: 12 }) {
      Text(label)
        .width(88)
        .fontSize(14)
        .fontColor('#4B5563');
      Text(value.length > 0 ? value : '未配置')
        .fontSize(14)
        .fontColor('#111827')
        .maxLines(3)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
        .layoutWeight(1);
    }
    .width('100%');
  }

  private async login(): Promise<void> {
    if (this.loading) {
      return;
    }
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
      if (token.length === 0) {
        throw new Error('服务端未返回访问令牌');
      }
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
    if (this.loading) {
      return;
    }
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
    if (home.mods && home.mods.length > 0) {
      mods = home.mods;
    } else {
      const modData = await this.api.mods();
      mods = modData.items || [];
    }
    this.mods = mods;
    this.employees = buildEmployees(mods);
    this.conversations = buildConversations(this.employees);
  }

  private async refreshHome(): Promise<void> {
    if (this.loading) {
      return;
    }
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
    this.messages = [
      {
        role: 'assistant',
        text: `${item.title} 已就绪。${item.employeeKey.length > 0 ? '这位员工来自企业端已安装模块。' : '这是固定服务入口。'}`
      }
    ];
  }

  private startEmployeeChat(employeeKey: string): void {
    const employee = findEmployee(this.employees, employeeKey);
    if (!employee) {
      return;
    }
    this.selectedEmployeeKey = '';
    this.selectedTab = TAB_MESSAGES;
    this.openConversation({
      id: `employee:${employee.key}`,
      title: employee.name,
      subtitle: employee.summary,
      badge: '已安装',
      avatar: employee.avatarText,
      source: employee.modName,
      employeeKey: employee.key
    });
  }

  private async sendChatMessage(): Promise<void> {
    if (this.loading) {
      return;
    }
    const text = this.chatInput.trim();
    if (text.length === 0) {
      return;
    }
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
    if (this.activeEmployeeKey.length === 0) {
      return text;
    }
    const employee = findEmployee(this.employees, this.activeEmployeeKey);
    if (!employee) {
      return text;
    }
    return `请以企业端员工「${employee.name}」身份处理：${text}\n来源模块：${employee.modName}\n员工标识：${employee.employeeId}\n接口路径：${employee.apiBasePath}`;
  }

  private extractReply(response: ChatResponseData): string {
    const direct = cleanText(response.reply);
    if (direct.length > 0) {
      return direct;
    }
    if (response.data) {
      const nested = cleanText(response.data.reply, cleanText(response.data.content, cleanText(response.data.message)));
      if (nested.length > 0) {
        return nested;
      }
    }
    return cleanText(response.message, '服务端已返回，但没有可展示内容');
  }

  private logout(): void {
    this.accessToken = '';
    this.sessionId = '';
    this.api.setAccessToken('');
    this.loggedIn = false;
    this.selectedTab = TAB_MESSAGES;
    this.selectedEmployeeKey = '';
    this.activeConversationId = '';
    this.mods = [];
    this.employees = [];
    this.conversations = buildConversations([]);
    this.statusText = '已退出企业账号';
  }

  private currentEmployee(): AiEmployeeProfile | undefined {
    return findEmployee(this.employees, this.selectedEmployeeKey);
  }

  private currentEmployeeName(): string {
    const employee = this.currentEmployee();
    return employee ? employee.name : 'AI 员工';
  }

  private currentEmployeeTitle(): string {
    const employee = this.currentEmployee();
    return employee ? employee.title : '企业端员工';
  }

  private currentEmployeeSummary(): string {
    const employee = this.currentEmployee();
    return employee ? employee.summary : '员工资料暂不可用';
  }

  private currentEmployeeAvatar(): string {
    const employee = this.currentEmployee();
    return employee ? employee.avatarText : 'AI';
  }

  private currentEmployeeModName(): string {
    const employee = this.currentEmployee();
    return employee ? employee.modName : '';
  }

  private currentEmployeeId(): string {
    const employee = this.currentEmployee();
    return employee ? employee.employeeId : '';
  }

  private currentEmployeeApiPath(): string {
    const employee = this.currentEmployee();
    return employee ? employee.apiBasePath : '';
  }

  private currentEmployeePhoneChannel(): string {
    const employee = this.currentEmployee();
    return employee ? employee.phoneChannel : '';
  }

  private navGlyph(tab: number): string {
    if (tab === TAB_MESSAGES) {
      return 'M';
    }
    if (tab === TAB_CONTACTS) {
      return 'A';
    }
    if (tab === TAB_DISCOVER) {
      return 'O';
    }
    return 'U';
  }

  private errorMessage(err: object): string {
    const message = (err as Error).message;
    return cleanText(message, '未知错误');
  }
}
