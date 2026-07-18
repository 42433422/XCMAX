import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/policy/mobile_runtime_policy.dart';

class _MemorySessionStore implements MobileSessionStore {
  MobileSessionData _data = MobileSessionData.empty;

  @override
  Future<MobileSessionData> load() async => _data;

  @override
  Future<void> save(MobileSessionData session) async {
    _data = session;
  }

  @override
  Future<void> clear() async {
    _data = MobileSessionData.empty;
  }
}

void main() {
  setUp(MobileProductSkuConfig.resetRemoteSku);

  test('preferCloudIfLanUnreachable flips blank host to cloud', () async {
    final store = _MemorySessionStore();
    await store.save(const MobileSessionData(serverMode: 'lan', fhdHost: ''));
    final client = MobileApiClient(sessionStore: store);

    final flipped = await client.preferCloudIfLanUnreachable();
    expect(flipped, isTrue);
    final saved = await store.load();
    expect(saved.serverMode, 'cloud');
  });

  test('preferCloudIfLanUnreachable no-ops when already cloud', () async {
    final store = _MemorySessionStore();
    await store.save(
      const MobileSessionData(
        serverMode: 'cloud',
        fhdHost: '192.168.1.8:17500',
      ),
    );
    final client = MobileApiClient(sessionStore: store);

    final flipped = await client.preferCloudIfLanUnreachable();
    expect(flipped, isFalse);
    expect((await store.load()).serverMode, 'cloud');
  });

  test(
    'resolveSessionBaseUrl keeps configured base without LAN host',
    () async {
      final store = _MemorySessionStore();
      final client = MobileApiClient(
        config: const MobileApiConfig(baseUrl: 'http://127.0.0.1:9999/'),
        sessionStore: store,
      );
      expect(await client.resolveSessionBaseUrl(), 'http://127.0.0.1:9999/');
    },
  );

  test('resolveSessionBaseUrl uses LAN host when serverMode=lan', () async {
    final store = _MemorySessionStore();
    await store.save(
      const MobileSessionData(serverMode: 'lan', fhdHost: '192.168.1.8:17500'),
    );
    final client = MobileApiClient(
      config: const MobileApiConfig(baseUrl: 'http://127.0.0.1:9999/'),
      sessionStore: store,
    );
    expect(await client.resolveSessionBaseUrl(), 'http://192.168.1.8:17500/');
  });

  test('resolveSessionBaseUrl uses cloud enterprise after LAN flip', () async {
    final store = _MemorySessionStore();
    await store.save(
      const MobileSessionData(
        serverMode: 'cloud',
        fhdHost: '192.168.1.8:17500',
      ),
    );
    final client = MobileApiClient(
      config: const MobileApiConfig(baseUrl: 'http://127.0.0.1:9999/'),
      sessionStore: store,
    );
    final base = await client.resolveSessionBaseUrl();
    expect(base, contains('xiu-ci.com'));
  });

  test('probeLanHealth returns false for closed port', () async {
    final client = MobileApiClient(sessionStore: _MemorySessionStore());
    final ok = await client.probeLanHealth('127.0.0.1:1');
    expect(ok, isFalse);
  });
}
