import { AiEmployeeProfile, DutyRosterData, ModInfo } from '../models/MobileModels';

const TAB_CONTACTS = 1;

@Component
export struct DiscoverPage {
  @Consume employees: AiEmployeeProfile[];
  @Consume baseUrl: string;
  @Consume mods: ModInfo[];
  @Consume selectedEmployeeKey: string;
  @Consume selectedTab: number;
  @Consume dutyRoster: DutyRosterData;

  onOpenDutyRoster: () => void = () => {};
  onOpenOverlay: (name: string) => void = () => {};

  build() {
    this.DiscoverArea();
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
          Text('查看动态 >')
            .fontSize(13)
            .fontColor('#1D4ED8');
        }
        .width('100%')
        .padding({ left: 18, right: 18, top: 18 })
        .onClick(() => this.onOpenOverlay('aicircle'));

        this.DutyRosterEntry();

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
  DutyRosterEntry() {
    Row({ space: 14 }) {
      // 组织架构图标（对标前端 admin-duty-graph 节点）
      Text('岗')
        .width(48)
        .height(48)
        .borderRadius(14)
        .fontSize(20)
        .fontWeight(FontWeight.Bold)
        .fontColor('#FFFFFF')
        .textAlign(TextAlign.Center)
        .backgroundColor('#BE185D');

      Column({ space: 3 }) {
        Text('员工入岗')
          .fontSize(17)
          .fontWeight(FontWeight.Medium)
          .fontColor('#111827')
          .maxLines(1);
        Text(`值班编制 · 在岗 ${this.dutyRoster.totalOnDuty} / ${this.dutyRoster.totalPlanned} · ${this.dutyRoster.areas.length} 个区域`)
          .fontSize(13)
          .fontColor('#4B5563')
          .maxLines(1);
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);

      Text('>')
        .fontSize(20)
        .fontColor('#9CA3AF');
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' })
    .onClick(() => this.onOpenDutyRoster());
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
}
