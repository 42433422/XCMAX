import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:pub_semver/pub_semver.dart';

import '../platform/credential_cipher.dart';
import '../security/relay_e2ee.dart';
import '../data/service_topology_ssot.dart';
import '../policy/mobile_runtime_policy.dart';
import 'mobile_models.dart';
import 'mobile_session_store.dart';
import 'encrypted_session_store.dart';

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
    super.config,
    super.sessionStore,
    super.httpClient,
    super.credentialCipher,
  });
}

abstract class _ApiRootBase {
  _ApiRootBase({
    MobileApiConfig config = const MobileApiConfig(),
    MobileSessionStore? sessionStore,
    HttpClient? httpClient,
    PlatformCredentialCipher? credentialCipher,
  })  : _ownsHttpClient = httpClient == null,
        _config = config,
        _httpClient = httpClient ?? HttpClient(),
        _credentialCipher =
            credentialCipher ?? const PlatformCredentialCipher() {
    _sessionStore = sessionStore ??
        EncryptedMobileSessionStore(
          FileMobileSessionStore(),
          cipher: _credentialCipher,
        );
  }

  final bool _ownsHttpClient;
  bool _disposed = false;

  void dispose() {
    if (_disposed) return;
    _disposed = true;
    if (_ownsHttpClient) _httpClient.close(force: true);
    unawaited(_sessionChanges.close());
  }

  final MobileApiConfig _config;
  late final MobileSessionStore _sessionStore;
  final HttpClient _httpClient;
  final PlatformCredentialCipher _credentialCipher;
  final StreamController<MobileSessionData> _sessionChanges =
      StreamController<MobileSessionData>.broadcast();
  MobileSessionData _lastSession = MobileSessionData.empty;
  int _authGeneration = 0;
  Future<void> _sessionWrites = Future<void>.value();
  Future<bool>? _refreshInFlight;
  DateTime? _authRefreshBlockedUntil;
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
