import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'package:cryptography/cryptography.dart';

import '../api/mobile_api.dart';
import '../api/mobile_models.dart';
import '../models/conversation.dart';
import '../policy/mobile_runtime_policy.dart';
import '../policy/avatar_policy.dart';
import '../policy/pinned_ids.dart';
import 'ai_employee_profile.dart';
import 'duty_roster_ssot.dart';
import 'employee_pending_question.dart';
import 'offline/mobile_offline_store.dart';
import '../im/im_websocket_client.dart';

part 'mobile_repository_session.part.dart';
part 'mobile_repository_groups.part.dart';
part 'mobile_repository_pairing_auth.part.dart';
part 'mobile_repository_chat_helpers.part.dart';
part 'mobile_repository_git_relay.part.dart';
part 'mobile_repository_chat.part.dart';
part 'mobile_repository_services.part.dart';
part 'mobile_repository_business.part.dart';
part 'mobile_repository_relay_helpers.part.dart';
part 'mobile_repository_models.part.dart';
part 'mobile_repository_helpers_parsing.part.dart';
part 'mobile_repository_helpers_format.part.dart';
part 'mobile_repository_conversation_state.part.dart';
part 'mobile_repository_extensions.part.dart';

class MobileRepository extends _RepoBusinessBase {
  MobileRepository({super.client, super.imWebSocket});

  static const customerServiceRequestType = 'mobile_ai_customer_service';
}

abstract class _RepoRootBase {
  _RepoRootBase({MobileApiClient? client, ImWebSocketClient? imWebSocket})
      : _ownsClient = client == null,
        _ownsImWebSocket = imWebSocket == null,
        _client = client ?? MobileApiClient(),
        _imWebSocket = imWebSocket ?? ImWebSocketClient() {
    _imAuthFailureSubscription = _imWebSocket.authFailures.listen((_) {
      unawaited(_client.clearActiveAuth().catchError((_) {}));
    });
  }

  final MobileApiClient _client;
  final ImWebSocketClient _imWebSocket;
  final bool _ownsClient;
  final bool _ownsImWebSocket;
  bool _disposed = false;
  StreamSubscription<void>? _imAuthFailureSubscription;

  Future<void> dispose() async {
    if (_disposed) return;
    _disposed = true;
    await _imAuthFailureSubscription?.cancel();
    _imAuthFailureSubscription = null;
    if (_ownsImWebSocket) _imWebSocket.dispose();
    if (_ownsClient) _client.dispose();
  }

  MobileApiClient get client => _client;
  bool get imWebSocketConnected => _imWebSocket.connected;

  // A scoped cache survives token refresh for an identified account, while
  // anonymous/legacy sessions use a credential fingerprint instead.
  Future<String> _offlineScope() async {
    final generation = _client.authGeneration;
    final session = await _client.loadSession();
    final base = await _client.resolveSessionBaseUrl();
    final identity = jsonEncode([
      base,
      session.userId,
      session.accountKind,
      session.relayTenantId,
      if (session.userId <= 0) ...[
        session.username,
        session.accessToken,
        session.sessionId,
        session.marketAccessToken,
      ],
    ]);
    final digest = await Sha256().hash(utf8.encode(identity));
    if (generation != _client.authGeneration) return '';
    return '$generation:${digest.bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join()}';
  }

  Future<MobileOfflineStore?> openOfflineStore({String? expectedScope}) async {
    try {
      final scope = expectedScope ?? await _offlineScope();
      if (scope.isEmpty || scope != await _offlineScope()) return null;
      final store =
          await MobileOfflineStore.open(namespace: scope.split(':').last);
      return scope == await _offlineScope() ? store : null;
    } catch (_) {
      return null;
    }
  }

  Stream<Map<String, Object?>> get imWebSocketEvents => _imWebSocket.events;
  ImWsConnectionState get imWebSocketState => _imWebSocket.state;
  Stream<ImWsConnectionState> get imWebSocketStates => _imWebSocket.states;

  /// See [MobileApiClient.preferCloudIfLanUnreachable].
  Future<bool> preferCloudIfLanUnreachable() =>
      _client.preferCloudIfLanUnreachable();
}
