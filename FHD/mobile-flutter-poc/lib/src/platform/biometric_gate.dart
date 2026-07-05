import 'package:flutter/services.dart';

class AndroidBiometricGate {
  const AndroidBiometricGate({
    MethodChannel channel = const MethodChannel('xcagi/biometric'),
  }) : _channel = channel;

  final MethodChannel _channel;

  Future<bool> canAuthenticate() async {
    final value = await _channel.invokeMethod<bool>('canAuthenticate');
    return value == true;
  }

  Future<bool> prompt() async {
    final value = await _channel.invokeMethod<bool>('authenticate');
    return value == true;
  }

  Future<void> finishApp() async {
    await _channel.invokeMethod<void>('finishApp');
  }
}
