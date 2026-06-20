/**
 * 固定伙伴资料页面。
 *
 * 对标 Android FixedPartnerProfileScreen：根据 partnerKind 展示固定伙伴
 * （客服 / 销售 / 技术支持）的资料卡片，包含头像、名称、职位、简介、
 * 联系方式与技能标签。底部"发起会话"按钮触发 onStartChat 回调。
 *
 * 本页使用本地 mock 数据，按 partnerKind 返回不同伙伴信息。
 */
@Component
export struct FixedPartnerProfilePage {
  @Prop partnerKind: string = '';

  onBack: () => void = () => {};
  onStartChat: () => void = () => {};

  @State profile: FixedPartnerProfile | null = null;

  aboutToAppear(): void {
    this.profile = this.buildProfile(this.partnerKind);
  }

  build() {
    Column() {
      this.Header();
      Scroll() {
        Column({ space: 12 }) {
          if (this.profile === null) {
            this.EmptyCard('未找到伙伴', '未识别到对应的固定伙伴，请返回重试。');
          } else {
            this.ProfileHeaderCard(this.profile as FixedPartnerProfile);
            this.SummaryCard(this.profile as FixedPartnerProfile);
            this.ContactCard(this.profile as FixedPartnerProfile);
            this.SkillsCard(this.profile as FixedPartnerProfile);
          }
        }
        .width('100%')
        .padding({ bottom: 24 });
      }
      .width('100%')
      .layoutWeight(1);

      if (this.profile !== null) {
        this.BottomAction();
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor('#F4F6F8');
  }

  @Builder
  Header() {
    Row({ space: 12 }) {
      Text('<')
        .width(36)
        .height(36)
        .fontSize(22)
        .fontColor('#111827')
        .textAlign(TextAlign.Center)
        .onClick(() => this.onBack());
      Column({ space: 2 }) {
        Text(this.headerTitle())
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .fontColor('#111827')
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis });
        Text('固定伙伴资料')
          .fontSize(13)
          .fontColor('#4B5563');
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 14, bottom: 12 })
    .backgroundColor('#FFFFFF')
    .border({ width: { bottom: 1 }, color: '#E5E7EB' });
  }

  @Builder
  ProfileHeaderCard(profile: FixedPartnerProfile) {
    Row({ space: 16 }) {
      Text(profile.avatarText)
        .width(72)
        .height(72)
        .borderRadius(16)
        .fontSize(26)
        .fontWeight(FontWeight.Bold)
        .fontColor('#FFFFFF')
        .textAlign(TextAlign.Center)
        .backgroundColor(profile.accentColor);

      Column({ space: 4 }) {
        Text(profile.name)
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .fontColor('#111827')
          .maxLines(1);
        Text(profile.title)
          .fontSize(14)
          .fontColor('#4B5563')
          .maxLines(1);
        Text(`账号：${profile.accountId}`)
          .fontSize(12)
          .fontColor('#6B7280')
          .maxLines(1);
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);
    }
    .width('100%')
    .padding(18)
    .margin({ left: 14, right: 14, top: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  SummaryCard(profile: FixedPartnerProfile) {
    Column({ space: 8 }) {
      this.SectionLabel('简介');
      Text(profile.summary)
        .fontSize(14)
        .fontColor('#374151')
        .lineHeight(22);
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  ContactCard(profile: FixedPartnerProfile) {
    Column({ space: 0 }) {
      this.SectionLabel('联系方式');
      this.ContactRow('电话', profile.phone, true);
      this.ContactRow('邮箱', profile.email, true);
      this.ContactRow('工号', profile.employeeNo, false);
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  ContactRow(label: string, value: string, showDivider: boolean) {
    Row({ space: 12 }) {
      Text(label)
        .width(60)
        .fontSize(14)
        .fontColor('#4B5563');
      Text(value)
        .fontSize(14)
        .fontColor('#111827')
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
        .layoutWeight(1);
    }
    .width('100%')
    .padding({ top: 10, bottom: 10 })
    .border({ width: { bottom: showDivider ? 1 : 0 }, color: '#F3F4F6' });
  }

  @Builder
  SkillsCard(profile: FixedPartnerProfile) {
    Column({ space: 10 }) {
      this.SectionLabel('技能标签');
      Flex({ wrap: FlexWrap.Wrap }) {
        ForEach(profile.skills, (skill: string) => {
          Text(skill)
            .fontSize(12)
            .fontColor(profile.accentColor)
            .padding({ left: 12, right: 12, top: 6, bottom: 6 })
            .backgroundColor(this.skillBgColor(profile.accentColor))
            .borderRadius(12)
            .margin({ right: 8, bottom: 8 });
        }, (skill: string, index: number) => `${skill}-${index}`);
      }
      .width('100%');
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  SectionLabel(text: string) {
    Text(text)
      .fontSize(13)
      .fontWeight(FontWeight.Medium)
      .fontColor('#6B7280');
  }

  @Builder
  BottomAction() {
    Column() {
      Button('发起会话')
        .height(48)
        .fontSize(16)
        .fontWeight(FontWeight.Medium)
        .fontColor('#FFFFFF')
        .backgroundColor('#1D4ED8')
        .borderRadius(12)
        .width('100%')
        .onClick(() => this.onStartChat());
    }
    .width('100%')
    .padding({ left: 14, right: 14, top: 8, bottom: 14 })
    .backgroundColor('#FFFFFF')
    .border({ width: { top: 1 }, color: '#E5E7EB' });
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
    .padding(24)
    .margin({ left: 14, right: 14 })
    .alignItems(HorizontalAlign.Center)
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  private headerTitle(): string {
    if (this.partnerKind === 'cs') return '专属客服';
    if (this.partnerKind === 'sales') return '销售顾问';
    if (this.partnerKind === 'support') return '技术支持';
    return '固定伙伴';
  }

  private skillBgColor(accent: string): string {
    if (accent === '#1D4ED8') return '#E8F0FF';
    if (accent === '#047857') return '#E7F7EE';
    if (accent === '#7C3AED') return '#F3E8FF';
    if (accent === '#B45309') return '#FEF3C7';
    if (accent === '#BE185D') return '#FCE7F3';
    return '#F3F4F6';
  }

  private buildProfile(partnerKind: string): FixedPartnerProfile | null {
    if (partnerKind === 'cs') {
      const profile: FixedPartnerProfile = {
        partnerKind: 'cs',
        name: '专属客服',
        title: '企业服务顾问',
        accountId: 'XCAGI-CS-001',
        avatarText: '客服',
        accentColor: '#1D4ED8',
        summary: '负责企业服务接待、问题反馈、订单跟进与人工协同支持。工作日 09:00-18:00 在线，紧急问题请优先发起会话。',
        phone: '400-888-0000',
        email: 'cs@xiu-ci.com',
        employeeNo: 'CS-001',
        skills: ['服务咨询', '进度跟进', '问题反馈', '人工协同', '订单支持']
      };
      return profile;
    }
    if (partnerKind === 'sales') {
      const profile: FixedPartnerProfile = {
        partnerKind: 'sales',
        name: '销售顾问',
        title: '企业销售经理',
        accountId: 'XCAGI-SALES-001',
        avatarText: '销售',
        accentColor: '#047857',
        summary: '负责产品咨询、方案报价、合同签订与客户关系维护。提供全流程销售支持，协助企业完成采购决策。',
        phone: '400-888-0001',
        email: 'sales@xiu-ci.com',
        employeeNo: 'SAL-001',
        skills: ['产品咨询', '方案报价', '合同签订', '客户关系', '招投标支持']
      };
      return profile;
    }
    if (partnerKind === 'support') {
      const profile: FixedPartnerProfile = {
        partnerKind: 'support',
        name: '技术支持',
        title: '企业技术工程师',
        accountId: 'XCAGI-SUP-001',
        avatarText: '技术',
        accentColor: '#7C3AED',
        summary: '负责系统部署、故障排查、接口对接与二次开发支持。7x24 小时响应紧急故障，提供远程与现场支持。',
        phone: '400-888-0002',
        email: 'support@xiu-ci.com',
        employeeNo: 'SUP-001',
        skills: ['系统部署', '故障排查', '接口对接', '二次开发', '性能优化']
      };
      return profile;
    }
    return null;
  }
}

/**
 * 固定伙伴资料本地数据模型。
 */
interface FixedPartnerProfile {
  partnerKind: string;
  name: string;
  title: string;
  accountId: string;
  avatarText: string;
  accentColor: string;
  summary: string;
  phone: string;
  email: string;
  employeeNo: string;
  skills: string[];
}
