import { DutyAreaGroup, DutyEmployee, DutyRosterData } from '../models/MobileModels';

/**
 * 员工入岗 / 值班编制页面。
 *
 * 对标前端 DutyRosterWorkflowLoopView 与 Android 管理端 duty 员工视图，
 * 展示「部门区域 → 在岗员工」组织架构。点击员工可发起会话。
 */
@Component
export struct DutyRosterPage {
  @Consume dutyRoster: DutyRosterData;
  @Consume loading: boolean;

  onBack: () => void = () => {};
  onStartEmployeeChat: (employeeKey: string) => void = () => {};

  build() {
    this.DutyArea();
  }

  @Builder
  DutyArea() {
    Column() {
      this.Header();
      Scroll() {
        Column({ space: 12 }) {
          this.SummaryCard();
          if (this.dutyRoster.areas.length === 0) {
            this.EmptyCard('暂无在岗员工', '企业端尚未同步值班编制数据。连接企业端后，在岗员工会按区域展示在这里。');
          } else {
            ForEach(this.dutyRoster.areas, (area: DutyAreaGroup) => {
              this.AreaCard(area);
            }, (area: DutyAreaGroup) => area.areaId);
          }
        }
        .width('100%')
        .padding({ bottom: 24 });
      }
      .width('100%')
      .layoutWeight(1);
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
        Text('员工入岗')
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .fontColor('#111827');
        Text('值班编制组织架构')
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
  SummaryCard() {
    Column({ space: 10 }) {
      Row({ space: 8 }) {
        Text('在岗 / 编制')
          .fontSize(15)
          .fontColor('#374151')
          .layoutWeight(1);
        Text(`${this.dutyRoster.totalOnDuty} / ${this.dutyRoster.totalPlanned}`)
          .fontSize(22)
          .fontWeight(FontWeight.Bold)
          .fontColor('#18A85F');
      }
      .width('100%');

      // 入岗率进度条
      Row() {
        Row()
          .width(`${this.dutyPercent()}%`)
          .height(8)
          .backgroundColor('#18A85F')
          .borderRadius({ topLeft: 4, bottomLeft: 4 });
      }
      .width('100%')
      .height(8)
      .backgroundColor('#E5E7EB')
      .borderRadius(4);

      Text(`入岗率 ${this.dutyPercent()}% · 共 ${this.dutyRoster.areas.length} 个区域`)
        .fontSize(12)
        .fontColor('#6B7280');
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14, top: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  AreaCard(area: DutyAreaGroup) {
    Column({ space: 10 }) {
      Row() {
        Column({ space: 2 }) {
          Text(area.areaLabel)
            .fontSize(16)
            .fontWeight(FontWeight.Medium)
            .fontColor('#111827')
            .maxLines(1);
          Text(`${area.onDutyCount} / ${area.plannedCount} 在岗`)
            .fontSize(12)
            .fontColor(area.onDutyCount >= area.plannedCount ? '#166534' : '#92400E');
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1);

        Text(area.onDutyCount >= area.plannedCount ? '满编' : (area.onDutyCount === 0 ? '空岗' : '缺编'))
          .fontSize(12)
          .fontColor(area.onDutyCount >= area.plannedCount ? '#166534' : (area.onDutyCount === 0 ? '#991B1B' : '#92400E'))
          .padding({ left: 10, right: 10, top: 5, bottom: 5 })
          .backgroundColor(area.onDutyCount >= area.plannedCount ? '#E7F7EE' : (area.onDutyCount === 0 ? '#FEE2E2' : '#FEF3C7'))
          .borderRadius(10);
      }
      .width('100%');

      if (area.employees.length === 0) {
        Text('该区域暂无在岗员工')
          .fontSize(13)
          .fontColor('#9CA3AF')
          .padding({ top: 6, bottom: 6 });
      } else {
        ForEach(area.employees, (employee: DutyEmployee) => {
          this.EmployeeRow(employee);
        }, (employee: DutyEmployee) => employee.key);
      }
    }
    .width('100%')
    .padding(16)
    .margin({ left: 14, right: 14 })
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  EmployeeRow(employee: DutyEmployee) {
    Row({ space: 12 }) {
      Text(employee.avatarText)
        .width(40)
        .height(40)
        .borderRadius(12)
        .fontSize(16)
        .fontWeight(FontWeight.Bold)
        .fontColor('#FFFFFF')
        .textAlign(TextAlign.Center)
        .backgroundColor(this.areaColor(employee.areaId));

      Column({ space: 2 }) {
        Text(employee.name)
          .fontSize(15)
          .fontWeight(FontWeight.Medium)
          .fontColor('#111827')
          .maxLines(1);
        Text(employee.title)
          .fontSize(12)
          .fontColor('#4B5563')
          .maxLines(1);
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);

      Text(employee.status === 'on_duty' ? '在岗' : employee.status)
        .fontSize(11)
        .fontColor(employee.status === 'on_duty' ? '#166534' : '#6B7280')
        .padding({ left: 8, right: 8, top: 3, bottom: 3 })
        .backgroundColor(employee.status === 'on_duty' ? '#E7F7EE' : '#F3F4F6')
        .borderRadius(8);
    }
    .width('100%')
    .padding({ top: 8, bottom: 8 })
    .onClick(() => this.onStartEmployeeChat(employee.key));
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

  private dutyPercent(): number {
    if (this.dutyRoster.totalPlanned === 0) return 0;
    return Math.min(100, Math.round((this.dutyRoster.totalOnDuty / this.dutyRoster.totalPlanned) * 100));
  }

  private areaColor(areaId: string): string {
    // 按区域分配稳定配色，对标前端组织架构图分区色
    if (areaId === 'site-and-marketing') return '#1D4ED8';
    if (areaId === 'server-and-ops') return '#7C3AED';
    if (areaId === 'modstore-backend') return '#047857';
    if (areaId === 'modstore-frontend') return '#B45309';
    if (areaId === 'platform-core') return '#BE185D';
    if (areaId === 'quality-and-docs') return '#0369A1';
    if (areaId === 'craft-workshop') return '#C2410C';
    if (areaId === 'partner-ecosystem') return '#4338CA';
    return '#4B5563';
  }
}
