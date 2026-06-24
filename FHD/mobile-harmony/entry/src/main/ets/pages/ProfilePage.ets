import { AiEmployeeProfile, ConversationSummary, firstChar, ModInfo } from '../models/MobileModels';

@Component
export struct ProfilePage {
  @Consume displayName: string;
  @Consume accountKind: string;
  @Consume companyBrand: string;
  @Consume baseUrl: string;
  @Consume mods: ModInfo[];
  @Consume employees: AiEmployeeProfile[];
  @Consume conversations: ConversationSummary[];
  @Consume loading: boolean;

  onRefreshHome: () => void = () => {};
  onLogout: () => void = () => {};
  onOpenSettings: () => void = () => {};
  onOpenOverlay: (name: string) => void = () => {};

  build() {
    this.ProfileArea();
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

        // ── 全部功能入口网格（对标安卓 ProfileScreen 功能区） ──
        Column({ space: 12 }) {
          Text('全部功能')
            .fontSize(18)
            .fontWeight(FontWeight.Bold)
            .fontColor('#111827');
          Flex({ wrap: FlexWrap.Wrap }) {
            this.FeatureCell('审', '#1D4ED8', '审批', 'approval');
            this.FeatureCell('告', '#0369A1', '通知', 'notifications');
            this.FeatureCell('客', '#047857', '客服', 'cs');
            this.FeatureCell('IM', '#7C3AED', '消息', 'im');
            this.FeatureCell('企', '#BE185D', '企业模块', 'enterprise');
            this.FeatureCell('圈', '#B45309', 'AI圈子', 'aicircle');
            this.FeatureCell('扫', '#166534', '扫一扫', 'scan');
            this.FeatureCell('字', '#C2410C', '文字识别', 'ocr');
            this.FeatureCell('纪', '#0F766E', '会议纪要', 'meeting');
            this.FeatureCell('店', '#4338CA', '应用市场', 'market');
            this.FeatureCell('桥', '#6B7280', '服务桥', 'bridge');
            this.FeatureCell('尾', '#92400E', '长尾分析', 'longtail');
            this.FeatureCell('于', '#374151', '关于', 'about');
          }
          .width('100%');
        }
        .width('100%')
        .padding(18)
        .backgroundColor('#FFFFFF')
        .borderRadius(16)
        .border({ width: 1, color: '#E5E7EB' });

        Row({ space: 10 }) {
          Button('设置')
            .height(44)
            .fontSize(15)
            .fontColor('#1D4ED8')
            .backgroundColor('#E8F0FF')
            .borderRadius(12)
            .layoutWeight(1)
            .onClick(() => {
              this.onOpenSettings();
            });
        }
        .width('100%');

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
              this.onRefreshHome();
            });
          Button('退出')
            .height(44)
            .fontSize(15)
            .fontColor('#991B1B')
            .backgroundColor('#FEE2E2')
            .borderRadius(12)
            .layoutWeight(1)
            .onClick(() => {
              this.onLogout();
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

  @Builder
  FeatureCell(icon: string, color: string, label: string, overlay: string) {
    Column({ space: 8 }) {
      Text(icon)
        .width(44)
        .height(44)
        .borderRadius(12)
        .fontSize(18)
        .fontWeight(FontWeight.Bold)
        .fontColor('#FFFFFF')
        .textAlign(TextAlign.Center)
        .backgroundColor(color);
      Text(label)
        .fontSize(13)
        .fontColor('#374151');
    }
    .width('32%')
    .padding({ top: 12, bottom: 12 })
    .alignItems(HorizontalAlign.Center)
    .onClick(() => this.onOpenOverlay(overlay));
  }
}
