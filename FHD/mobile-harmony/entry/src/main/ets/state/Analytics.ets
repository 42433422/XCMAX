import hilog from '@ohos.hilog';

// 可观测：结构化事件日志，对齐 Android core/observability/XcagiAnalytics.kt。
// Android 走 Firebase；鸿蒙此处走 hilog（结构化、可被 HiLog/HiAnalytics 采集），
// 统一 log(event[, key, value]) 接口 + sku 标签。真机/采集后端未接，仅本地结构化日志。
// 注：ArkTS 严格禁 Record 对象字面量，故用 log/logKv 显式入参而非 params 字典。

const DOMAIN = 0xA1A1;
const TAG = 'XcagiAnalytics';
const SKU = 'enterprise'; // 鸿蒙构建为企业版（bundle com.xiuci.xcagi.mobile.enterprise）

export class Analytics {
  static log(event: string): void {
    Analytics.emit(event, `sku=${SKU}`);
  }

  static logKv(event: string, key: string, value: string): void {
    Analytics.emit(event, `sku=${SKU} ${key}=${value}`);
  }

  private static emit(event: string, detail: string): void {
    hilog.info(DOMAIN, TAG, '%{public}s | %{public}s', event, detail);
  }
}
