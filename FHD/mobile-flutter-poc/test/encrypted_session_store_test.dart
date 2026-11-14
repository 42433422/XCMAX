import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/encrypted_session_store.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/platform/credential_cipher.dart';

class _FakeCredentialCipher implements PlatformCredentialCipher {
  @override
  Future<String> encrypt(String plain) async =>
      plain.isEmpty ? '' : '${EncryptedMobileSessionStore.encryptedPrefix}$plain';

  @override
  Future<String> decrypt(String stored) async => stored.startsWith(
        EncryptedMobileSessionStore.encryptedPrefix,
      )
          ? stored.substring(EncryptedMobileSessionStore.encryptedPrefix.length)
          : '';
}

class _UnavailableCredentialCipher implements PlatformCredentialCipher {
  @override
  Future<String> encrypt(String plain) async => plain;

  @override
  Future<String> decrypt(String stored) async => '';
}

void main() {
  late MemoryMobileSessionStore inner;
  late EncryptedMobileSessionStore store;

  setUp(() {
    inner = MemoryMobileSessionStore();
    store = EncryptedMobileSessionStore(inner, cipher: _FakeCredentialCipher());
  });

  test('加密凭证字段后落盘，读取时还原', () async {
    const data = MobileSessionData(
      accessToken: 'access-1',
      refreshToken: 'refresh-1',
      marketAccessToken: 'market-1',
      marketRefreshToken: 'market-refresh-1',
      relaySessionToken: 'relay-1',
      fcmToken: 'fcm-1',
      username: 'alice',
      userId: 7,
    );

    await store.save(data);
    final persisted = await inner.load();

    expect(persisted.accessToken, startsWith('enc:v1:'));
    expect(persisted.refreshToken, startsWith('enc:v1:'));
    expect(persisted.marketAccessToken, startsWith('enc:v1:'));
    expect(persisted.marketRefreshToken, startsWith('enc:v1:'));
    expect(persisted.relaySessionToken, startsWith('enc:v1:'));
    expect(persisted.fcmToken, startsWith('enc:v1:'));
    expect(persisted.username, 'alice');
    expect(persisted.userId, 7);

    final loaded = await store.load();
    expect(loaded.accessToken, 'access-1');
    expect(loaded.refreshToken, 'refresh-1');
    expect(loaded.marketAccessToken, 'market-1');
    expect(loaded.marketRefreshToken, 'market-refresh-1');
    expect(loaded.relaySessionToken, 'relay-1');
    expect(loaded.fcmToken, 'fcm-1');
  });

  test('历史明文会话可继续读取，不会被二次加密', () async {
    const legacy = MobileSessionData(
      accessToken: 'legacy-access',
      refreshToken: 'legacy-refresh',
    );
    await inner.save(legacy);

    final loaded = await store.load();
    expect(loaded.accessToken, 'legacy-access');
    expect(loaded.refreshToken, 'legacy-refresh');
  });

  test('空字段保持为空，不会写入加密前缀', () async {
    await store.save(const MobileSessionData(username: 'bob'));
    final persisted = await inner.load();

    expect(persisted.accessToken, isEmpty);
    expect(persisted.fcmToken, isEmpty);
    expect(persisted.username, 'bob');
  });

  test('clear 透传到内层存储', () async {
    await store.save(const MobileSessionData(accessToken: 'a'));
    await store.clear();

    final loaded = await store.load();
    expect(loaded.accessToken, isEmpty);
  });

  test('密钥库不可用时凭证不落盘明文', () async {
    final unavailable = EncryptedMobileSessionStore(
      inner,
      cipher: _UnavailableCredentialCipher(),
    );

    await unavailable.save(
      const MobileSessionData(accessToken: 'plain-token', username: 'bob'),
    );
    final persisted = await inner.load();

    expect(persisted.accessToken, isEmpty);
    expect(persisted.username, 'bob');
  });

  test('解密失败按无凭证处理', () async {
    await inner.save(
      const MobileSessionData(accessToken: 'enc:v1:ciphertext'),
    );
    final unavailable = EncryptedMobileSessionStore(
      inner,
      cipher: _UnavailableCredentialCipher(),
    );

    final loaded = await unavailable.load();
    expect(loaded.accessToken, isEmpty);
  });
}
