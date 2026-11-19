import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';

@visibleForTesting
String? debugSpeechOperatingSystemOverride;

String? get unsupportedSpeechRecognitionMessage {
  var operatingSystem = Platform.operatingSystem;
  assert(() {
    operatingSystem = debugSpeechOperatingSystemOverride ?? operatingSystem;
    return true;
  }());
  // The locked speech_to_text 7.4.0 has no HarmonyOS recognition adapter.
  return operatingSystem == 'ohos' ? '当前鸿蒙版暂不支持语音识别，请使用文字输入' : null;
}

const speechRecognitionUnavailableMessage = '语音识别暂时不可用，请检查麦克风和语音识别权限，或使用文字输入';
