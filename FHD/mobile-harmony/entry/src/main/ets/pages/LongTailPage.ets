/**
 * 长尾财务分析页面。
 *
 * 对标 Android feature/finance/LongTailScreen.kt，
 * 展示长尾客户的月度财务数据与趋势，顶部统计卡片汇总总客户数、总金额、平均金额。
 */
interface LongTailCustomer {
  customerId: string;
  customerName: string;
  monthlyAmount: number;
  trend: string; // 'up' | 'down' | 'flat'
  trendPercent: number;
}

interface LongTailSummary {
  totalCustomers: number;
  totalAmount: number;
  averageAmount: number;
}

@Component
export struct LongTailPage {
  onBack: () => void = () => {};

  build() {
    Column() {
      this.Header();
      Scroll() {
        Column({ space: 14 }) {
          this.SummaryCard();
          this.CustomerListCard();
        }
        .width('100%')
        .padding({ left: 14, right: 14, top: 16, bottom: 24 });
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
      Text('长尾分析')
        .fontSize(20)
        .fontWeight(FontWeight.Bold)
        .fontColor('#111827')
        .layoutWeight(1);
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 14, bottom: 12 })
    .backgroundColor('#FFFFFF')
    .border({ width: { bottom: 1 }, color: '#E5E7EB' });
  }

  @Builder
  SummaryCard() {
    Column({ space: 12 }) {
      Text('概览')
        .fontSize(13)
        .fontColor('#6B7280')
        .width('100%');
      Row() {
        this.StatItem('总客户数', `${this.summary().totalCustomers}`, '家');
        this.StatItem('总金额', `¥${this.formatAmount(this.summary().totalAmount)}`, '');
        this.StatItem('平均金额', `¥${this.formatAmount(this.summary().averageAmount)}`, '');
      }
      .width('100%');
    }
    .width('100%')
    .padding(16)
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  StatItem(label: string, value: string, unit: string) {
    Column({ space: 4 }) {
      Text(label)
        .fontSize(12)
        .fontColor('#6B7280');
      Row({ space: 2 }) {
        Text(value)
          .fontSize(18)
          .fontWeight(FontWeight.Bold)
          .fontColor('#111827');
        if (unit.length > 0) {
          Text(unit)
            .fontSize(12)
            .fontColor('#6B7280');
        }
      }
      .alignItems(VerticalAlign.Bottom);
    }
    .alignItems(HorizontalAlign.Start)
    .layoutWeight(1);
  }

  @Builder
  CustomerListCard() {
    Column() {
      Text('客户明细')
        .fontSize(13)
        .fontColor('#6B7280')
        .width('100%')
        .padding({ bottom: 8 });
      ForEach(this.customers(), (customer: LongTailCustomer) => {
        this.CustomerRow(customer);
      }, (customer: LongTailCustomer) => customer.customerId);
    }
    .width('100%')
    .padding(16)
    .backgroundColor('#FFFFFF')
    .borderRadius(14)
    .border({ width: 1, color: '#E5E7EB' });
  }

  @Builder
  CustomerRow(customer: LongTailCustomer) {
    Row({ space: 12 }) {
      Column({ space: 2 }) {
        Text(customer.customerName)
          .fontSize(15)
          .fontWeight(FontWeight.Medium)
          .fontColor('#111827')
          .maxLines(1);
        Text(`¥${this.formatAmount(customer.monthlyAmount)}/月`)
          .fontSize(13)
          .fontColor('#4B5563');
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1);

      this.TrendBadge(customer);
    }
    .width('100%')
    .padding({ top: 12, bottom: 12 })
    .border({ width: { bottom: 1 }, color: '#F1F5F9' });
  }

  @Builder
  TrendBadge(customer: LongTailCustomer) {
    Row({ space: 4 }) {
      Text(this.trendIcon(customer.trend))
        .fontSize(13)
        .fontColor(this.trendColor(customer.trend));
      Text(`${customer.trendPercent}%`)
        .fontSize(13)
        .fontWeight(FontWeight.Medium)
        .fontColor(this.trendColor(customer.trend));
    }
    .padding({ left: 10, right: 10, top: 5, bottom: 5 })
    .backgroundColor(this.trendBgColor(customer.trend))
    .borderRadius(10);
  }

  private summary(): LongTailSummary {
    const list = this.customers();
    let total = 0;
    for (let i = 0; i < list.length; i++) {
      total += list[i].monthlyAmount;
    }
    const avg = list.length > 0 ? Math.round(total / list.length) : 0;
    const s: LongTailSummary = {
      totalCustomers: list.length,
      totalAmount: total,
      averageAmount: avg
    };
    return s;
  }

  private customers(): LongTailCustomer[] {
    const list: LongTailCustomer[] = [
      { customerId: 'c001', customerName: '成都锦绣文创', monthlyAmount: 12800, trend: 'up', trendPercent: 12 },
      { customerId: 'c002', customerName: '重庆山城手作', monthlyAmount: 8600, trend: 'down', trendPercent: 5 },
      { customerId: 'c003', customerName: '昆明云艺工坊', monthlyAmount: 5400, trend: 'up', trendPercent: 8 },
      { customerId: 'c004', customerName: '西安唐风礼品', monthlyAmount: 3200, trend: 'flat', trendPercent: 0 },
      { customerId: 'c005', customerName: '贵阳黔韵特产', monthlyAmount: 2100, trend: 'up', trendPercent: 15 },
      { customerId: 'c006', customerName: '南宁桂风小铺', monthlyAmount: 1800, trend: 'down', trendPercent: 3 },
      { customerId: 'c007', customerName: '兰州陇上百货', monthlyAmount: 1200, trend: 'flat', trendPercent: 0 }
    ];
    return list;
  }

  private formatAmount(amount: number): string {
    const str = amount.toString();
    if (str.length <= 3) {
      return str;
    }
    let result = '';
    for (let i = 0; i < str.length; i++) {
      if (i > 0 && (str.length - i) % 3 === 0) {
        result += ',';
      }
      result += str.charAt(i);
    }
    return result;
  }

  private trendIcon(trend: string): string {
    if (trend === 'up') return '↑';
    if (trend === 'down') return '↓';
    return '→';
  }

  private trendColor(trend: string): string {
    if (trend === 'up') return '#166534';
    if (trend === 'down') return '#991B1B';
    return '#6B7280';
  }

  private trendBgColor(trend: string): string {
    if (trend === 'up') return '#DCFCE7';
    if (trend === 'down') return '#FEE2E2';
    return '#F3F4F6';
  }
}
