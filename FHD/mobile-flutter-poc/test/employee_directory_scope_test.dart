import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/data/offline/mobile_offline_store.dart';

const _lan = 'http://10.0.0.9:5011/';
const _cached = <String, Object?>{
  'id': 'cached-mod',
  'name': '缓存目录',
  '_mobile_cache_base_url': _lan,
  'workflow_employees': [
    {'id': 'cached-employee', 'label': '缓存员工'}
  ],
};
const _session = MobileSessionData(
  accessToken: 'account-a',
  userId: 1,
  username: 'a',
  accountKind: 'enterprise',
  serverMode: 'lan',
  fhdHost: '10.0.0.9:5011',
  localBaseUrl: _lan,
  cachedModInfos: [_cached],
);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  for (final change in ['account', 'backend']) {
    test('late directory response cannot replace cache after $change switch',
        () async {
      final api = _DirectoryApi();
      final repository = _Repository(api);
      addTearDown(() async {
        await repository.dispose();
        api.dispose();
      });
      final loading = repository.loadModInfos();
      final rejected = expectLater(
          loading,
          throwsA(isA<MobileApiException>()
              .having((e) => e.statusCode, 'status', 409)));
      await api.requested.future;
      if (change == 'account') {
        await api.persistLoginSession({
          'access_token': 'account-b',
          'user': {'id': 2, 'username': 'b'}
        }, fallbackUsername: 'b', fallbackAccountKind: 'enterprise');
      } else {
        await api.saveLocalSettings(serverMode: 'cloud');
      }
      api.response.complete(
          const MobileEnvelope(success: true, message: '', raw: {}, data: [
        {'pack_id': 'old-private-employee', 'label': '旧账号员工'}
      ]));
      await rejected;
      final cached = (await api.loadSession()).cachedModInfos;
      expect(cached.any((m) => m['id'] == 'admin-duty-employees'), isFalse);
      if (change == 'account') expect(cached, isEmpty);
      if (change == 'backend') expect(cached.single['id'], 'cached-mod');
    });
  }
  test(
      'same backend offline directory survives but is hidden on another backend',
      () async {
    final api = _DirectoryApi();
    final repository = _Repository(api);
    addTearDown(() async {
      await repository.dispose();
      api.dispose();
    });
    Future<List<String>> employees() async =>
        (await repository.loadCachedConversations(adminMode: false))
            .where((c) => c.id.startsWith('employee:'))
            .map((c) => c.id)
            .toList();
    expect(await employees(), ['employee:cached-mod:cached-employee']);
    await api.saveLocalSettings(serverMode: 'cloud');
    expect(await employees(), isEmpty);
    await api.saveLocalSettings(serverMode: 'lan');
    expect(await employees(), ['employee:cached-mod:cached-employee']);
  });
  test(
      'directory cache transaction rejects a backend change queued ahead of it',
      () async {
    final api = _DirectoryApi();
    addTearDown(api.dispose);
    final captured = await api.loadSession();
    final switching = api.saveLocalSettings(serverMode: 'cloud');
    final caching = api.cacheModInfos([
      {'id': 'late-cache'}
    ],
        authGeneration: api.authGeneration,
        expectedSession: captured,
        expectedBaseUrl: _lan);
    await switching;
    await caching;
    expect((await api.loadSession()).cachedModInfos.single['id'], 'cached-mod');
  });
}

class _DirectoryApi extends MobileApiClient {
  _DirectoryApi() : super(sessionStore: MemoryMobileSessionStore(_session));
  final requested = Completer<void>();
  final response = Completer<MobileEnvelope<List<Map<String, Object?>>>>();
  @override
  Future<MobileEnvelope<List<Map<String, Object?>>>> employeeDirectory() {
    requested.complete();
    return response.future;
  }
}

class _Repository extends MobileRepository {
  _Repository(MobileApiClient api) : super(client: api);
  @override
  Future<MobileOfflineStore?> openOfflineStore({String? expectedScope}) async =>
      null;
}
