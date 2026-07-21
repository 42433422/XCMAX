// Flutter 移动端自治核心类型契约（纯 Dart，无原生通道）。
//
// 与桌面端 autonomy/types.ts 对齐，仅前缀 Mobile。
// 跨平台（Android + iOS 共享同一份 Dart 实现）。
// 设计参考：FHD/desktop/autonomy/types.ts。

/// 自治信号严重级别。
enum MobileAutonomySeverity {
  info,
  warn,
  crit,
  fatal,
}

/// 自治动作风险等级。
///
/// - [low]：日志记录 / noop，自动执行
/// - [medium]：SafeMode 软回滚（主路径），自动执行
/// - [high]：上报后端 + 强制 SafeMode，单次执行后必须 escalate
enum MobileAutonomyRiskLevel {
  low,
  medium,
  high,
}

/// 自治执行门禁。
///
/// - [auto]：满足条件自动执行
/// - [manual]：必须人工确认（保留枚举，当前未使用）
enum MobileAutonomyGate {
  auto,
  manual,
}

/// 移动端自治动作类型。
///
/// 纯 Flutter 自治不进行本地 APK/IPA 替换（系统沙盒禁止），
/// 只做 SafeMode 软回滚 + 后端上报。
enum MobileAutonomyActionType {
  /// 进入 SafeMode：渲染降级 UI，跳过新业务模块。
  enterSafeMode,

  /// 上报后端 crash_loop 事件。
  escalate,

  /// 不动作。
  noop,
}

/// 自治信号：被测系统的状态/事件输入。
class MobileAutonomySignal {
  const MobileAutonomySignal({
    required this.kind,
    required this.severity,
    required this.detail,
    required this.payload,
    required this.ts,
  });

  /// 信号种类，例如 `app_crash_loop` / `startup_exception`。
  final String kind;

  final MobileAutonomySeverity severity;

  final String detail;

  /// 任意附加数据，序列化为 Map<String, dynamic>。
  final Map<String, dynamic> payload;

  /// 信号时间戳（Unix ms）。
  final double ts;

  /// 去重 key：kind + ts（与桌面端 controller 一致）。
  String get dedupKey => '$kind@$ts';

  @override
  String toString() =>
      'MobileAutonomySignal(kind=$kind, severity=$severity, ts=$ts, detail=$detail)';
}

/// 自治诊断：policy 对信号的分析结果。
class MobileAutonomyDiagnosis {
  const MobileAutonomyDiagnosis({
    required this.id,
    required this.severity,
    required this.detail,
    this.payload = const {},
  });

  final String id;
  final MobileAutonomySeverity severity;
  final String detail;
  final Map<String, dynamic> payload;

  @override
  String toString() =>
      'MobileAutonomyDiagnosis(id=$id, severity=$severity, detail=$detail)';
}

/// 自治动作：policy 输出，由 controller 执行。
class MobileAutonomyAction {
  const MobileAutonomyAction({
    required this.type,
    required this.risk,
    required this.detail,
    required this.maxAttempts,
    required this.idempotencyKey,
    this.payload = const {},
    this.gate = MobileAutonomyGate.auto,
  });

  final MobileAutonomyActionType type;
  final MobileAutonomyRiskLevel risk;
  final String detail;
  final int maxAttempts;
  final String idempotencyKey;
  final Map<String, dynamic> payload;
  final MobileAutonomyGate gate;

  @override
  String toString() =>
      'MobileAutonomyAction(type=$type, risk=$risk, key=$idempotencyKey, max=$maxAttempts)';
}

/// 自治执行结果。
class MobileAutonomyActionResult {
  const MobileAutonomyActionResult({
    required this.action,
    required this.ok,
    this.note,
    this.error,
  });

  final MobileAutonomyAction action;
  final bool ok;
  final String? note;
  final String? error;

  @override
  String toString() =>
      'MobileAutonomyActionResult(action=$action, ok=$ok, error=$error)';
}

/// 自治计划：一组诊断 + 一组动作。
class MobileAutonomyPlan {
  const MobileAutonomyPlan({
    required this.diagnoses,
    required this.actions,
  });

  final List<MobileAutonomyDiagnosis> diagnoses;
  final List<MobileAutonomyAction> actions;

  static MobileAutonomyPlan empty() =>
      const MobileAutonomyPlan(diagnoses: [], actions: []);
}

/// 运行态真相快照：从持久化 store 读取。
class MobileRuntimeTruthSnapshot {
  const MobileRuntimeTruthSnapshot({
    required this.platform,
    required this.bootCount,
    required this.crashCount,
    required this.lastCrashTs,
    required this.lastCrashKind,
    required this.lastGoodVersionCode,
    required this.lastGoodVersionName,
    required this.lastGoodTs,
    required this.currentVersionCode,
    required this.currentVersionName,
    required this.safeMode,
    required this.timestampMs,
  });

  /// `"android"` / `"ios"`（由 [dart:io.Platform] 提供）。
  final String platform;
  final int bootCount;
  final int crashCount;
  final double lastCrashTs;
  final String lastCrashKind;
  final int lastGoodVersionCode;
  final String lastGoodVersionName;
  final double lastGoodTs;
  final int currentVersionCode;
  final String currentVersionName;
  final bool safeMode;
  final double timestampMs;

  factory MobileRuntimeTruthSnapshot.empty() =>
      const MobileRuntimeTruthSnapshot(
        platform: 'unknown',
        bootCount: 0,
        crashCount: 0,
        lastCrashTs: 0,
        lastCrashKind: '',
        lastGoodVersionCode: 0,
        lastGoodVersionName: '',
        lastGoodTs: 0,
        currentVersionCode: 0,
        currentVersionName: '',
        safeMode: false,
        timestampMs: 0,
      );

  @override
  String toString() => 'MobileRuntimeTruthSnapshot(platform=$platform, '
      'bootCount=$bootCount, crashCount=$crashCount, safeMode=$safeMode)';
}

/// 审计条目。
class MobileAutonomyAuditEntry {
  const MobileAutonomyAuditEntry({
    required this.ts,
    required this.action,
    required this.risk,
    required this.detail,
    this.payload = const {},
  });

  final double ts;
  final String action;
  final MobileAutonomyRiskLevel risk;
  final String detail;
  final Map<String, dynamic> payload;

  /// 序列化为 JSON 兼容的 Map（用于写入 jsonl 文件）。
  Map<String, dynamic> toJson() => {
        'ts': ts,
        'action': action,
        'risk': risk.name,
        'detail': detail,
        'payload': payload,
      };
}

/// 自治策略抽象类（纯函数）。
abstract class MobileAutonomyPolicy {
  /// 策略唯一 id。
  String get id;

  /// 关心的信号种类列表。
  List<String> get observedSignals;

  /// 输入匹配信号 + 运行态真相，输出诊断 + 动作。
  ///
  /// 必须是纯函数：相同输入产生相同输出，禁止 [DateTime.now]。
  MobileAutonomyPlan plan(
    List<MobileAutonomySignal> matched,
    MobileRuntimeTruthSnapshot truth,
  );
}

/// 持久化 store 抽象：负责崩溃计数 + SafeMode 状态 + 审计日志的存取。
///
/// 纯 Dart 实现（[SharedPreferencesAutonomyStore]），无原生通道。
/// 测试时可用 [FakeAutonomyStore] 替换。
abstract class MobileAutonomyStore {
  /// 读取运行态真相快照。
  Future<MobileRuntimeTruthSnapshot> collectTruth();

  /// 自增 boot_count + crash_count（启动开始时调用）。
  Future<MobileRuntimeTruthSnapshot> incrementStartupCrash();

  /// 重置 crash_count + 记录 last_good（启动完成时调用）。
  Future<void> recordStartupComplete({
    required int versionCode,
    required String versionName,
  });

  /// 记录一次崩溃事件。
  Future<void> recordCrash({required String kind, required String detail});

  /// 进入 SafeMode。
  Future<void> enterSafeMode(String detail);

  /// 退出 SafeMode（用户主动重试时调用）。
  Future<void> exitSafeMode();

  /// 追加审计日志（jsonl 格式，一行一条 JSON）。
  Future<void> appendAudit(MobileAutonomyAuditEntry entry);

  /// 释放资源。
  Future<void> dispose();
}

/// controller 配置。
class MobileAutonomyControllerOptions {
  const MobileAutonomyControllerOptions({
    this.tickIntervalMs = 30000,
    this.maxAuditRetries = 3,
    this.cooldownMs = 60000,
    this.enabled = true,
  });

  /// 自动 tick 间隔（毫秒）。0 表示禁用自动 tick，仅手动调用 [MobileAutonomyController.tickOnce]。
  final int tickIntervalMs;

  /// 审计写入失败重试次数。
  final int maxAuditRetries;

  /// 同一 action 的冷却窗口（毫秒）。
  final int cooldownMs;

  /// 是否启用 controller。false 时所有方法都是 noop。
  final bool enabled;
}
