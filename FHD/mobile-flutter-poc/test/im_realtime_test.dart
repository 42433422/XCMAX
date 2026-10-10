import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/im/im_messenger_screen.dart';
import 'package:xcagi_flutter_poc/src/im/im_websocket_client.dart';
import 'package:xcagi_flutter_poc/src/policy/mobile_runtime_policy.dart';

class _MemorySessionStore implements MobileSessionStore {
  _MemorySessionStore(this._data);

  MobileSessionData _data;

  @override
  Future<MobileSessionData> load() async => _data;

  @override
  Future<void> save(MobileSessionData session) async {
    _data = session;
  }

  @override
  Future<void> clear() async {
    _data = MobileSessionData.empty;
  }
}

Future<ImWsConnectionState> _waitFor(
  ImWebSocketClient client,
  ImWsConnectionState target,
) async {
  if (client.state == target) return target;
  return client.states
      .firstWhere((s) => s == target)
      .timeout(const Duration(seconds: 5));
}

void main() {
  setUp(MobileProductSkuConfig.resetRemoteSku);

  group('IM WebSocket URL follows the configured backend', () {
    test('derives ws/wss from an http(s) base', () {
      expect(
        MobileServerRouter.webSocketUrlForHttpBase(
          'http://10.0.2.2:17500/',
          's1',
        ),
        'ws://10.0.2.2:17500/ws/im?session_id=s1',
      );
      expect(
        MobileServerRouter.webSocketUrlForHttpBase(
          'https://xiu-ci.com/fhd-api/',
          's/1',
        ),
        'wss://xiu-ci.com/fhd-api/ws/im?session_id=s%2F1',
      );
    });

    test('cloud mode uses XCAGI_MOBILE_BASE_URL instead of hard-coded prod',
        () async {
      final repo = MobileRepository(
        client: MobileApiClient(
          config: const MobileApiConfig(baseUrl: 'http://10.0.2.2:17500/'),
          sessionStore: _MemorySessionStore(
            const MobileSessionData(serverMode: 'cloud'),
          ),
        ),
      );
      expect(
        await repo.imWebSocketUrlForSession('abc'),
        'ws://10.0.2.2:17500/ws/im?session_id=abc',
      );
    });

    test('cloud mode default stays on production fhd-api', () async {
      final repo = MobileRepository(
        client: MobileApiClient(
          config: const MobileApiConfig(
            baseUrl: 'https://xiu-ci.com/fhd-api',
          ),
          sessionStore: _MemorySessionStore(
            const MobileSessionData(serverMode: 'cloud'),
          ),
        ),
      );
      expect(
        await repo.imWebSocketUrlForSession('abc'),
        'wss://xiu-ci.com/fhd-api/ws/im?session_id=abc',
      );
    });

    test('LAN mode keeps the LAN host behaviour', () async {
      final repo = MobileRepository(
        client: MobileApiClient(
          config: const MobileApiConfig(baseUrl: 'http://10.0.2.2:17500/'),
          sessionStore: _MemorySessionStore(
            const MobileSessionData(
              serverMode: 'lan',
              fhdHost: '192.168.1.9:5112',
            ),
          ),
        ),
      );
      expect(
        await repo.imWebSocketUrlForSession('abc'),
        'ws://192.168.1.9:5112/ws/im?session_id=abc',
      );
    });
  });

  group('ImWebSocketClient reports the real connection state', () {
    test('connected only after the handshake succeeds', () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final sockets = <WebSocket>[];
      server.listen((request) async {
        sockets.add(await WebSocketTransformer.upgrade(request));
      });
      final client = ImWebSocketClient();
      addTearDown(() async {
        client.dispose();
        for (final s in sockets) {
          await s.close();
        }
        await server.close(force: true);
      });

      client.connect(
        sessionId: 's',
        url: 'ws://127.0.0.1:${server.port}/ws/im?session_id=s',
      );
      expect(client.state, ImWsConnectionState.connecting);
      expect(client.connected, isFalse);
      await _waitFor(client, ImWsConnectionState.connected);
      expect(client.connected, isTrue);

      // 服务端断开 → 不再显示已连接，进入重连。
      await sockets.single.close();
      await _waitFor(client, ImWsConnectionState.reconnecting);
      expect(client.connected, isFalse);

      client.disconnect();
      expect(client.state, ImWsConnectionState.disconnected);
    });

    test('unreachable host never reports connected', () async {
      final probe = await ServerSocket.bind(InternetAddress.loopbackIPv4, 0);
      final port = probe.port;
      await probe.close();
      final client = ImWebSocketClient();
      addTearDown(client.dispose);
      final seen = <ImWsConnectionState>[];
      final sub = client.states.listen(seen.add);
      addTearDown(sub.cancel);

      client.connect(
        sessionId: 's',
        url: 'ws://127.0.0.1:$port/ws/im?session_id=s',
      );
      await _waitFor(client, ImWsConnectionState.reconnecting);
      expect(seen, isNot(contains(ImWsConnectionState.connected)));
      expect(client.connected, isFalse);
    });
  });

  test('status text matches each connection state', () {
    expect(
      imWsStatusText(ImWsConnectionState.connected, conversationOpen: true),
      'WebSocket 已连接，消息实时同步',
    );
    expect(
      imWsStatusText(ImWsConnectionState.connecting, conversationOpen: true),
      '正在连接 WebSocket…',
    );
    expect(
      imWsStatusText(ImWsConnectionState.reconnecting, conversationOpen: true),
      contains('正在重连'),
    );
    expect(
      imWsStatusText(ImWsConnectionState.disconnected, conversationOpen: true),
      contains('未连接'),
    );
    expect(
      imWsStatusText(
        ImWsConnectionState.disconnected,
        conversationOpen: true,
        attached: false,
      ),
      '正在连接 WebSocket…',
    );
  });
}
