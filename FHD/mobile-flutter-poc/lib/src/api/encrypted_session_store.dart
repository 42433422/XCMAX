import '../platform/credential_cipher.dart';
import 'mobile_session_store.dart';

/// 会话落盘加密装饰器。
///
/// 凭证字段（access/refresh/market/relay/fcm）在写入前统一经平台密钥库加密，
/// 读取时解密；`savedPassword` 已由 [MobileApiClient] 单独加密，避免二次加密。
class EncryptedMobileSessionStore implements MobileSessionStore {
  EncryptedMobileSessionStore(
    this._inner, {
    PlatformCredentialCipher? cipher,
  }) : _cipher = cipher ?? const PlatformCredentialCipher();

  static const encryptedPrefix = 'enc:v1:';

  final MobileSessionStore _inner;
  final PlatformCredentialCipher _cipher;

  @override
  Future<MobileSessionData> load() async {
    final data = await _inner.load();
    return data.copyWith(
      accessToken: await _decrypt(data.accessToken),
      refreshToken: await _decrypt(data.refreshToken),
      marketAccessToken: await _decrypt(data.marketAccessToken),
      marketRefreshToken: await _decrypt(data.marketRefreshToken),
      relaySessionToken: await _decrypt(data.relaySessionToken),
      fcmToken: await _decrypt(data.fcmToken),
    );
  }

  @override
  Future<void> save(MobileSessionData data) async {
    await _inner.save(
      data.copyWith(
        accessToken: await _encrypt(data.accessToken),
        refreshToken: await _encrypt(data.refreshToken),
        marketAccessToken: await _encrypt(data.marketAccessToken),
        marketRefreshToken: await _encrypt(data.marketRefreshToken),
        relaySessionToken: await _encrypt(data.relaySessionToken),
        fcmToken: await _encrypt(data.fcmToken),
      ),
    );
  }

  @override
  Future<void> clear() => _inner.clear();

  Future<String> _encrypt(String plain) async {
    if (plain.isEmpty || plain.startsWith(encryptedPrefix)) return plain;
    final encrypted = await _cipher.encrypt(plain);
    // 密钥库不可用时宁可不落盘，也不把凭证写成明文。
    return encrypted.startsWith(encryptedPrefix) ? encrypted : '';
  }

  Future<String> _decrypt(String stored) async {
    if (!stored.startsWith(encryptedPrefix)) return stored;
    // 解密失败按「无凭证」处理，避免把密文当作令牌继续使用。
    return _cipher.decrypt(stored);
  }
}
