import 'dart:async';
import 'dart:convert';
import 'dart:io';

import '../api/mobile_api.dart';
import '../api/mobile_models.dart';
import '../models/conversation.dart';
import '../policy/mobile_runtime_policy.dart';
import '../policy/avatar_policy.dart';
import '../policy/pinned_ids.dart';
import 'ai_employee_profile.dart';
import 'duty_roster_ssot.dart';
import 'employee_pending_question.dart';
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

const _badgeInstalledColor = 0xFF3370FF;
const _xcmaxDefaultWorkspaceRoot = '/Users/a4243342/Desktop/XCMAX';

class MobileRepository extends _RepoBusinessBase {
  MobileRepository({MobileApiClient? client, ImWebSocketClient? imWebSocket})
      : super(client: client, imWebSocket: imWebSocket);

  static const customerServiceRequestType = 'mobile_ai_customer_service';
}

abstract class _RepoRootBase {
  _RepoRootBase({MobileApiClient? client, ImWebSocketClient? imWebSocket})
      : _client = client ?? MobileApiClient(),
        _imWebSocket = imWebSocket ?? ImWebSocketClient();

  final MobileApiClient _client;
  final ImWebSocketClient _imWebSocket;
  StreamSubscription<Map<String, Object?>>? _imWebSocketSubscription;

  MobileApiClient get client => _client;
  bool get imWebSocketConnected => _imWebSocket.connected;
  Stream<Map<String, Object?>> get imWebSocketEvents => _imWebSocket.events;

  /// See [MobileApiClient.preferCloudIfLanUnreachable].
  Future<bool> preferCloudIfLanUnreachable() =>
      _client.preferCloudIfLanUnreachable();
}
