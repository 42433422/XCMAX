import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 手机 ↔ 桌面端端到端加密。
///
/// 手机用桌面公钥加密任务内容，云端只看到密文；结果由桌面用同一次 ECDH
/// 共享密钥加密，手机用本地保存的一次性私钥解开。云端无法解密任何内容。
class RelayE2eeException implements Exception {
  const RelayE2eeException(this.message);

  final String message;

  @override
  String toString() => message;
}

class SealedRelayPayload {
  const SealedRelayPayload({
    required this.envelope,
    required this.reference,
    required this.ephemeralPrivateKey,
    required this.desktopPublicKey,
  });

  final Map<String, Object?> envelope;
  final String reference;
  final String ephemeralPrivateKey;
  final String desktopPublicKey;
}

class RelayE2ee {
  static final X25519 _x25519 = X25519();
  static final AesGcm _aes = AesGcm.with256bits();
  static final Hkdf _hkdf = Hkdf(hmac: Hmac.sha256(), outputLength: 32);
  static final Random _random = Random.secure();

  static const String alg = 'x25519-hkdf-sha256-aesgcm';
  static const int _macBytes = 16;
  static const int _nonceBytes = 12;

  static bool isEnvelope(Object? value) {
    if (value is! Map) return false;
    if (value['v'] != 1) return false;
    final algorithm = (value['alg'] ?? alg).toString();
    if (algorithm != alg) return false;
    return ['nonce', 'ct'].every(
      (field) => (value[field] ?? '').toString().isNotEmpty,
    );
  }

  static bool isE2eeError(Object? value) =>
      value is Map && value['e2ee_error'] == true;

  static Future<SealedRelayPayload> sealPayload(
    Map<String, Object?> payload,
    String desktopPublicKeyB64,
  ) async {
    final Uint8List desktopPublic;
    try {
      desktopPublic = base64.decode(desktopPublicKeyB64);
    } on FormatException {
      throw const RelayE2eeException('电脑端加密公钥格式无效，请重新配对');
    }
    final ephemeral = await _x25519.newKeyPair();
    final secret = await _x25519.sharedSecretKey(
      keyPair: ephemeral,
      remotePublicKey: SimplePublicKey(
        desktopPublic,
        type: KeyPairType.x25519,
      ),
    );
    final key = await _derive(secret, 'xcagi-relay-payload-v1');
    final nonce = _randomBytes(_nonceBytes);
    final box = await _aes.encrypt(
      utf8.encode(jsonEncode(payload)),
      secretKey: key,
      nonce: nonce,
    );
    final ephemeralPrivate = await ephemeral.extractPrivateKeyBytes();
    final ephemeralPublic = (await ephemeral.extractPublicKey()).bytes;
    final reference = _hex(_randomBytes(8));
    return SealedRelayPayload(
      reference: reference,
      ephemeralPrivateKey: base64.encode(ephemeralPrivate),
      desktopPublicKey: desktopPublicKeyB64,
      envelope: {
        'v': 1,
        'alg': alg,
        'ref': reference,
        'epk': base64.encode(ephemeralPublic),
        'nonce': base64.encode(nonce),
        'ct': base64.encode([...box.cipherText, ...box.mac.bytes]),
      },
    );
  }

  static Future<Map<String, Object?>> openResult(
    Map<String, Object?> envelope, {
    required String ephemeralPrivateKey,
    required String ephemeralPublicKey,
    required String desktopPublicKey,
  }) async {
    final Uint8List raw;
    final Uint8List nonce;
    final Uint8List privateBytes;
    final Uint8List publicBytes;
    final Uint8List desktopPublic;
    try {
      raw = base64.decode((envelope['ct'] ?? '').toString());
      nonce = base64.decode((envelope['nonce'] ?? '').toString());
      privateBytes = base64.decode(ephemeralPrivateKey);
      publicBytes = base64.decode(ephemeralPublicKey);
      desktopPublic = base64.decode(desktopPublicKey);
    } on FormatException {
      throw const RelayE2eeException('任务结果加密数据损坏，请稍后重试');
    }
    if (raw.length <= _macBytes) {
      throw const RelayE2eeException('任务结果加密数据损坏，请稍后重试');
    }
    final keyPair = SimpleKeyPairData(
      privateBytes,
      publicKey: SimplePublicKey(publicBytes, type: KeyPairType.x25519),
      type: KeyPairType.x25519,
    );
    final secret = await _x25519.sharedSecretKey(
      keyPair: keyPair,
      remotePublicKey: SimplePublicKey(
        desktopPublic,
        type: KeyPairType.x25519,
      ),
    );
    final key = await _derive(secret, 'xcagi-relay-result-v1');
    final clear = await _aes.decrypt(
      SecretBox(
        raw.sublist(0, raw.length - _macBytes),
        nonce: nonce,
        mac: Mac(raw.sublist(raw.length - _macBytes)),
      ),
      secretKey: key,
    );
    final decoded = jsonDecode(utf8.decode(clear));
    if (decoded is! Map) {
      throw const RelayE2eeException('任务结果格式不正确');
    }
    return Map<String, Object?>.from(decoded);
  }

  static Future<void> rememberTask(SealedRelayPayload sealed) async {
    final record = jsonEncode({
      'private': sealed.ephemeralPrivateKey,
      'public': (sealed.envelope['epk'] ?? '').toString(),
      'desktop': sealed.desktopPublicKey,
      'at': DateTime.now().millisecondsSinceEpoch,
    });
    _memory['task:${sealed.reference}'] = record;
    final prefs = await _prefs();
    await prefs?.setString('xcagi.relay.e2ee.task.${sealed.reference}', record);
    await _prune(prefs);
  }

  static Future<
      ({
        String privateKey,
        String publicKey,
        String desktopPublicKey,
      })?> taskKeys(
    String reference,
  ) async {
    if (reference.isEmpty) return null;
    final prefs = await _prefs();
    final raw = prefs?.getString('xcagi.relay.e2ee.task.$reference') ??
        _memory['task:$reference'];
    if (raw == null || raw.isEmpty) return null;
    try {
      final map = jsonDecode(raw);
      if (map is! Map) return null;
      return (
        privateKey: (map['private'] ?? '').toString(),
        publicKey: (map['public'] ?? '').toString(),
        desktopPublicKey: (map['desktop'] ?? '').toString(),
      );
    } on FormatException {
      return null;
    }
  }

  /// 首次配对时固定桌面公钥；后续云端换钥会被识别为异常。
  static Future<String?> pinnedDesktopKey(String relayId) async {
    if (relayId.trim().isEmpty) return null;
    final prefs = await _prefs();
    return prefs?.getString('xcagi.relay.e2ee.pin.${relayId.trim()}') ??
        _memory['pin:${relayId.trim()}'];
  }

  static Future<void> pinDesktopKey(String relayId, String publicKey) async {
    final clean = relayId.trim();
    if (clean.isEmpty || publicKey.isEmpty) return;
    final pinned = await pinnedDesktopKey(clean);
    if (pinned != null && pinned.isNotEmpty && pinned != publicKey) {
      throw const RelayE2eeException(
        '电脑端加密公钥已变化，可能存在中间人攻击。请在电脑和手机重新配对后再试。',
      );
    }
    _memory['pin:$clean'] = publicKey;
    final prefs = await _prefs();
    await prefs?.setString('xcagi.relay.e2ee.pin.$clean', publicKey);
  }

  static Future<SecretKey> _derive(SecretKey secret, String info) {
    return _hkdf.deriveKey(
      secretKey: secret,
      nonce: utf8.encode('xcagi-relay-v1'),
      info: utf8.encode(info),
    );
  }

  static Future<void> _prune(SharedPreferences? prefs) async {
    if (prefs == null) return;
    final cutoff = DateTime.now()
        .subtract(const Duration(hours: 24))
        .millisecondsSinceEpoch;
    for (final key in prefs.getKeys().toList(growable: false)) {
      if (!key.startsWith('xcagi.relay.e2ee.task.')) continue;
      final raw = prefs.getString(key);
      if (raw == null) continue;
      try {
        final map = jsonDecode(raw);
        final at = map is Map ? int.tryParse('${map['at']}') ?? 0 : 0;
        if (at > 0 && at < cutoff) await prefs.remove(key);
      } on FormatException {
        await prefs.remove(key);
      }
    }
  }

  static Future<SharedPreferences?> _prefs() async {
    try {
      return await SharedPreferences.getInstance();
    } catch (_) {
      // 测试环境没有平台插件时退回内存存储，不影响加解密本身。
      return null;
    }
  }

  static final Map<String, String> _memory = <String, String>{};

  static Uint8List _randomBytes(int length) {
    return Uint8List.fromList(
      List<int>.generate(length, (_) => _random.nextInt(256)),
    );
  }

  static String _hex(List<int> bytes) {
    final buffer = StringBuffer();
    for (final byte in bytes) {
      buffer.write(byte.toRadixString(16).padLeft(2, '0'));
    }
    return buffer.toString();
  }
}
