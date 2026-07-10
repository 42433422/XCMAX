import 'package:flutter/services.dart';

class AndroidCredentialCipher {
  const AndroidCredentialCipher({
    MethodChannel channel = const MethodChannel('xcagi/credential_cipher'),
  }) : _channel = channel;

  final MethodChannel _channel;

  Future<String> encrypt(String plain) async {
    if (plain.isEmpty) return '';
    final value = await _channel.invokeMethod<String>('encrypt', {
      'plain': plain,
    });
    final encrypted = value?.trim() ?? '';
    if (!encrypted.startsWith('enc:v1:') || encrypted == plain) {
      throw PlatformException(
        code: 'credential_encryption_unavailable',
        message: 'Android Keystore encryption is unavailable',
      );
    }
    return encrypted;
  }

  Future<String> decrypt(String stored) async {
    if (stored.isEmpty) return '';
    final value = await _channel.invokeMethod<String>('decrypt', {
      'stored': stored,
    });
    if (value == null || value.isEmpty) {
      throw PlatformException(
        code: 'credential_decryption_failed',
        message: 'Android Keystore decryption failed',
      );
    }
    return value;
  }
}
