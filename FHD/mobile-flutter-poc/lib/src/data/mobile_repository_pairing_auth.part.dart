part of 'mobile_repository.dart';

abstract class _RepoPairingAuthBase extends _RepoGroupsBase {
  _RepoPairingAuthBase({
    MobileApiClient? client,
    ImWebSocketClient? imWebSocket,
  }) : super(client: client, imWebSocket: imWebSocket);

  Future<void> exchangePairingCode(String raw) async {
    final text = raw.trim();
    if (text.isEmpty) {
      throw const MobileRepositoryException('无法识别配对码');
    }
    if (RegExp(r'^\d{6}$').hasMatch(text)) {
      await _bindRelay('', text);
      return;
    }
    final parsed = parsePairingPayload(text);
    if (parsed != null && parsed.version >= 3 && parsed.relayId.isNotEmpty) {
      await _bindRelay(parsed.relayId, parsed.code);
      return;
    }

    final code = parsed?.code.trim() ?? '';
    final nonce = _pairingExchangeNonce(parsed, text, code);
    if (code.isEmpty && nonce.isEmpty) {
      throw const MobileRepositoryException('无法识别配对码，请刷新电脑端二维码');
    }

    final baseUrl = await _resolvePairingExchangeBaseUrl(parsed, text);
    if (baseUrl.isEmpty) {
      throw const MobileRepositoryException(
        '未找到电脑，请确认手机与电脑在同一 WiFi，并在管理端刷新设备码后重试',
      );
    }

    await _primePairingLanSession(baseUrl);
    final response = await _client.exchangePairing(
      nonce: nonce,
      code: code,
      baseUrl: baseUrl,
    );
    if (!response.success) {
      throw MobileRepositoryException('设备配对失败[${response.message}]');
    }
    final hostWithPort = _hostPortFromApiBaseUrl(
      _readStringMap(response.data, const ['api_base_url', 'base_url']),
    ).ifEmpty(parsed?.hostWithPort ?? '');
    await _client.persistPairingSession(
      response.data,
      hostWithPort: hostWithPort,
      clearRelayDesktop: true,
      setupComplete: true,
      preserveActiveAuth: true,
    );
    final relayId = _relayIdFromBindingData(response.data);
    if (relayId.isNotEmpty) {
      await _bindRelay(relayId, '');
    }
  }

  Future<void> _bindRelay(String relayId, String code) async {
    final session = await _client.loadSession();
    if (session.accessToken.trim().isEmpty) {
      throw const MobileRepositoryException('请先登录账号，再绑定电脑端设备');
    }
    final binding = await _client.relayBindAccount(
      relayId,
      pairingCode: code,
    );
    if (!binding.success) {
      throw MobileRepositoryException('设备配对失败[${binding.message}]');
    }
  }

  Future<void> _primePairingLanSession(String baseUrl) async {
    final hostWithPort = _hostPortFromApiBaseUrl(baseUrl);
    if (hostWithPort.isEmpty) return;
    final session = await _client.loadSession();
    await _client.saveSession(
      session.copyWith(fhdHost: hostWithPort, serverMode: 'lan'),
    );
  }

  Future<String> _resolvePairingExchangeBaseUrl(
    PairingPayload? parsed,
    String raw,
  ) async {
    if (parsed != null) {
      final fromPayload = parsed.apiBaseUrl.isNotEmpty
          ? _ensureTrailingSlash(parsed.apiBaseUrl)
          : _pairingLanBaseUrl(parsed.host, parsed.port);
      if (fromPayload.isNotEmpty) return fromPayload;
    }

    final session = await _client.loadSession();
    final fromSession = _pairingLanBaseUrlFromHostPort(session.fhdHost);
    if (fromSession.isNotEmpty) return fromSession;

    if (raw.startsWith('{')) {
      throw const MobileRepositoryException('二维码内容无法识别，请在电脑端刷新二维码后重试');
    }
    return '';
  }

  String _pairingExchangeNonce(
    PairingPayload? parsed,
    String raw,
    String code,
  ) {
    if (parsed != null) {
      if (parsed.version >= 2 && code.isEmpty) {
        return parsed.nonce.ifEmpty(parsed.token);
      }
      return parsed.nonce;
    }
    if (code.isNotEmpty) return '';
    if (raw.length >= 8) return raw;
    return '';
  }

  Future<void> confirmAuthQr({
    required String qrId,
    required String username,
    required String password,
    required String accountKind,
  }) async {
    if (qrId.trim().isEmpty) {
      throw const MobileRepositoryException('扫码登录二维码缺少 qr_id');
    }
    final response = await _client.confirmAuthQr(
      qrId: qrId,
      username: username,
      password: password,
      accountKind: accountKind,
    );
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('扫码登录确认失败'));
    }
  }

  Future<void> login({
    required String username,
    required String password,
    required bool adminMode,
    bool rememberPass = false,
    bool autoLogin = false,
  }) async {
    if (username.trim().isEmpty || password.isEmpty) {
      throw const MobileRepositoryException('用户名和密码不能为空');
    }
    final response = await _client.login(
      username: username,
      password: password,
      accountKind: adminMode ? 'admin' : 'enterprise',
    );
    if (!response.success) {
      throw MobileRepositoryException(
        response.message.ifEmpty(adminMode ? '账号或密码错误' : '用户名或密码错误'),
      );
    }
    await _client.persistLoginSession(
      response.data,
      fallbackUsername: username,
      fallbackAccountKind: adminMode ? 'admin' : 'enterprise',
    );
    await _client.saveLoginPreferences(
      username: username,
      password: password,
      rememberPassword: rememberPass,
      autoLogin: autoLogin,
    );
  }

  Future<void> register({
    required String username,
    required String password,
    required String email,
    required String industryId,
    required String budgetRange,
  }) async {
    if (username.trim().isEmpty || password.isEmpty) {
      throw const MobileRepositoryException('用户名和密码不能为空');
    }
    final response = await _client.register(
      username: username,
      password: password,
      email: email,
      industryId: industryId,
      budgetRange: budgetRange,
      accountKind: 'enterprise',
    );
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('注册失败，请稍后重试'));
    }
  }

  Future<void> sendPhoneCode(String phone) async {
    if (phone.trim().length != 11) {
      throw const MobileRepositoryException('请输入 11 位手机号');
    }
    final response = await _client.sendPhoneCode(phone);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('验证码发送失败'));
    }
  }

  Future<void> loginWithPhoneCode({
    required String phone,
    required String code,
  }) async {
    final response = await _client.loginWithPhoneCode(
      phone: phone,
      code: code,
      accountKind: 'enterprise',
    );
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('验证码错误或已过期'));
    }
    await _client.persistLoginSession(
      response.data,
      fallbackUsername: phone,
      fallbackAccountKind: 'enterprise',
    );
  }

}
