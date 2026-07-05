import 'package:flutter/services.dart';

import '../api/mobile_session_store.dart';

class AndroidBackgroundWorkScheduler {
  const AndroidBackgroundWorkScheduler({
    MethodChannel channel = const MethodChannel('xcagi/background_work'),
  }) : _channel = channel;

  final MethodChannel _channel;

  Future<void> reconcile(MobileSessionData session) async {
    try {
      await _channel.invokeMethod<void>('reconcile', {
        'loggedIn': session.hasAuth,
        'autoSync': session.autoSync,
        'autoLanProbe': session.autoLanProbe,
      });
    } on MissingPluginException {
      return;
    }
  }
}
