import 'package:flutter/scheduler.dart';

/// Groups synchronous SSE token bursts into one delivery per Flutter frame.
/// Tokens never cross message identities; final receipts are authoritative.
class ChatStreamFrameBatcher {
  ChatStreamFrameBatcher(this.onBatch);

  final void Function(String messageId, String text) onBatch;
  String? _messageId;
  StringBuffer _pending = StringBuffer();
  int? _callbackId;

  void append(String messageId, String token) {
    if (messageId.isEmpty || token.isEmpty) return;
    if (_messageId != null && _messageId != messageId) clear();
    _messageId = messageId;
    _pending.write(token);
    _callbackId ??= SchedulerBinding.instance.scheduleFrameCallback((_) {
      _callbackId = null;
      flush();
    });
  }

  /// Preserve already received text when the user explicitly stops the stream.
  void flushFor(String messageId) {
    if (_messageId == messageId) flush();
  }

  void flush() {
    _cancelCallback();
    final messageId = _messageId;
    final text = _pending.toString();
    _messageId = null;
    _pending = StringBuffer();
    if (messageId != null && text.isNotEmpty) onBatch(messageId, text);
  }

  void clearFor(String messageId) {
    if (_messageId == messageId) clear();
  }

  void clear() {
    _cancelCallback();
    _messageId = null;
    _pending = StringBuffer();
  }

  void _cancelCallback() {
    final id = _callbackId;
    _callbackId = null;
    if (id != null) SchedulerBinding.instance.cancelFrameCallbackWithId(id);
  }

  void dispose() => clear();
}
