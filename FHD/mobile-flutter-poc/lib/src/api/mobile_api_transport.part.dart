part of 'mobile_api.dart';

abstract class _ApiTransportBase extends _ApiSessionCoreBase {
  _ApiTransportBase({
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

  Future<MobileEnvelope<Map<String, Object?>>> mobileHealth() async {
    final json = await getJson(XcagiMobileEndpoints.health);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<Map<String, Object?>> rootHealth() {
    return getJson(XcagiMobileEndpoints.rootHealth);
  }

  /// Keep the mobile failover contract when an enterprise LAN is unavailable:
  /// when enterprise LAN host is blank/unreachable, flip session to cloud so
  /// subsequent API calls stop hammering a dead `192.168.x.x`.
  Future<bool> preferCloudIfLanUnreachable() async {
    final isEnterprise = MobileProductSkuConfig.isEnterprise(
      buildSku: MobileBuildConfig.productSku,
    );
    if (!isEnterprise) return false;
    final session = await loadSession();
    if (session.serverMode.trim().toLowerCase() == 'cloud') return false;
    final host = session.fhdHost.trim();
    if (host.isEmpty) {
      await _saveSession(session.copyWith(serverMode: 'cloud'));
      _lastLanProbeAt = null;
      _lastLanProbeOk = null;
      return true;
    }
    final now = DateTime.now();
    if (_lastLanProbeAt != null &&
        _lastLanProbeOk == true &&
        now.difference(_lastLanProbeAt!) < const Duration(seconds: 15)) {
      return false;
    }
    final reachable = await probeLanHealth(host);
    _lastLanProbeAt = now;
    _lastLanProbeOk = reachable;
    if (reachable) return false;
    await _saveSession(session.copyWith(serverMode: 'cloud'));
    _lastLanProbeAt = null;
    _lastLanProbeOk = null;
    return true;
  }

  /// Probe LAN host `/api/health` with a short timeout (pairing-style).
  Future<bool> probeLanHealth(String hostWithPort) async {
    final host = hostWithPort.trim();
    if (host.isEmpty) return false;
    final router = MobileServerRouter(
      fhdHost: host,
      mode: MobileServerMode.lan,
      isEnterprise: true,
    );
    final base = router.lanReachableBaseUrl();
    try {
      final request = await _httpClient
          .openUrl('GET', Uri.parse('${base}api/health'))
          .timeout(const Duration(milliseconds: 900));
      request.headers.set(HttpHeaders.acceptHeader, 'application/json');
      request.headers.set('X-XCAGI-Client', 'android');
      final response = await request.close().timeout(
            const Duration(milliseconds: 900),
          );
      await response.drain<void>();
      return response.statusCode >= 200 && response.statusCode < 300;
    } catch (_) {
      return false;
    }
  }

  MobileServerRouter serverRouterForSession(MobileSessionData session) {
    final mode = session.serverMode.trim().toLowerCase() == 'lan'
        ? MobileServerMode.lan
        : MobileServerMode.cloud;
    final host = session.fhdHost.trim();
    return MobileServerRouter(
      fhdHost: host.isEmpty ? '127.0.0.1' : host,
      mode: mode,
      isEnterprise: MobileProductSkuConfig.isEnterprise(
        buildSku: MobileBuildConfig.productSku,
      ),
    );
  }

  Future<String> resolveSessionBaseUrl() async {
    final session = await loadSession();
    final mode = session.serverMode.trim().toLowerCase();
    final host = session.fhdHost.trim();
    final configBase = _config.baseUrl.trim();
    final normalizedConfig =
        configBase.endsWith('/') ? configBase : '$configBase/';

    if (mode == 'lan') {
      final local = session.localBaseUrl.trim();
      if (local.isNotEmpty) {
        return local.endsWith('/') ? local : '$local/';
      }
      if (host.isNotEmpty) {
        return serverRouterForSession(session).fhdBaseUrl();
      }
    }

    // After LAN→cloud flip we still keep fhdHost; route to enterprise cloud base.
    if (mode == 'cloud' && host.isNotEmpty) {
      return serverRouterForSession(session).fhdBaseUrl();
    }

    // Tests / explicit XCAGI_MOBILE_BASE_URL keep configured base.
    return normalizedConfig;
  }


  /// Keep the saved login when the access JWT expires but refresh_token is
  /// still valid.
  Future<bool> _refreshFhdAccessToken() async {
    if (_refreshInFlight != null) {
      return _refreshInFlight!;
    }
    final future = _refreshFhdAccessTokenImpl();
    _refreshInFlight = future;
    try {
      return await future;
    } finally {
      if (identical(_refreshInFlight, future)) {
        _refreshInFlight = null;
      }
    }
  }

  Future<bool> _refreshFhdAccessTokenImpl() async {
    final session = await loadSession();
    final refresh = session.refreshToken.trim();
    if (refresh.isEmpty) return false;
    try {
      final json = await _sendJsonRequest(
        method: 'POST',
        path: XcagiMobileEndpoints.authRefresh,
        body: {'refresh_token': refresh},
        allowAuthRefresh: false,
      );
      final envelope = MobileEnvelope.fromJson(json, _asObjectMap);
      if (!envelope.success) return false;
      final data = envelope.data;
      if (data == null || data.isEmpty) return false;
      final access = _readString(data, const ['access_token']);
      if (access.isEmpty) return false;
      final current = await _sessionStore.load().catchError(
            (_) => MobileSessionData.empty,
          );
      await _saveSession(
        current.copyWith(
          accessToken: access,
          refreshToken: _firstNonBlank([
            _readString(data, const ['refresh_token']),
            current.refreshToken,
          ]),
          sessionId: _firstNonBlank([
            _readString(data, const ['session_id']),
            current.sessionId,
          ]),
        ),
      );
      return true;
    } on MobileApiException catch (error) {
      if (error.statusCode == 401) {
        await clearActiveAuth();
      }
      return false;
    } catch (_) {
      return false;
    }
  }

  Future<Map<String, Object?>> _sendJsonRequest({
    required String method,
    required String path,
    Map<String, String> query = const {},
    Map<String, Object?>? body,
    String? baseUrl,
    String? authToken,
    bool allowAuthRefresh = true,
  }) async {
    Future<Map<String, Object?>> perform() async {
      var effectiveBase = baseUrl;
      if (effectiveBase == null || effectiveBase.trim().isEmpty) {
        // Skip LAN→cloud flip for the health probe itself to avoid recursion.
        final isHealthProbe = path == XcagiMobileEndpoints.rootHealth ||
            path == XcagiMobileEndpoints.health;
        if (!isHealthProbe) {
          await preferCloudIfLanUnreachable();
        }
        effectiveBase = await resolveSessionBaseUrl();
      }
      final request = await _open(
        method,
        path,
        query: query,
        baseUrl: effectiveBase,
        authToken: authToken,
      );
      if (body != null) {
        final bytes = utf8.encode(jsonEncode(body));
        request.contentLength = bytes.length;
        request.add(bytes);
      }
      return _readJsonResponse(request);
    }

    try {
      return await perform();
    } on MobileApiException catch (error) {
      if (!allowAuthRefresh ||
          error.statusCode != 401 ||
          MobileAuthHeaderPolicy.isPublicAuthWriteRequest(path)) {
        rethrow;
      }
      final refreshed = await _refreshFhdAccessToken();
      if (!refreshed) rethrow;
      return perform();
    }
  }

  Future<Map<String, Object?>> getJson(
    String path, {
    Map<String, String> query = const {},
  }) async {
    return _sendJsonRequest(method: 'GET', path: path, query: query);
  }

  Future<Map<String, Object?>> postJson(
    String path,
    Map<String, Object?> body, {
    Map<String, String> query = const {},
    String? baseUrl,
  }) async {
    return _sendJsonRequest(
      method: 'POST',
      path: path,
      query: query,
      body: body,
      baseUrl: baseUrl,
    );
  }

  Future<Map<String, Object?>> postModstoreJson(
    String path,
    Map<String, Object?> body, {
    Map<String, String> query = const {},
  }) async {
    return _sendJsonRequest(
      method: 'POST',
      path: path,
      query: query,
      body: body,
      baseUrl: _config.modstoreBaseUrl,
      authToken: _config.marketAccessToken,
      allowAuthRefresh: false,
    );
  }

  Future<Map<String, Object?>> getModstoreJson(
    String path, {
    Map<String, String> query = const {},
  }) async {
    return _sendJsonRequest(
      method: 'GET',
      path: path,
      query: query,
      baseUrl: _config.modstoreBaseUrl,
      authToken: _config.marketAccessToken,
      allowAuthRefresh: false,
    );
  }

  Future<Map<String, Object?>> putJson(
    String path,
    Map<String, Object?> body, {
    Map<String, String> query = const {},
  }) async {
    return _sendJsonRequest(
      method: 'PUT',
      path: path,
      query: query,
      body: body,
    );
  }

  Future<Map<String, Object?>> deleteJson(
    String path, {
    Map<String, String> query = const {},
  }) async {
    return _sendJsonRequest(method: 'DELETE', path: path, query: query);
  }

  Future<HttpClientRequest> _open(
    String method,
    String path, {
    Map<String, String> query = const {},
    String? baseUrl,
    String? authToken,
  }) async {
    final uri = _buildUri(path, query, baseUrl: baseUrl);
    final request =
        await _httpClient.openUrl(method, uri).timeout(_config.timeout);
    request.headers.set(HttpHeaders.acceptHeader, 'application/json');
    request.headers.set(HttpHeaders.contentTypeHeader, 'application/json');
    request.headers.set('X-XCAGI-Client', 'android');
    request.headers.set('X-XCAGI-SKU', MobileBuildConfig.productSku);

    final session = await loadSession();
    final explicitAuthorization = authToken?.trim() ?? '';
    if (explicitAuthorization.isNotEmpty) {
      request.headers.set(
        HttpHeaders.authorizationHeader,
        'Bearer $explicitAuthorization',
      );
    } else {
      final selectedBearer = _requestToken(session: session, url: uri);
      if (MobileAuthHeaderPolicy.shouldAttachSelectedBearer(
        isPublicAuthWriteRequest:
            MobileAuthHeaderPolicy.isPublicAuthWriteRequest(uri.toString()),
        callerAuthorization:
            request.headers.value(HttpHeaders.authorizationHeader) ?? '',
        selectedBearer: selectedBearer,
      )) {
        request.headers.set(
          HttpHeaders.authorizationHeader,
          'Bearer $selectedBearer',
        );
      }
    }
    final sessionId = _firstNonBlank([_config.sessionId, session.sessionId]);
    if (sessionId.isNotEmpty) {
      request.headers.set('X-Session-ID', sessionId);
      request.headers.set(HttpHeaders.cookieHeader, 'session_id=$sessionId');
    }
    return request;
  }

  Uri _buildUri(String path, Map<String, String> query, {String? baseUrl}) {
    final normalizedPath = path.startsWith('/') ? path.substring(1) : path;
    final rawBase = baseUrl ?? _config.baseUrl;
    final base = Uri.parse(rawBase.endsWith('/') ? rawBase : '$rawBase/');
    final uri = base.resolve(normalizedPath);
    if (query.isEmpty) return uri;
    return uri.replace(queryParameters: {...uri.queryParameters, ...query});
  }

  Map<String, Object?> _withLocalAvatar(
    Map<String, Object?> json,
    String avatarSource,
  ) {
    final avatar = avatarSource.trim();
    if (avatar.isEmpty) return json;

    final data = _asObjectMap(json['data']);
    if (data.isEmpty) return json;
    final user = _asObjectMap(data['user']);
    if (user.isEmpty) return json;
    final existing =
        (user['avatar_url'] ?? user['avatar'] ?? '').toString().trim();
    if (existing.isNotEmpty) return json;

    return {
      ...json,
      'data': {
        ...data,
        'user': {...user, 'avatar_url': avatar},
      },
    };
  }

  String _requestToken({required MobileSessionData session, required Uri url}) {
    return MobileAuthHeaderPolicy.selectBearer(
      url: url.toString(),
      fhdToken: _firstNonBlank([_config.accessToken, session.accessToken]),
      marketToken: _firstNonBlank([
        _config.marketAccessToken,
        session.marketAccessToken,
      ]),
      modstoreBaseUrl: _config.modstoreBaseUrl,
      enterpriseFhdBaseUrl: XcagiMobileTopology.fhdApiBaseUrl,
    );
  }

  Future<Map<String, Object?>> _readJsonResponse(
    HttpClientRequest request,
  ) async {
    final response = await request.close().timeout(_config.timeout);
    final text = await utf8.decodeStream(response).timeout(_config.timeout);
    final status = response.statusCode;
    Object? decoded;

    if (text.trim().isNotEmpty) {
      decoded = jsonDecode(text);
    }
    final body = _asObjectMap(decoded);
    if (status < 200 || status >= 300) {
      throw MobileApiException(
        statusCode: status,
        message: body['message']?.toString() ??
            body['error']?.toString() ??
            'HTTP $status',
        body: body,
      );
    }
    return body;
  }
}
