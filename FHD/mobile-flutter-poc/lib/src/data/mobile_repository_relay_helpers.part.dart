part of 'mobile_repository.dart';


Map<String, Object?> _superEmployeeRelayContext({String conversationId = ''}) {
  return {
    'source': 'mobile_chat',
    'client_surface': 'mobile',
    'workspace_root': _xcmaxDefaultWorkspaceRoot,
    if (conversationId.trim().isNotEmpty)
      'conversation_id': conversationId.trim(),
  };
}

PairingPayload? parsePairingPayload(String raw) {
  final text = raw.trim();
  if (text.isEmpty || text.toLowerCase().contains('auth-qr')) {
    return null;
  }
  if (text.length == 6 && int.tryParse(text) != null) {
    return PairingPayload(code: text, token: text, version: 2);
  }

  final uri = Uri.tryParse(text);
  if (uri != null && uri.scheme.toLowerCase() == 'xcagi') {
    final route = '${uri.host}${uri.path}';
    if (!route.toLowerCase().contains('pair')) {
      return null;
    }
    final code = _firstNonBlank([
      uri.queryParameters['code'] ?? '',
      uri.queryParameters['shortCode'] ?? '',
      uri.queryParameters['short_code'] ?? '',
      uri.queryParameters['token'] ?? '',
    ]);
    final apiBaseUrl = _firstNonBlank([
      uri.queryParameters['api_base_url'] ?? '',
      uri.queryParameters['api_base'] ?? '',
      uri.queryParameters['base_url'] ?? '',
    ]);
    final fromBase = _pairingHostPortFromApiBase(apiBaseUrl);
    final host = _normalizePairingHost(
      (uri.queryParameters['host'] ?? '').ifEmpty(fromBase.$1),
    );
    final port =
        (int.tryParse(uri.queryParameters['port'] ?? '') ?? fromBase.$2)
            .takeIfValidPort();
    final relayId = _firstNonBlank([
      uri.queryParameters['relay_id'] ?? '',
      uri.queryParameters['relayId'] ?? '',
    ]);
    final relayBaseUrl = _firstNonBlank([
      uri.queryParameters['relay_base_url'] ?? '',
      uri.queryParameters['relayBaseUrl'] ?? '',
    ]);
    if (relayId.isNotEmpty && code.isNotEmpty) {
      return PairingPayload(
        code: code,
        token: code,
        relayId: relayId,
        relayBaseUrl: relayBaseUrl,
        version: 3,
      );
    }
    if (code.isNotEmpty) {
      return PairingPayload(
        nonce: uri.queryParameters['nonce']?.trim() ?? '',
        code: code,
        token: code,
        host: host,
        port: port,
        apiBaseUrl: apiBaseUrl,
        version: 2,
      );
    }
    final nonce = uri.queryParameters['nonce']?.trim() ?? '';
    if (nonce.length >= 8 && host.isNotEmpty && port > 0) {
      return PairingPayload(
        nonce: nonce,
        host: host,
        port: port,
        apiBaseUrl: apiBaseUrl,
        version: 1,
      );
    }
    return null;
  }

  final jsonLike = _tryDecodeObject(text);
  if (jsonLike.isNotEmpty) {
    final version = _intField(jsonLike, 'v').ifZero(1);
    final kind = _stringField(jsonLike, 'kind').toLowerCase();
    final relayId = _firstNonBlank([
      _stringField(jsonLike, 'relay_id'),
      _stringField(jsonLike, 'relayId'),
    ]);
    final relayBaseUrl = _firstNonBlank([
      _stringField(jsonLike, 'relay_base_url'),
      _stringField(jsonLike, 'relayBaseUrl'),
    ]);
    final code = _firstNonBlank([
      _stringField(jsonLike, 't'),
      _stringField(jsonLike, 'code'),
      _stringField(jsonLike, 'shortCode'),
      _stringField(jsonLike, 'short_code'),
      _stringField(jsonLike, 'token'),
    ]);
    if ((version >= 3 || kind.contains('relay')) &&
        relayId.isNotEmpty &&
        code.isNotEmpty) {
      return PairingPayload(
        code: code,
        token: code,
        relayId: relayId,
        relayBaseUrl: relayBaseUrl,
        version: 3,
      );
    }
    final apiBaseUrl = _firstNonBlank([
      _stringField(jsonLike, 'api_base_url'),
      _stringField(jsonLike, 'base_url'),
      _stringField(jsonLike, 'apiBaseUrl'),
    ]);
    final fromBase = _pairingHostPortFromApiBase(apiBaseUrl);
    final host = _normalizePairingHost(
      _stringField(jsonLike, 'host').ifEmpty(fromBase.$1),
    );
    final port = _pairingPort(jsonLike, host).ifZero(fromBase.$2);
    final bareHost = host.split(':').first.trim();
    final hasHostPort = bareHost.isNotEmpty && port.takeIfValidPort() > 0;
    if ((version >= 2 || kind.contains('pairing')) && code.isNotEmpty) {
      return PairingPayload(
        nonce: _stringField(jsonLike, 'nonce'),
        code: code,
        token: code,
        host: hasHostPort ? bareHost : '',
        port: hasHostPort ? port.takeIfValidPort() : 0,
        apiBaseUrl: apiBaseUrl,
        version: 2,
      );
    }
    final nonce = _stringField(jsonLike, 'nonce');
    if (version >= 2 || kind.contains('pairing')) {
      if (nonce.isEmpty) return null;
      return PairingPayload(
        nonce: nonce,
        token: nonce,
        host: hasHostPort ? bareHost : '',
        port: hasHostPort ? port.takeIfValidPort() : 0,
        apiBaseUrl: apiBaseUrl,
        version: 2,
      );
    }
    if (nonce.length >= 8 && hasHostPort) {
      return PairingPayload(
        nonce: nonce,
        host: bareHost,
        port: port.takeIfValidPort(),
        version: 1,
      );
    }
  }

  return null;
}

AuthQrPayload? parseAuthQrPayload(String raw) {
  final text = raw.trim();
  if (!text.contains('auth-qr')) return null;
  final uri = Uri.tryParse(text);
  if (uri == null) return null;
  final qrId = uri.queryParameters['qr_id']?.trim() ?? '';
  if (qrId.isEmpty) return null;
  return AuthQrPayload(
    qrId: qrId,
    accountKind:
        (uri.queryParameters['account_kind'] ?? '').trim().toLowerCase(),
  );
}

List<Map<String, Object?>> _relayDesktopRows(Map<String, Object?>? data) {
  final raw = data?['items'] ?? data?['desktops'] ?? data?['results'];
  return _objectList(raw);
}

List<ModInfo> _parseModInfos(Map<String, Object?> body) {
  final data = _nestedDataMap(body);
  final nestedData = _objectMap(data['data']);
  final rows = _firstObjectList([
    nestedData['items'],
    nestedData['mods'],
    nestedData['installed'],
    data['items'],
    data['mods'],
    data['installed'],
  ]);
  return rows.map(ModInfo.fromJson).toList(growable: false);
}

/// Session cache only needs list-row fields; avoid bloating xcagi_session.json.
Map<String, Object?> _modInfoToCacheJson(ModInfo mod) {
  return {
    'id': mod.id,
    'name': mod.name,
    'version': mod.version,
    'description': mod.description,
    'author': mod.author,
    'primary': mod.primary,
    'industry': mod.industry == null
        ? null
        : {'id': mod.industry!.id, 'name': mod.industry!.name},
    'workflow_employees': mod.workflowEmployees
        .map(
          (employee) => {
            'id': employee.id,
            'label': employee.label,
            'panel_title': employee.panelTitle,
            'panel_summary': employee.panelSummary,
            'api_base_path': employee.apiBasePath,
            'phone_channel': employee.phoneChannel,
            'profile_source': employee.profileSource,
          },
        )
        .toList(growable: false),
  }..removeWhere((_, value) => value == null);
}

bool _relayDesktopIsDispatchable(Map<String, Object?> row) {
  final relayId = _stringField(row, 'relay_id');
  final status = _stringField(row, 'status').toLowerCase();
  // 与 Kotlin 一致：账号下 status=paired 即可派工；last_seen 只影响排序，不阻断中继。
  // 否则桌面轮询稍停就会误走云端 /admin/*-super-employee（服务器 CLI），而非 cursor.invoke 本机执行。
  return relayId.isNotEmpty && status == 'paired';
}

bool _relayDesktopIsFresh(Map<String, Object?> row) {
  final lastSeen = _firstNonBlank([
    _stringField(row, 'last_seen_at'),
    _stringField(row, 'updated_at'),
  ]);
  if (lastSeen.isEmpty) return false;
  final parsed = DateTime.tryParse(lastSeen)?.toUtc();
  if (parsed == null) return false;
  final age = DateTime.now().toUtc().difference(parsed);
  if (age.isNegative) return true;
  return age <= const Duration(minutes: 5);
}

String _relayDesktopSortKey(Map<String, Object?> row) {
  return _firstNonBlank([
    _stringField(row, 'last_seen_at'),
    _stringField(row, 'updated_at'),
    _stringField(row, 'paired_at'),
  ]);
}

String _relayTaskResultText(Map<String, Object?> task) {
  final result = _objectMap(task['result']);
  if (result.isEmpty) return '';
  final error = _stringField(result, 'error');
  if (error.isNotEmpty) return error;
  final codex = _objectMap(result['codex']);
  final assistant = _objectMap(codex['assistant_message']);
  final body = _stringField(assistant, 'body');
  if (body.isNotEmpty) return body;
  return _stringField(result, 'reply');
}
