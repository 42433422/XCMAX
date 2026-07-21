// 纯 Flutter 实现的自治持久化 store。
//
// 使用 shared_preferences 持久化崩溃计数 + SafeMode 状态，
// 使用 path_provider 写审计日志到 applicationDocumentsDirectory/autonomy/audit.jsonl。
// 不依赖任何原生 MethodChannel，Android + iOS 共享同一份 Dart 实现。

import 'dart:async';
import 'dart:convert';
import 'dart:io' show Directory, File, FileMode, IOSink, Platform;

import 'package:package_info_plus/package_info_plus.dart';
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'mobile_autonomy_types.dart';

/// shared_preferences 键名前缀。
const String kPrefPrefix = 'xcagi.autonomy.';

/// 审计日志子目录。
const String kAuditDirName = 'autonomy';

/// 审计日志文件名。
const String kAuditFileName = 'audit.jsonl';

/// 基于 shared_preferences + path_provider 的纯 Flutter 自治 store。
///
/// 生产用法：
/// ```dart
/// final store = await SharedPreferencesAutonomyStore.create();
/// ```
///
/// 测试用法：通过构造函数注入 fake 实现。
class SharedPreferencesAutonomyStore implements MobileAutonomyStore {
  SharedPreferencesAutonomyStore({
    required SharedPreferences preferences,
    required Future<File> Function() auditFileResolver,
    required Future<PackageInfo> Function() packageInfoResolver,
    required String Function() platformResolver,
  })  : _prefs = preferences,
        _auditFileResolver = auditFileResolver,
        _packageInfoResolver = packageInfoResolver,
        _platformResolver = platformResolver;

  /// 默认工厂：使用真实 shared_preferences + path_provider + Platform。
  static Future<SharedPreferencesAutonomyStore> create() async {
    final prefs = await SharedPreferences.getInstance();
    return SharedPreferencesAutonomyStore(
      preferences: prefs,
      auditFileResolver: _resolveDefaultAuditFile,
      packageInfoResolver: () => PackageInfo.fromPlatform(),
      platformResolver: _defaultPlatform,
    );
  }

  final SharedPreferences _prefs;
  final Future<File> Function() _auditFileResolver;
  final Future<PackageInfo> Function() _packageInfoResolver;
  final String Function() _platformResolver;

  IOSink? _auditSink;
  File? _cachedAuditFile;
  bool _auditOpenFailed = false;

  @override
  Future<MobileRuntimeTruthSnapshot> collectTruth() async {
    final info = await _packageInfoResolver();
    final versionCode = int.tryParse(info.buildNumber) ?? 0;
    return MobileRuntimeTruthSnapshot(
      platform: _platformResolver(),
      bootCount: _prefs.getInt('${kPrefPrefix}boot_count') ?? 0,
      crashCount: _prefs.getInt('${kPrefPrefix}crash_count') ?? 0,
      lastCrashTs: _prefs.getDouble('${kPrefPrefix}last_crash_ts') ?? 0,
      lastCrashKind: _prefs.getString('${kPrefPrefix}last_crash_kind') ?? '',
      lastGoodVersionCode:
          _prefs.getInt('${kPrefPrefix}last_good_version_code') ?? 0,
      lastGoodVersionName:
          _prefs.getString('${kPrefPrefix}last_good_version_name') ?? '',
      lastGoodTs: _prefs.getDouble('${kPrefPrefix}last_good_ts') ?? 0,
      currentVersionCode: versionCode,
      currentVersionName: info.version,
      safeMode: _prefs.getBool('${kPrefPrefix}safe_mode') ?? false,
      timestampMs: DateTime.now().millisecondsSinceEpoch.toDouble(),
    );
  }

  @override
  Future<MobileRuntimeTruthSnapshot> incrementStartupCrash() async {
    final bootCount = (_prefs.getInt('${kPrefPrefix}boot_count') ?? 0) + 1;
    final crashCount = (_prefs.getInt('${kPrefPrefix}crash_count') ?? 0) + 1;
    await _prefs.setInt('${kPrefPrefix}boot_count', bootCount);
    await _prefs.setInt('${kPrefPrefix}crash_count', crashCount);
    return collectTruth();
  }

  @override
  Future<void> recordStartupComplete({
    required int versionCode,
    required String versionName,
  }) async {
    final now = DateTime.now().millisecondsSinceEpoch.toDouble();
    await Future.wait([
      _prefs.setInt('${kPrefPrefix}crash_count', 0),
      _prefs.setInt('${kPrefPrefix}last_good_version_code', versionCode),
      _prefs.setString('${kPrefPrefix}last_good_version_name', versionName),
      _prefs.setDouble('${kPrefPrefix}last_good_ts', now),
      _prefs.setBool('${kPrefPrefix}safe_mode', false),
    ]);
  }

  @override
  Future<void> recordCrash({
    required String kind,
    required String detail,
  }) async {
    final now = DateTime.now().millisecondsSinceEpoch.toDouble();
    final crashCount = (_prefs.getInt('${kPrefPrefix}crash_count') ?? 0) + 1;
    await Future.wait([
      _prefs.setInt('${kPrefPrefix}crash_count', crashCount),
      _prefs.setDouble('${kPrefPrefix}last_crash_ts', now),
      _prefs.setString('${kPrefPrefix}last_crash_kind', kind),
    ]);
  }

  @override
  Future<void> enterSafeMode(String detail) async {
    await _prefs.setBool('${kPrefPrefix}safe_mode', true);
  }

  @override
  Future<void> exitSafeMode() async {
    await _prefs.setBool('${kPrefPrefix}safe_mode', false);
    await _prefs.setInt('${kPrefPrefix}crash_count', 0);
  }

  @override
  Future<void> appendAudit(MobileAutonomyAuditEntry entry) async {
    if (_auditOpenFailed) return;
    try {
      final sink = await _ensureAuditSink();
      final line = jsonEncode(entry.toJson());
      sink.writeln(line);
      await sink.flush();
    } catch (_) {
      _auditOpenFailed = true;
    }
  }

  Future<IOSink> _ensureAuditSink() async {
    if (_auditSink != null) return _auditSink!;
    _cachedAuditFile ??= await _auditFileResolver();
    _auditSink = _cachedAuditFile!.openWrite(mode: FileMode.writeOnlyAppend);
    return _auditSink!;
  }

  @override
  Future<void> dispose() async {
    try {
      await _auditSink?.flush();
    } catch (_) {}
    try {
      await _auditSink?.close();
    } catch (_) {}
    _auditSink = null;
    _auditOpenFailed = false;
  }
}

Future<File> _resolveDefaultAuditFile() async {
  final dir = await getApplicationDocumentsDirectory();
  final auditDir = Directory('${dir.path}/$kAuditDirName');
  if (!auditDir.existsSync()) {
    auditDir.createSync(recursive: true);
  }
  return File('${auditDir.path}/$kAuditFileName');
}

String _defaultPlatform() {
  if (Platform.isAndroid) return 'android';
  if (Platform.isIOS) return 'ios';
  if (Platform.isWindows) return 'windows';
  if (Platform.isMacOS) return 'macos';
  if (Platform.isLinux) return 'linux';
  return 'unknown';
}
