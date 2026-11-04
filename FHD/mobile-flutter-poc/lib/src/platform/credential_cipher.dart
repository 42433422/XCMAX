import 'package:flutter/services.dart';

class PlatformCredentialCipher {
  const PlatformCredentialCipher({
    MethodChannel channel = const MethodChannel('xcagi/credential_cipher'),
  }) : _channel = channel;

  final MethodChannel _channel;

  Future<String> encrypt(String plain) async {
    if (plain.isEmpty) return '';
    final value = await _channel.invokeMethod<String>('encrypt', {
      'plain': plain,
    });
    if (value == null ||
        !value.startsWith('enc:v1:') ||
        value.length <= 'enc:v1:'.length ||
        value == plain) {
      throw StateError('当前设备无法安全保存密码');
    }
    return value;
  }

  Future<String> decrypt(String stored) async {
    if (stored.isEmpty) return '';
    final value = await _channel.invokeMethod<String>('decrypt', {
      'stored': stored,
    });
    return value ?? '';
  }
}
