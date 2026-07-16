import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

class ImWsMessageEvent {
  const ImWsMessageEvent({
    required this.conversationId,
    required this.messageId,
    required this.senderUserId,
    required this.body,
    required this.createdAtMs,
  });

  final int conversationId;
  final int messageId;
  final int senderUserId;
  final String body;
  final int createdAtMs;
}

class ImWebSocketClient {
  ImWebSocketClient();

  final _events = StreamController<Map<String, Object?>>.broadcast();
  WebSocketChannel? _channel;
  StreamSubscription<Object?>? _subscription;
  Timer? _heartbeatTimer;
  Timer? _reconnectTimer;
  String _sessionId = '';
  String _url = '';
  var _connected = false;
  var _reconnectAttempts = 0;
  var _disposed = false;

  Stream<Map<String, Object?>> get events => _events.stream;
  bool get connected => _connected;

  void connect({required String sessionId, required String url}) {
    if (sessionId.trim().isEmpty || url.trim().isEmpty) return;
    _sessionId = sessionId.trim();
    _url = url.trim();
    _reconnectAttempts = 0;
    _disconnectSocket();
    _cancelReconnect();
    _openSocket();
  }

  void disconnect() {
    _sessionId = '';
    _url = '';
    _cancelReconnect();
    _disconnectSocket();
  }

  void dispose() {
    _disposed = true;
    disconnect();
    _events.close();
  }

  void _openSocket() {
    if (_disposed || _sessionId.isEmpty || _url.isEmpty) return;
    try {
      _channel = WebSocketChannel.connect(Uri.parse(_url));
      _subscription = _channel!.stream.listen(
        _onData,
        onDone: _onDone,
        onError: _onError,
        cancelOnError: true,
      );
      _connected = true;
      _reconnectAttempts = 0;
      _startHeartbeat();
    } catch (_) {
      _connected = false;
      _scheduleReconnect();
    }
  }

  void _onData(Object? data) {
    if (data is! String || data.trim().isEmpty) return;
    try {
      final decoded = jsonDecode(data);
      if (decoded is Map) {
        final event = decoded.map(
          (key, value) => MapEntry(key.toString(), value),
        );
        if (!_events.isClosed) {
          _events.add(Map<String, Object?>.from(event));
        }
      }
    } catch (_) {
      // ignore malformed frames
    }
  }

  void _onDone() {
    _connected = false;
    _stopHeartbeat();
    _scheduleReconnect();
  }

  void _onError(Object _) {
    _connected = false;
    _stopHeartbeat();
    _scheduleReconnect();
  }

  void _startHeartbeat() {
    _stopHeartbeat();
    _heartbeatTimer = Timer.periodic(const Duration(seconds: 30), (_) {
      if (!_connected) return;
      try {
        _channel?.sink.add(jsonEncode(const {'type': 'ping'}));
      } catch (error) {
        _onError(error);
      }
    });
  }

  void _stopHeartbeat() {
    _heartbeatTimer?.cancel();
    _heartbeatTimer = null;
  }

  void _scheduleReconnect() {
    if (_disposed || _sessionId.isEmpty) return;
    _cancelReconnect();
    final delayMs = _reconnectDelayMs(_reconnectAttempts);
    _reconnectAttempts += 1;
    _reconnectTimer = Timer(Duration(milliseconds: delayMs), () {
      if (_disposed || _sessionId.isEmpty) return;
      _disconnectSocket();
      _openSocket();
    });
  }

  int _reconnectDelayMs(int attempt) {
    const base = 5000;
    const cap = 300000;
    final scaled = base * (1 << attempt.clamp(0, 6));
    return scaled > cap ? cap : scaled;
  }

  void _cancelReconnect() {
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
  }

  void _disconnectSocket() {
    _stopHeartbeat();
    _subscription?.cancel();
    _subscription = null;
    try {
      _channel?.sink.close();
    } catch (_) {
      // ignore close errors
    }
    _channel = null;
    _connected = false;
  }

  static ImWsMessageEvent? parseMessageEvent(Map<String, Object?> json) {
    final type = (json['type'] ?? '').toString();
    if (type != 'im.message' && type != 'message') return null;
    final conversationId = _int(json['conversation_id']);
    final message = json['message'];
    final messageMap = message is Map
        ? message.map((key, value) => MapEntry(key.toString(), value))
        : const <String, Object?>{};
    final messageId = messageMap.isNotEmpty
        ? _int(messageMap['id'])
        : _int(json['message_id']);
    if (conversationId <= 0 || messageId <= 0) return null;
    final senderUserId = messageMap.isNotEmpty
        ? _int(messageMap['sender_user_id'])
        : _int(json['sender_user_id']);
    final body = messageMap.isNotEmpty
        ? _string(messageMap['body'])
        : _string(json['body']);
    return ImWsMessageEvent(
      conversationId: conversationId,
      messageId: messageId,
      senderUserId: senderUserId,
      body: body,
      createdAtMs: DateTime.now().millisecondsSinceEpoch,
    );
  }
}

int _int(Object? value) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  return int.tryParse('$value') ?? 0;
}

String _string(Object? value) => value?.toString() ?? '';
