part of 'local_workspace.dart';

abstract interface class LocalWorkspacePeer {
  Future<Map<String, Object?>> send({
    required Uri endpoint,
    required String key,
    required Map<String, Object?> request,
  });
}

class LocalWorkspaceLanPeer implements LocalWorkspacePeer {
  static const _timeout = Duration(seconds: 8);
  static final _cipher = AesGcm.with256bits();
  static final _requestAad = utf8.encode('xcagi-local-workspace-request-v1');
  static final _replyAad = utf8.encode('xcagi-local-workspace-response-v1');

  @override
  Future<Map<String, Object?>> send({
    required Uri endpoint,
    required String key,
    required Map<String, Object?> request,
  }) async {
    _PairingCode.validate(endpoint.toString(), key);
    final secret = SecretKey(_decodeWire(key));
    final sealed = await _cipher.encrypt(
      _boundedJson(request),
      secretKey: secret,
      aad: _requestAad,
    );
    final packet = utf8.encode(jsonEncode({
      'nonce': _encodeWire(sealed.nonce),
      'box': _encodeWire([...sealed.cipherText, ...sealed.mac.bytes]),
    }));
    if (packet.length > _maxWirePacket) throw const _PacketTooLarge();
    final client = HttpClient()
      ..connectionTimeout = _timeout
      ..findProxy = (_) => 'DIRECT';
    try {
      final upload = await client.postUrl(endpoint).timeout(_timeout);
      upload.followRedirects = false;
      upload.headers.contentType = ContentType.json;
      upload.contentLength = packet.length;
      upload.add(packet);
      final response = await upload.close().timeout(_timeout);
      if (response.statusCode == HttpStatus.requestEntityTooLarge) {
        throw const _PacketTooLarge();
      }
      if (response.statusCode != HttpStatus.ok) {
        throw const HttpException('电脑拒绝了请求，请检查绑定状态');
      }
      final bytes = await response.fold<List<int>>([], (buffer, chunk) {
        if (buffer.length + chunk.length > _maxWirePacket) {
          throw const _PacketTooLarge();
        }
        return buffer..addAll(chunk);
      }).timeout(_timeout);
      return await _decodeReply(bytes, secret);
    } finally {
      client.close(force: true);
    }
  }

  Future<Map<String, Object?>> _decodeReply(
    List<int> bytes,
    SecretKey secret,
  ) async {
    try {
      final wire = _object(jsonDecode(utf8.decode(bytes)));
      final nonce = _decodeWire(wire['nonce'] as String);
      final box = _decodeWire(wire['box'] as String);
      if (nonce.length != 12 || box.length < 16) {
        throw const FormatException('Invalid encrypted payload');
      }
      final macStart = box.length - 16;
      final decrypted = await _cipher.decrypt(
        SecretBox(box.sublist(0, macStart),
            nonce: nonce, mac: Mac(box.sublist(macStart))),
        secretKey: secret,
        aad: _replyAad,
      );
      return _object(jsonDecode(utf8.decode(decrypted)));
    } catch (_) {
      throw const FormatException('无法验证电脑的同步响应');
    }
  }
}

class _PairingCode {
  const _PairingCode(this.endpoint, this.key);

  factory _PairingCode.parse(String value) {
    Map<String, Object?> json;
    try {
      json = _object(jsonDecode(value));
    } on FormatException {
      throw const FormatException('请扫描电脑本地工作区的绑定二维码');
    }
    if (json['kind'] != 'xcagi_local_workspace' || json['v'] != 1) {
      throw const FormatException('请扫描电脑本地工作区的绑定二维码');
    }
    return _PairingCode.validate(json['endpoint'], json['key']);
  }

  factory _PairingCode.validate(Object? rawEndpoint, Object? rawKey) {
    final endpoint = rawEndpoint is String ? Uri.tryParse(rawEndpoint) : null;
    if (endpoint == null ||
        !endpoint.hasAuthority ||
        endpoint.scheme != 'http' ||
        !endpoint.hasPort ||
        endpoint.port <= 0 ||
        endpoint.port > 65535 ||
        endpoint.path != '/api/local-workspace/peer' ||
        endpoint.hasQuery ||
        endpoint.hasFragment ||
        endpoint.userInfo.isNotEmpty ||
        !_isLocalAddress(endpoint.host)) {
      throw const FormatException('二维码没有有效的电脑局域网地址');
    }
    if (rawKey is! String ||
        rawKey.length != 43 ||
        _decodeWire(rawKey).length != 32) {
      throw const FormatException('二维码没有有效的绑定密钥');
    }
    return _PairingCode(endpoint, rawKey);
  }

  final Uri endpoint;
  final String key;
}

bool _isLocalAddress(String host) {
  final ip = InternetAddress.tryParse(host);
  if (ip == null) return false;
  if (ip.isLoopback || ip.isLinkLocal) return true;
  final bytes = ip.rawAddress;
  if (ip.type == InternetAddressType.IPv6) return bytes[0] & 0xfe == 0xfc;
  return bytes[0] == 10 ||
      (bytes[0] == 172 && bytes[1] >= 16 && bytes[1] <= 31) ||
      (bytes[0] == 192 && bytes[1] == 168);
}

String _encodeWire(List<int> bytes) => base64Url.encode(bytes).split('=').first;

List<int> _decodeWire(String value) {
  if (!RegExp(r'^[a-zA-Z0-9_-]+$').hasMatch(value)) {
    throw const FormatException('绑定数据编码无效');
  }
  final bytes = base64Url.decode(base64Url.normalize(value));
  if (_encodeWire(bytes) != value) {
    throw const FormatException('绑定数据编码无效');
  }
  return bytes;
}

void _checkReply(Map<String, Object?> reply, String requestId) {
  if (reply['request_id'] != requestId) {
    throw const FormatException('电脑响应与当前请求不匹配');
  }
  if (reply['success'] == false || reply['error'] != null) {
    throw StateError(reply['message']?.toString() ??
        reply['error']?.toString() ??
        '电脑无法完成同步操作');
  }
}

const _maxWirePacket = 2 * 1024 * 1024;
const _maxPlainPacket = (_maxWirePacket - 1024) * 3 ~/ 4;

List<int> _boundedJson(Object? value) {
  final bytes = utf8.encode(jsonEncode(value));
  if (bytes.length > _maxPlainPacket) throw const _PacketTooLarge();
  return bytes;
}

class _PacketTooLarge implements Exception {
  const _PacketTooLarge();

  @override
  String toString() => '工作区数据超过单次局域网同步大小';
}
