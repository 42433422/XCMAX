// SharedPreferencesAutonomyStore 单元测试。
//
// 验证：
// - incrementStartupCrash 自增 boot_count + crash_count
// - recordStartupComplete 重置 crash_count + 记录 last_good
// - recordCrash 累加 crash_count + 记录 last_crash_*
// - enterSafeMode / exitSafeMode 切换 safe_mode
// - appendAudit 写入 jsonl 文件
// - collectTruth 返回所有字段
//
// 使用 SharedPreferences.setMockInitialValues 注入内存 mock。

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:xcagi_flutter_poc/src/autonomy/mobile_autonomy_store.dart';
import 'package:xcagi_flutter_poc/src/autonomy/mobile_autonomy_types.dart';

void main() {
  late SharedPreferences prefs;
  late File auditFile;
  late Directory tempDir;

  setUp(() async {
    TestWidgetsFlutterBinding.ensureInitialized();
    SharedPreferences.setMockInitialValues({});
    prefs = await SharedPreferences.getInstance();

    tempDir = await Directory.systemTemp.createTemp('autonomy_test_');
    auditFile = File('${tempDir.path}/audit.jsonl');
  });

  tearDown(() async {
    if (tempDir.existsSync()) {
      await tempDir.delete(recursive: true);
    }
  });

  SharedPreferencesAutonomyStore createStore({
    PackageInfo? packageInfo,
    String platform = 'test',
  }) {
    return SharedPreferencesAutonomyStore(
      preferences: prefs,
      auditFileResolver: () async => auditFile,
      packageInfoResolver: () async =>
          packageInfo ?? _fakePackageInfo(),
      platformResolver: () => platform,
    );
  }

  test('incrementStartupCrash increments boot_count + crash_count', () async {
    final store = createStore();
    await store.incrementStartupCrash();
    await store.incrementStartupCrash();
    await store.incrementStartupCrash();

    final truth = await store.collectTruth();
    expect(truth.bootCount, 3);
    expect(truth.crashCount, 3);
  });

  test('recordStartupComplete resets crash_count + records last_good', () async {
    final store = createStore();
    await store.incrementStartupCrash();
    await store.incrementStartupCrash();
    expect((await store.collectTruth()).crashCount, 2);

    await store.recordStartupComplete(versionCode: 10, versionName: '1.0.1');

    final truth = await store.collectTruth();
    expect(truth.crashCount, 0);
    expect(truth.lastGoodVersionCode, 10);
    expect(truth.lastGoodVersionName, '1.0.1');
    expect(truth.lastGoodTs, greaterThan(0));
    expect(truth.safeMode, false);
  });

  test('recordCrash increments crash_count + records last_crash_*', () async {
    final store = createStore();

    await store.recordCrash(kind: 'flutter_error', detail: 'build failed');
    await store.recordCrash(kind: 'platform_error', detail: 'async throw');

    final truth = await store.collectTruth();
    expect(truth.crashCount, 2);
    expect(truth.lastCrashKind, 'platform_error');
    expect(truth.lastCrashTs, greaterThan(0));
  });

  test('enterSafeMode + exitSafeMode toggle safe_mode', () async {
    final store = createStore();

    expect((await store.collectTruth()).safeMode, false);

    await store.enterSafeMode('crash loop');
    expect((await store.collectTruth()).safeMode, true);

    await store.exitSafeMode();
    expect((await store.collectTruth()).safeMode, false);
    expect((await store.collectTruth()).crashCount, 0);
  });

  test('appendAudit writes jsonl lines', () async {
    final store = createStore();

    await store.appendAudit(const MobileAutonomyAuditEntry(
      ts: 1000000,
      action: 'execute:enterSafeMode',
      risk: MobileAutonomyRiskLevel.medium,
      detail: 'crash loop',
      payload: {'crash_count': 3},
    ));
    await store.appendAudit(const MobileAutonomyAuditEntry(
      ts: 1000001,
      action: 'diagnosis:crash-loop-detected',
      risk: MobileAutonomyRiskLevel.medium,
      detail: 'detected',
      payload: {},
    ));
    await store.dispose();

    final lines = auditFile.readAsLinesSync();
    expect(lines.length, 2);
    expect(lines[0], contains('"action":"execute:enterSafeMode"'));
    expect(lines[0], contains('"risk":"medium"'));
    expect(lines[1], contains('"action":"diagnosis:crash-loop-detected"'));
  });

  test('collectTruth returns all fields correctly', () async {
    final store = createStore(
      packageInfo: PackageInfo(
        appName: 'XCAGI',
        packageName: 'com.xiuci.xcagi',
        version: '1.0.1',
        buildNumber: '10',
        buildSignature: '',
        installerStore: null,
      ),
      platform: 'android',
    );

    await store.incrementStartupCrash();
    await store.recordCrash(kind: 'flutter_error', detail: 'crash');
    await store.enterSafeMode('crash loop');

    final truth = await store.collectTruth();
    expect(truth.platform, 'android');
    expect(truth.bootCount, 1);
    expect(truth.crashCount, 2); // incrementStartupCrash(1) + recordCrash(1)
    expect(truth.lastCrashKind, 'flutter_error');
    expect(truth.currentVersionCode, 10);
    expect(truth.currentVersionName, '1.0.1');
    expect(truth.safeMode, true);
    expect(truth.timestampMs, greaterThan(0));
  });

  test('audit file open failure does not throw', () async {
    // 注入一个不存在的路径（父目录不存在），让 openWrite 失败
    final badFile = File('${tempDir.path}/nonexistent_dir/audit.jsonl');
    final store = SharedPreferencesAutonomyStore(
      preferences: prefs,
      auditFileResolver: () async => badFile,
      packageInfoResolver: () async => _fakePackageInfo(),
      platformResolver: () => 'test',
    );

    // 应该不抛异常（fail-open）
    await store.appendAudit(const MobileAutonomyAuditEntry(
      ts: 1000000,
      action: 'test',
      risk: MobileAutonomyRiskLevel.low,
      detail: 'should not throw',
      payload: {},
    ));

    // 第二次 appendAudit 也不抛（_auditOpenFailed 已标记）
    await store.appendAudit(const MobileAutonomyAuditEntry(
      ts: 1000001,
      action: 'test2',
      risk: MobileAutonomyRiskLevel.low,
      detail: 'second call',
      payload: {},
    ));

    await store.dispose();
  });
}

PackageInfo _fakePackageInfo() {
  return PackageInfo(
    appName: 'XCAGI',
    packageName: 'com.xiuci.xcagi',
    version: '1.0.0',
    buildNumber: '1',
    buildSignature: '',
    installerStore: null,
  );
}
