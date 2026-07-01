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
    return value ?? plain;
  }

  Future<String> decrypt(String stored) async {
    if (stored.isEmpty) return '';
    final value = await _channel.invokeMethod<String>('decrypt', {
      'stored': stored,
    });
    return value ?? '';
  }
}
