import 'package:flutter/services.dart';

class AssistantPickedFile {
  const AssistantPickedFile({
    required this.name,
    required this.mimeType,
    required this.bytes,
  });

  final String name;
  final String mimeType;
  final Uint8List bytes;

  int get size => bytes.length;
}

class AssistantNativeBridge {
  const AssistantNativeBridge();

  static const _channel = MethodChannel('xcagi/assistant_native');

  Future<AssistantPickedFile?> pickFile() async {
    final raw = await _channel.invokeMapMethod<String, Object?>('pickFile');
    if (raw == null) return null;
    final name = raw['name']?.toString().trim() ?? '';
    final mime = raw['mimeType']?.toString().trim() ?? '';
    final bytes = raw['bytes'];
    if (name.isEmpty || bytes is! Uint8List || bytes.isEmpty) return null;
    return AssistantPickedFile(
      name: name,
      mimeType: mime.isEmpty ? 'application/octet-stream' : mime,
      bytes: bytes,
    );
  }

  Future<void> playBase64Audio(String audioBase64) async {
    await _channel.invokeMethod<void>('playBase64Audio', {
      'audioBase64': audioBase64,
    });
  }

  Future<void> speakText(String text) async {
    await _channel.invokeMethod<void>('speakText', {'text': text});
  }

  Future<String> recognizeSpeech() async {
    final text = await _channel.invokeMethod<String>('recognizeSpeech');
    return text?.trim() ?? '';
  }

  Future<void> stopSpeech() => _channel.invokeMethod<void>('stopSpeech');
}
