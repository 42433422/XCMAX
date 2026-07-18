import 'dart:io' show Platform;

import 'package:flutter/services.dart';

class AndroidRecordAudioPermission {
  const AndroidRecordAudioPermission({
    MethodChannel channel = const MethodChannel('xcagi/permissions'),
  }) : _channel = channel;

  final MethodChannel _channel;

  Future<bool> ensureGranted() async {
    if (!Platform.isAndroid) return true;
    try {
      final granted = await _channel.invokeMethod<bool>('ensureRecordAudio');
      return granted ?? false;
    } on MissingPluginException {
      return true;
    } on PlatformException {
      return false;
    }
  }
}
