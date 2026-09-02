import 'dart:async';
import 'dart:convert';
import 'dart:io';

import '../platform/credential_cipher.dart';
import '../data/service_topology_ssot.dart';
import '../policy/mobile_runtime_policy.dart';
import 'mobile_models.dart';
import 'mobile_session_store.dart';

export '../data/service_topology_ssot.dart';

part 'mobile_api_endpoints.part.dart';
part 'mobile_api_config.part.dart';
part 'mobile_api_session_core.part.dart';
part 'mobile_api_transport.part.dart';
part 'mobile_api_session_persist.part.dart';
part 'mobile_api_nav.part.dart';
part 'mobile_api_groups.part.dart';
part 'mobile_api_cs_auth.part.dart';
part 'mobile_api_pairing.part.dart';
part 'mobile_api_work.part.dart';
part 'mobile_api_chat.part.dart';
part 'mobile_api_misc.part.dart';

class MobileApiClient extends _ApiChatBase {
  MobileApiClient({
    MobileApiConfig config = const MobileApiConfig(),
    MobileSessionStore? sessionStore,
    HttpClient? httpClient,
    PlatformCredentialCipher? credentialCipher,
  }) : super(
          config: config,
          sessionStore: sessionStore,
          httpClient: httpClient,
          credentialCipher: credentialCipher,
        );
}

abstract class _ApiRootBase {
  _ApiRootBase({
    MobileApiConfig config = const MobileApiConfig(),
    MobileSessionStore? sessionStore,
    HttpClient? httpClient,
    PlatformCredentialCipher? credentialCipher,
  })  : _config = config,
        _sessionStore = sessionStore ?? FileMobileSessionStore(),
        _httpClient = httpClient ?? HttpClient(),
        _credentialCipher =
            credentialCipher ?? const PlatformCredentialCipher();

  final MobileApiConfig _config;
  final MobileSessionStore _sessionStore;
  final HttpClient _httpClient;
  final PlatformCredentialCipher _credentialCipher;
  final StreamController<MobileSessionData> _sessionChanges =
      StreamController<MobileSessionData>.broadcast();
  MobileSessionData _lastSession = MobileSessionData.empty;
  Future<bool>? _refreshInFlight;
  DateTime? _lastLanProbeAt;
  bool? _lastLanProbeOk;

  String get configuredRelayId => _config.relayId.trim();
  String get localAvatarSource => _config.localAvatarSource.trim();
  MobileSessionStore get sessionStore => _sessionStore;
  Stream<MobileSessionData> get sessionChanges async* {
    yield _lastSession;
    yield* _sessionChanges.stream;
  }
}
