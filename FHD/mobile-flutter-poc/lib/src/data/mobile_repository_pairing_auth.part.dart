part of 'mobile_repository.dart';

abstract class _RepoPairingAuthBase extends _RepoGroupsBase {
  Future<void> exchangePairingCode(String raw) async {
    final text = raw.trim();
    if (text.isEmpty) {
      throw const MobileRepositoryException('无法识别配对码');
    }
    final parsed = parsePairingPayload(text);
    if (parsed != null && parsed.version >= 3 && parsed.relayId.isNotEmpty) {
      throw const MobileRepositoryException('云中继绑定请先登录账号，登录后将自动完成绑定');
    }

    final code = _pairingExchangeCode(parsed, text);
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
      try {
        await _client.relayBindAccount(relayId);
      } catch (_) {
        // Leave relay binding cleared when account relay bind fails.
      }
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

    final shortCode = _pairingExchangeCode(parsed, raw);
    if (RegExp(r'^\d{6}$').hasMatch(shortCode)) {
      return _discoverLanBaseUrlForShortCode(shortCode);
    }
    if (raw.startsWith('{')) {
      throw const MobileRepositoryException('二维码内容无法识别，请在电脑端刷新二维码后重试');
    }
    return '';
  }

  static const _lanPairingProbeTimeout = Duration(milliseconds: 900);

  Future<String> _discoverLanBaseUrlForShortCode(String code) async {
    final cleanCode = code.trim();
    if (!RegExp(r'^\d{6}$').hasMatch(cleanCode)) return '';
    final session = await _client.loadSession();
    final candidates = await _lanPairingCandidateBaseUrls(session.fhdHost);
    for (final baseUrl in candidates) {
      try {
        final lookup = await _client
            .pairingLookup(code: cleanCode, baseUrl: baseUrl)
            .timeout(_lanPairingProbeTimeout);
        if (lookup.success) return baseUrl;
      } on TimeoutException {
        // 继续尝试下一个候选
      } catch (_) {
        // 继续尝试下一个候选
      }
    }
    return '';
  }

  Future<List<String>> _lanPairingCandidateBaseUrls(
    String configuredHost,
  ) async {
    const lanPorts = [5011, 5100, 17500, 5001, 5000];
    final hostPorts = <String>[];
    final configured = _normalizePairingHost(configuredHost);
    if (configured.isNotEmpty) {
      if (configured.contains(':')) {
        hostPorts.add(configured);
      } else {
        for (final port in lanPorts) {
          hostPorts.add('$configured:$port');
        }
      }
    }

    try {
      final ifaces = await NetworkInterface.list(
        type: InternetAddressType.IPv4,
      );
      for (final iface in ifaces) {
        for (final addr in iface.addresses) {
          final ip = addr.address;
          if (ip.startsWith('127.') || ip.startsWith('169.254.')) continue;
          final parts = ip.split('.');
          if (parts.length != 4) continue;
          final prefix = '${parts[0]}.${parts[1]}.${parts[2]}';
          for (final hostOctet in ['1', '2', '100']) {
            for (final port in lanPorts) {
              hostPorts.add('$prefix.$hostOctet:$port');
            }
          }
        }
      }
    } catch (_) {
      // 网络接口枚举失败时忽略，仅依赖已配置 host
    }

    final seen = <String>{};
    final bases = <String>[];
    for (final hostPort in hostPorts) {
      final base = _pairingLanBaseUrlFromHostPort(hostPort);
      if (base.isNotEmpty && seen.add(base)) {
        bases.add(base);
      }
    }
    return bases;
  }

  String _pairingExchangeCode(PairingPayload? parsed, String raw) {
    if (parsed != null) return parsed.code.trim();
    if (RegExp(r'^\d{6}$').hasMatch(raw)) return raw;
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
