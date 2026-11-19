import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:cryptography/cryptography.dart';
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/data/local_workspace.dart';
import 'package:xcagi_flutter_poc/src/platform/credential_cipher.dart';

final _key = base64Url.encode(List.filled(32, 42)).split('=').first;

String _qr([String host = '192.168.1.12']) => jsonEncode({
      'kind': 'xcagi_local_workspace',
      'v': 1,
      'endpoint': 'http://$host:6100/api/local-workspace/peer',
      'key': _key,
    });

class _Cipher extends PlatformCredentialCipher {
  const _Cipher();

  @override
  Future<String> encrypt(String plain) async => 'enc:v1:test:$plain';

  @override
  Future<String> decrypt(String stored) async =>
      stored.replaceFirst('enc:v1:test:', '');
}

class _Peer implements LocalWorkspacePeer {
  final records = <String, Map<String, Object?>>{};
  final changes = <Map<String, Object?>>[];
  final bindings = <String, Map<String, Object?>>{};
  final bindPackets = <String>[];
  bool losePush = false;
  bool loseBind = false;
  bool offline = false;

  Map<String, Object?> update(
      String id, String kind, Map<String, Object?> data, String version,
      {bool deleted = false}) {
    final record = {
      'id': id,
      'kind': kind,
      'data': data,
      'deleted': deleted,
      'version': version,
    };
    records['$kind:$id'] = record;
    changes.add({'seq': changes.length + 1, 'record': record});
    return record;
  }

  @override
  Future<Map<String, Object?>> send({
    required Uri endpoint,
    required String key,
    required Map<String, Object?> request,
  }) async {
    expect(key, _key);
    expect(endpoint.toString(),
        'http://192.168.1.12:6100/api/local-workspace/peer');
    if (offline) throw const SocketException('offline');
    final requestId = request['request_id']! as String;
    final result = <String, Object?>{'request_id': requestId};
    if (request['action'] != 'bind') {
      expect(request['workspace_id'], 'desk-workspace');
    }
    switch (request['action']) {
      case 'bind':
        bindPackets.add(jsonEncode(request));
        final response = bindings.putIfAbsent(requestId, () {
          if (request['origin'] == 'mobile') {
            records.clear();
            changes.clear();
            for (final value in request['records']! as List) {
              final record = LocalWorkspaceRecord.fromJson(value);
              update(record.id, record.kind, record.data, record.version!);
            }
          }
          return {
            ...result,
            'workspace_id': 'desk-workspace',
            'records': records.values.toList(),
            'cursor': changes.length,
          };
        });
        if (loseBind) {
          loseBind = false;
          throw const SocketException('bind acknowledgement lost');
        }
        return response;
      case 'pull':
        final after = request['after']! as int;
        final page =
            changes.skip(after).take(request['limit']! as int).toList();
        return {
          ...result,
          'changes': page,
          'cursor': after + page.length,
          'has_more': after + page.length < changes.length,
        };
      case 'push':
        final accepted = <String>[];
        final conflicts = <Map<String, Object?>>[];
        for (final value in request['operations']! as List) {
          final op = Map<String, Object?>.from(value as Map);
          final id = op['id']! as String;
          final kind = op['kind']! as String;
          final opId = op['op_id']! as String;
          final current = records['$kind:$id'];
          if (current?['version'] != op['base_version']) {
            conflicts.add({'op_id': opId, 'current': current});
            continue;
          }
          update(id, kind, Map<String, Object?>.from(op['data']! as Map), opId,
              deleted: op['deleted']! as bool);
          accepted.add(opId);
        }
        if (losePush) {
          losePush = false;
          throw const SocketException('push acknowledgement lost');
        }
        return {...result, 'accepted': accepted, 'conflicts': conflicts};
      case 'unbind':
        return result;
      default:
        throw StateError('Unexpected action');
    }
  }
}

LocalWorkspaceController _controller(_Peer peer, {File? file}) =>
    LocalWorkspaceController(
      executor: file == null ? NativeDatabase.memory() : NativeDatabase(file),
      peer: peer,
      cipher: const _Cipher(),
    );

void main() {
  test('rejects oversized local records before they enter the sync queue',
      () async {
    final controller = LocalWorkspaceController(executor: NativeDatabase.memory());
    addTearDown(controller.closeDatabase);

    await expectLater(
      controller.save('customer', {'name': List.filled(24000, '客').join()}),
      throwsFormatException,
    );
    expect(controller.records, isEmpty);
    expect(controller.pendingCount, 0);
  });

  test('LAN transport encrypts the packet and verifies response AAD', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => server.close(force: true));
    final cipher = AesGcm.with256bits(), key = SecretKey(List.filled(32, 42));
    final request = Completer<void>();
    server.listen((connection) async {
      final raw = await utf8.decoder.bind(connection).join();
      final box = jsonDecode(raw) as Map<String, dynamic>;
      expect(box.keys.toSet(), {'nonce', 'box'});
      final nonce =
          base64Url.decode(base64Url.normalize(box['nonce'] as String));
      final bytes = base64Url.decode(base64Url.normalize(box['box'] as String));
      final message = await cipher.decrypt(
        SecretBox(bytes.sublist(0, bytes.length - 16),
            nonce: nonce, mac: Mac(bytes.sublist(bytes.length - 16))),
        secretKey: key,
        aad: utf8.encode('xcagi-local-workspace-request-v1'),
      );
      expect(jsonDecode(utf8.decode(message)), {'action': 'pull'});
      final reply = await cipher.encrypt(
        utf8.encode('{"success":true}'),
        secretKey: key,
        aad: utf8.encode('xcagi-local-workspace-response-v1'),
      );
      connection.response.write(jsonEncode({
        'nonce': base64Url.encode(reply.nonce).split('=').first,
        'box': base64Url
            .encode([...reply.cipherText, ...reply.mac.bytes])
            .split('=')
            .first,
      }));
      await connection.response.close();
      request.complete();
    });
    final result = await LocalWorkspaceLanPeer().send(
      endpoint:
          Uri.parse('http://127.0.0.1:${server.port}/api/local-workspace/peer'),
      key: _key,
      request: {'action': 'pull'},
    );
    await request.future;
    expect(result, {'success': true});
  });

  test(
      'desktop binding archives local records, and offline unbind retains draft',
      () async {
    final directory =
        Directory.systemTemp.createTempSync('local-workspace-test-');
    addTearDown(() => directory.deleteSync(recursive: true));
    final file = File('${directory.path}/test.sqlite');
    final peer = _Peer()..update('c', 'customer', {'name': '电脑客户'}, 'v1');
    final before = _controller(peer, file: file);
    await before.open();
    await before.save('customer', {'name': '手机客户'});
    expect(before.pendingCount, 0);
    await before.bind(_qr(), origin: LocalWorkspaceOrigin.desktop);
    expect(before.records.single.data['name'], '电脑客户');
    expect(before.archives.single.records.single.data['name'], '手机客户');
    await before.save('order', {'title': '手机草稿', 'status': 'draft'});
    expect(before.pendingCount, 1);
    before.dispose();
    await before.closeDatabase();

    final reopened = _controller(peer, file: file);
    addTearDown(reopened.closeDatabase);
    await reopened.open();
    expect(reopened.isBound, isTrue);
    expect(reopened.pendingCount, 1);
    expect(reopened.archives.single.records.single.data['name'], '手机客户');
    peer.offline = true;
    await reopened.unbind();
    expect(reopened.isBound, isFalse);
    expect(reopened.remoteUnbindConfirmed, isFalse);
    expect(reopened.pendingCount, 0);
    expect(
        reopened.records.where((record) => record.kind == 'order').single.data,
        containsPair('status', 'draft'));
  });

  test(
      'restore unbound archive preserves the current workspace in a new archive',
      () async {
    final peer = _Peer()
      ..update('desktop-c', 'customer', {'name': '电脑客户'}, 'v1');
    final workspace = _controller(peer);
    addTearDown(workspace.closeDatabase);
    await workspace.save('customer', {'name': '手机客户'});
    await workspace.bind(_qr(), origin: LocalWorkspaceOrigin.desktop);
    final phoneArchive = workspace.archives.single.id;

    await expectLater(workspace.restoreArchive(phoneArchive), throwsStateError);
    expect(workspace.records.single.data['name'], '电脑客户');
    expect(workspace.archives, hasLength(1));
    await workspace.unbind();
    await workspace.save('order', {'title': '新草稿'});
    await expectLater(workspace.restoreArchive('missing'), throwsStateError);
    expect(workspace.records, hasLength(2));

    await workspace.restoreArchive(phoneArchive);
    expect(workspace.records.single.data['name'], '手机客户');
    expect(workspace.pendingCount, 0);
    expect(workspace.isBound, isFalse);
    final laterArchive = workspace.archives.first;
    expect(laterArchive.id, isNot(phoneArchive));
    expect(laterArchive.records.map((record) => record.kind),
        unorderedEquals(['customer', 'order']));

    await workspace.restoreArchive(laterArchive.id);
    expect(workspace.records.map((record) => record.kind),
        unorderedEquals(['customer', 'order']));
    expect(workspace.records.every((record) => record.version == null), isTrue);
    expect(workspace.archives, hasLength(3));

    for (final record in workspace.records) {
      await workspace.delete(record.id, kind: record.kind);
    }
    await workspace.restoreArchive(phoneArchive);
    final emptyArchive = workspace.archives.first;
    expect(emptyArchive.records, isEmpty);
    await workspace.restoreArchive(emptyArchive.id);
    expect(workspace.records, isEmpty);
  });

  test('applied push with a lost acknowledgement is recovered from pull',
      () async {
    final peer = _Peer();
    final workspace = _controller(peer);
    addTearDown(workspace.closeDatabase);
    await workspace.bind(_qr(), origin: LocalWorkspaceOrigin.desktop);
    await workspace.save('product', {'name': '新商品'});
    peer.losePush = true;
    await expectLater(workspace.sync(), throwsA(isA<SocketException>()));
    expect(workspace.pendingCount, 1);
    expect(peer.changes, hasLength(1));
    await workspace.sync();
    expect(workspace.pendingCount, 0);
    expect(workspace.records.single.version, isNotNull);
    expect(peer.changes, hasLength(1));
  });

  test('a pull preserves pending edits until each conflict is resolved',
      () async {
    final peer = _Peer()
      ..update('same', 'customer', {'name': '客户'}, 'c1')
      ..update('same', 'product', {'name': '旧商品'}, 'p1');
    final workspace = _controller(peer);
    addTearDown(workspace.closeDatabase);
    await workspace.bind(_qr(), origin: LocalWorkspaceOrigin.desktop);
    expect(workspace.records, hasLength(2));
    await workspace.save('product', {'name': '手机修改'}, id: 'same');
    await workspace.delete('same', kind: 'customer');
    peer.update('same', 'product', {'name': '电脑修改'}, 'p2');
    peer.update('same', 'customer', {'name': '电脑客户'}, 'c2');
    await workspace.sync();
    expect(workspace.records.single.data['name'], '手机修改');
    expect(workspace.conflicts, hasLength(2));
    final product =
        workspace.conflicts.singleWhere((c) => c.local.kind == 'product');
    final customer =
        workspace.conflicts.singleWhere((c) => c.local.kind == 'customer');
    await workspace.resolveConflict(product.opId, keepLocal: true);
    await workspace.resolveConflict(customer.opId, keepLocal: false);
    await workspace.sync();
    expect(workspace.pendingCount, 0);
    expect(workspace.conflicts, isEmpty);
    expect(peer.records['product:same']!['data'], {'name': '手机修改'});
    expect(workspace.records.singleWhere((r) => r.kind == 'customer').data,
        {'name': '电脑客户'});
  });

  test('mobile binding retries its exact request and retains subsequent edits',
      () async {
    final peer = _Peer()..loseBind = true;
    final workspace = _controller(peer);
    addTearDown(workspace.closeDatabase);
    await workspace.save('customer', {'name': '最初客户'});
    final id = workspace.records.single.id;
    await expectLater(
        workspace.bind(_qr(), origin: LocalWorkspaceOrigin.mobile),
        throwsA(isA<SocketException>()));
    expect(workspace.isBound, isFalse);
    await workspace.save('customer', {'name': '后来修改'}, id: id);
    await workspace.bind(_qr(), origin: LocalWorkspaceOrigin.mobile);
    expect(peer.bindPackets, hasLength(2));
    expect(peer.bindPackets.first, peer.bindPackets.last);
    expect(workspace.records.single.data['name'], '后来修改');
    expect(workspace.pendingCount, 1);
    await workspace.sync();
    expect(workspace.pendingCount, 0);
    expect(peer.records['customer:$id']!['data'], {'name': '后来修改'});
  });

  test('rejects QR endpoints outside the local network', () async {
    final peer = _Peer();
    final workspace = _controller(peer);
    addTearDown(workspace.closeDatabase);
    await expectLater(
        workspace.bind(_qr('8.8.8.8'), origin: LocalWorkspaceOrigin.desktop),
        throwsA(isA<FormatException>()));
    expect(peer.bindPackets, isEmpty);
    expect(workspace.isBound, isFalse);
  });
}
