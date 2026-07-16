import 'dart:io' show Platform;

import 'package:flutter/services.dart';

class AndroidCameraPermission {
  const AndroidCameraPermission({
    MethodChannel channel = const MethodChannel('xcagi/permissions'),
  }) : _channel = channel;

  final MethodChannel _channel;

  Future<bool> isGranted() async {
    if (!Platform.isAndroid) return true;
    try {
      final granted = await _channel.invokeMethod<bool>('checkCamera');
      return granted ?? false;
    } on MissingPluginException {
      return true;
    } on PlatformException {
      return false;
    }
  }

  Future<bool> ensureGranted() async {
    if (!Platform.isAndroid) return true;
    try {
      final granted = await _channel.invokeMethod<bool>('ensureCamera');
      return granted ?? false;
    } on MissingPluginException {
      return true;
    } on PlatformException {
      return false;
    }
  }
}
