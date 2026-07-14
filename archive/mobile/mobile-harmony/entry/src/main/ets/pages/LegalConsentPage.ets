/**
 * 用户协议与隐私政策同意页。
 *
 * 对标 Android feature/legal/LegalConsentScreen.kt，
 * 展示协议文本，底部提供"不同意"和"同意并继续"两个按钮。
 */
interface LegalSection {
  title: string;
  body: string;
}

const APP_NAME = 'XCAGI 企业版';
const COMPANY_NAME = '成都修茈科技有限公司';
const LEGAL_UPDATED_AT = '2026-06-25';

@Component
export struct LegalConsentPage {
  onBack: () => void = () => {};
  onAgree: () => void = () => {};

  build() {
    Column() {
      this.Header();
      Scroll() {
        Column({ space: 14 }) {
          this.IntroCard();
          ForEach(this.legalSections(), (section: LegalSection) => {
            this.SectionCard(section);
          }, (section: LegalSection) => section.title);
        }
        .width('100%')
        .padding({ left: 14, right: 14, top: 16, bottom: 24 });
      }
      .width('100%')
      .layoutWeight(1);
      this.BottomBar();
    }
    .width('100%')
    .height('100%')
    .backgroundColor('#F4F6F8');
  }

  @Builder
  Header() {
    Row() {
      Text('用户协议与隐私政策')
        .fontSize(20)
        .fontWeight(FontWeight.Bold)
        .fontColor('#111827')
        .layoutWeight(1)
        .textAlign(TextAlign.Center);
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 14, bottom: 12 })
    .backgroundColor('#FFFFFF')
    .border({ width: { bottom: 1 }, color: '#E5E7EB' });
  }

  @Builder
  IntroCard() {
    Column({ space: 8 }) {
      Text(APP_NAME)
        .fontSize(18)
        .fontWeight(FontWeight.Bold)
        .fontColor('#111827');
      Text(`更新日期：${LEGAL_UPDATED_AT}`)
        .fontSize(13)
        .fontColor('#6B7280');
      Text(`欢迎使用 ${APP_NAME}。在继续使用前，请仔细阅读以下协议。点击"同意并继续"即表示您已阅读并同意本协议。`)
        .fontSize(14)
        .fontColor('#374151')
        .lineHeight(22);
    }
    .width('100%')
    .padding(16)
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  SectionCard(section: LegalSection) {
    Column({ space: 8 }) {
      Text(section.title)
        .fontSize(16)
        .fontWeight(FontWeight.Bold)
        .fontColor('#111827');
      Text(section.body)
        .fontSize(14)
        .fontColor('#374151')
        .lineHeight(22);
    }
    .width('100%')
    .padding(16)
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  BottomBar() {
    Row({ space: 12 }) {
      Button('不同意')
        .height(48)
        .fontSize(16)
        .fontColor('#374151')
        .backgroundColor('#F3F4F6')
        .borderRadius(10)
        .layoutWeight(1)
        .onClick(() => this.onBack());
      Button('同意并继续')
        .height(48)
        .fontSize(16)
        .fontWeight(FontWeight.Medium)
        .fontColor('#FFFFFF')
        .backgroundColor('#1D4ED8')
        .borderRadius(10)
        .layoutWeight(1)
        .onClick(() => this.onAgree());
    }
    .width('100%')
    .padding({ left: 14, right: 14, top: 12, bottom: 12 })
    .backgroundColor('#FFFFFF')
    .border({ width: { top: 1 }, color: '#E5E7EB' });
  }

  private legalSections(): LegalSection[] {
    const sections: LegalSection[] = [
      {
        title: '一、服务说明',
        body: `${APP_NAME}（以下简称"本应用"）由${COMPANY_NAME}提供，面向企业用户提供智能办公协同、AI 员工调度、审批处理、消息沟通和 MOD 插件市场等功能。本应用需连接企业后端服务，业务数据按企业部署策略存储与处理。`
      },
      {
        title: '二、用户账号',
        body: '用户需通过企业端管理员分配的账号登录本应用。用户应妥善保管账号与密码，不得将账号转借他人。因账号保管不善导致的一切后果由用户自行承担。注册或登录时提供的信息将用于身份验证与企业归属确认。'
      },
      {
        title: '三、隐私保护',
        body: '本应用仅收集为提供功能所必需的信息，包括企业标识、用户身份、会话记录、操作日志、设备与网络状态等。相机、通知等设备能力仅在用户授权后用于扫码配对、消息提醒等明确场景。未经用户或企业授权，不会向无关第三方共享个人信息。'
      },
      {
        title: '四、用户行为规范',
        body: '用户不得利用本应用从事违法、违规或侵犯他人权益的活动。不得发布、传播违法信息，不得攻击、干扰服务正常运行。如发现违规行为，平台有权暂停或终止相关服务。'
      },
      {
        title: '五、知识产权',
        body: `本应用的软件、文档、界面设计、商标及相关知识产权归${COMPANY_NAME}或合法权利人所有。未经授权，不得复制、修改、传播或用于商业用途。MOD 插件的知识产权归各自开发者或权利人所有。`
      },
      {
        title: '六、免责声明',
        body: '因网络故障、设备问题、企业后端不可用、第三方服务中断或不可抗力导致的服务中断或数据损失，平台将在合理范围内协助处理。用户和企业管理员应按内部制度备份重要数据。'
      },
      {
        title: '七、协议变更',
        body: '本协议可能随应用升级而更新。更新后的协议将在应用内提示，用户继续使用即视为同意。如有重大变更将通过应用内提示或企业管理员通知。'
      }
    ];
    return sections;
  }
}
