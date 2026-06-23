import { AiEmployeeProfile, FixedContactDto } from '../models/MobileModels';
import { findEmployee } from '../state/AppDataBuilder';

@Component
export struct ContactsPage {
  @Consume selectedEmployeeKey: string;
  @Consume employees: AiEmployeeProfile[];
  @Consume fixedTop: FixedContactDto[];
  @Consume fixedBottom: FixedContactDto[];

  onStartEmployeeChat: (employeeKey: string) => void = () => {};

  build() {
    this.ContactsArea();
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

          ForEach(this.fixedTop, (f: FixedContactDto) => {
            this.FixedContact(f.name, f.summary, f.avatar);
          }, (f: FixedContactDto) => f.id);

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

          ForEach(this.fixedBottom, (f: FixedContactDto) => {
            this.FixedContact(f.name, f.summary, f.avatar);
          }, (f: FixedContactDto) => f.id);
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
            this.onStartEmployeeChat(this.selectedEmployeeKey);
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
}
