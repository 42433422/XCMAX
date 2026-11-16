import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';

import '../../api/mobile_api.dart';
import '../../api/mobile_session_store.dart';

/// Pins a native page to the account and server it was opened with.
class NativeWorkspaceSession extends ChangeNotifier {
  NativeWorkspaceSession(this.api, {this.activeModId = ''}) {
    ready = _initialize();
  }
  final MobileApiClient api;
  final String activeModId;
  late final Future<void> ready;
  StreamSubscription<MobileSessionData>? _subscription;
  String? _identity;
  late String base;
  late int generation;
  bool active = true;

  String _key(MobileSessionData session) =>
      '${api.authGeneration}|${session.serverMode}|${session.fhdHost}|${session.localBaseUrl}';

  Future<void> _initialize() async {
    generation = api.authGeneration;
    final session = await api.loadSession();
    _identity = _key(session);
    base = await api.resolveSessionBaseUrl();
    final current = await api.loadSession();
    if (!active ||
        generation != api.authGeneration ||
        _key(current) != _identity) {
      throw StateError('账号已切换，请重新打开页面');
    }
    _subscription = api.sessionChanges.listen((session) {
      if (active && _key(session) != _identity) {
        active = false;
        notifyListeners();
      }
    });
  }

  Future<Map<String, Object?>> request(
    String path, {
    String method = 'GET',
    Map<String, String> query = const {},
    Map<String, Object?>? body,
  }) async {
    await ready;
    if (!active) throw StateError('账号或连接已切换，请重新打开页面');
    final result = await api.workspaceRequest(path,
        method: method,
        query: query,
        body: body,
        expectedGeneration: generation,
        expectedBase: base,
        activeModId: activeModId);
    if (!active) throw StateError('账号或连接已切换，请重新打开页面');
    if (result['success'] != true) {
      throw StateError(result['message']?.toString() ?? '操作未完成，请重试');
    }
    return result;
  }

  Future<List<int>> download(String path,
      {Map<String, String> query = const {}}) async {
    await ready;
    if (!active) throw StateError('账号或连接已切换');
    final bytes = await api.workspaceFileRequest(path,
        query: query,
        expectedGeneration: generation,
        expectedBase: base,
        activeModId: activeModId);
    if (!active) throw StateError('账号或连接已切换');
    return bytes;
  }

  Future<Map<String, Object?>> upload(String path, List<int> bytes, String name,
      {String field = 'file'}) async {
    await ready;
    if (!active) throw StateError('账号或连接已切换');
    final result = await api.workspaceFileRequest(path,
        upload: bytes,
        name: name,
        field: field,
        expectedGeneration: generation,
        expectedBase: base,
        activeModId: activeModId);
    if (!active) throw StateError('账号或连接已切换');
    final decoded = jsonDecode(utf8.decode(result));
    if (decoded is! Map || decoded['success'] != true) {
      throw StateError(
          decoded is Map ? '${decoded['message'] ?? '导入失败'}' : '导入结果无效');
    }
    return Map<String, Object?>.from(decoded);
  }

  @override
  void dispose() {
    active = false;
    unawaited(_subscription?.cancel());
    super.dispose();
  }
}
