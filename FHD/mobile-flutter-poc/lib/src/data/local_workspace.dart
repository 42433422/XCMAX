import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:cryptography/cryptography.dart';
import 'package:drift/drift.dart';
import 'package:drift_flutter/drift_flutter.dart';
import 'package:flutter/foundation.dart' show ChangeNotifier, visibleForTesting;

import '../platform/credential_cipher.dart';

part 'local_workspace_peer.part.dart';

enum LocalWorkspaceOrigin { desktop, mobile }

class LocalWorkspaceRecord {
  LocalWorkspaceRecord({
    required this.id,
    required this.kind,
    required Map<String, Object?> data,
    this.deleted = false,
    this.version,
  }) : data = Map.unmodifiable(data);

  factory LocalWorkspaceRecord.fromJson(Object? value) {
    final json = _object(value);
    final id = json['id'];
    final kind = json['kind'];
    final deleted = json['deleted'];
    final version = json['version'];
    if (id is! String ||
        id.trim().isEmpty ||
        id.length > 128 ||
        !_kinds.contains(kind) ||
        deleted is! bool ||
        (version != null && (version is! String || version.isEmpty))) {
      throw const FormatException('本地工作区记录格式无效');
    }
    return LocalWorkspaceRecord(
      id: id,
      kind: kind as String,
      data: _object(json['data']),
      deleted: deleted,
      version: version as String?,
    );
  }

  final String id, kind;
  final Map<String, Object?> data;
  final bool deleted;
  final String? version;
  String get _key => _recordKey(kind, id);

  Map<String, Object?> toJson() => {
        'id': id,
        'kind': kind,
        'data': data,
        'deleted': deleted,
        'version': version,
      };

  LocalWorkspaceRecord _atVersion(String? version) => LocalWorkspaceRecord(
        id: id,
        kind: kind,
        data: data,
        deleted: deleted,
        version: version,
      );
}

class LocalWorkspaceConflict {
  const LocalWorkspaceConflict({
    required this.opId,
    required this.local,
    required this.current,
  });

  final String opId;
  final LocalWorkspaceRecord local;
  final LocalWorkspaceRecord? current;
}

class LocalWorkspaceArchive {
  const LocalWorkspaceArchive({
    required this.id,
    required this.createdAt,
    required this.records,
  });

  final String id;
  final DateTime createdAt;
  final List<LocalWorkspaceRecord> records;
}

class _Operation {
  const _Operation(this.id, this.record);

  factory _Operation.fromJson(Object? value) {
    final json = _object(value);
    return _Operation(
      json['op_id'] as String,
      LocalWorkspaceRecord.fromJson({...json, 'version': json['base_version']}),
    );
  }

  final String id;
  final LocalWorkspaceRecord record;

  Map<String, Object?> toJson() => {
        'op_id': id,
        'id': record.id,
        'kind': record.kind,
        'data': record.data,
        'deleted': record.deleted,
        'base_version': record.version,
      };
}

class LocalWorkspaceController extends ChangeNotifier {
  LocalWorkspaceController({
    QueryExecutor? executor,
    LocalWorkspacePeer? peer,
    PlatformCredentialCipher? cipher,
  })  : _store = executor == null ? _shared : _WorkspaceDatabase(executor),
        _peer = peer ?? LocalWorkspaceLanPeer(),
        _cipher = cipher ?? const PlatformCredentialCipher();

  static final _shared = _WorkspaceDatabase(
    driftDatabase(name: 'xcagi_local_workspace'),
  );

  final _WorkspaceDatabase _store;
  final LocalWorkspacePeer _peer;
  final PlatformCredentialCipher _cipher;
  bool _disposed = false;
  bool _busy = false;
  String? _endpoint;
  int _pendingCount = 0;
  List<LocalWorkspaceRecord> _records = const [];
  List<LocalWorkspaceConflict> _conflicts = const [];
  List<LocalWorkspaceArchive> _archives = const [];
  bool? _remoteUnbindConfirmed;

  bool get busy => _busy;
  bool get isBound => _endpoint != null;
  String? get endpoint => _endpoint;
  int get pendingCount => _pendingCount;
  List<LocalWorkspaceRecord> get records => _records;
  List<LocalWorkspaceConflict> get conflicts => _conflicts;
  List<LocalWorkspaceArchive> get archives => _archives;
  bool? get remoteUnbindConfirmed => _remoteUnbindConfirmed;

  Future<void> open() => reload();
  Future<void> reload() => _run(() async {});

  Future<void> save(String kind, Map<String, Object?> data, {String? id}) =>
      _run(() async {
        if (!_kinds.contains(kind)) {
          throw ArgumentError.value(kind, 'kind', '不支持此记录类型');
        }
        final old = id == null ? null : await _store.record(kind, id);
        if (id != null && (old == null || old.deleted || old.kind != kind)) {
          throw StateError('记录已变更，请刷新后重试');
        }
        final record = LocalWorkspaceRecord(
          id: id ?? _newId(),
          kind: kind,
          data: _object(jsonDecode(jsonEncode(data))),
          version: old?.version,
        );
        final normalized = record.toJson()..remove('version');
        if (utf8.encode(jsonEncode(normalized)).length > 64 * 1024) {
          throw const FormatException('单条本地记录超过 64 KiB，请缩短内容后再保存。');
        }
        await _write(record);
      });

  Future<void> delete(String id, {String? kind}) => _run(() async {
        final old = kind == null
            ? await _store.uniqueRecord(id)
            : await _store.record(kind, id);
        if (old == null || old.deleted) return;
        await _write(LocalWorkspaceRecord(
          id: old.id,
          kind: old.kind,
          data: old.data,
          deleted: true,
          version: old.version,
        ));
      });

  Future<void> _write(LocalWorkspaceRecord record) async {
    final bound = await _store.meta('binding') != null;
    await _store.transaction(() async {
      if (record.deleted && !bound) {
        await _store.removeRecord(record._key);
      } else {
        await _store.putRecord(record);
      }
      if (bound) await _store.putOperation(_Operation(_newId(), record));
    });
  }

  Future<void> bind(String qr, {required LocalWorkspaceOrigin origin}) =>
      _run(() async {
        if (await _store.meta('binding') != null) {
          throw StateError('请先解除当前绑定');
        }
        final code = _PairingCode.parse(qr);
        final local = await _store.records();
        final staged = await _store.meta('pending_bind');
        late Map<String, Object?> request;
        late String sealedKey;
        if (staged?['endpoint'] == code.endpoint.toString() &&
            await _cipher.decrypt(staged!['key'] as String) == code.key) {
          request = _object(staged['request']);
          if (request['origin'] != origin.name) {
            throw StateError('该二维码已有待完成的绑定，请使用原数据来源重试');
          }
          sealedKey = staged['key'] as String;
        } else {
          request = {
            'request_id': _newId(),
            'action': 'bind',
            'origin': origin.name,
            if (origin == LocalWorkspaceOrigin.mobile)
              'records': local
                  .map((record) => record._atVersion(_newId()).toJson())
                  .toList(),
          };
          _boundedJson(request);
          sealedKey = await _cipher.encrypt(code.key);
          await _store.putMeta('pending_bind', {
            'endpoint': code.endpoint.toString(),
            'key': sealedKey,
            'request': request,
          });
        }
        final reply = await _peer.send(
            endpoint: code.endpoint, key: code.key, request: request);
        _checkReply(reply, request['request_id'] as String);
        final workspaceId = reply['workspace_id'];
        final cursor = reply['cursor'];
        if (workspaceId is! String ||
            workspaceId.isEmpty ||
            cursor is! int ||
            cursor < 0) {
          throw const FormatException('电脑返回了无效的工作区信息');
        }
        final remote = _list(reply['records'])
            .map(LocalWorkspaceRecord.fromJson)
            .toList(growable: false);
        if (remote.map((record) => record._key).toSet().length !=
            remote.length) {
          throw const FormatException('电脑返回了重复的工作区记录');
        }
        await _store.transaction(() async {
          if (origin == LocalWorkspaceOrigin.desktop && local.isNotEmpty) {
            await _store.archive(local);
          }
          await _store.clearReplica();
          for (final record in remote) {
            await _store.putRecord(record);
          }
          if (origin == LocalWorkspaceOrigin.mobile) {
            await _applyEditsDuringBinding(
                local, _list(request['records']), remote);
          }
          await _store.putMeta('binding', {
            'endpoint': code.endpoint.toString(),
            'key': sealedKey,
            'workspace_id': workspaceId,
            'cursor': cursor,
          });
          await _store.removeMeta('pending_bind');
        });
        _remoteUnbindConfirmed = null;
      });

  Future<void> _applyEditsDuringBinding(
    List<LocalWorkspaceRecord> local,
    List<Object?> requested,
    List<LocalWorkspaceRecord> remote,
  ) async {
    final seeded = {
      for (final record in requested.map(LocalWorkspaceRecord.fromJson))
        record._key: record,
    };
    final replacements = {for (final record in remote) record._key: record};
    final current = {for (final record in local) record._key: record};
    for (final key in {...seeded.keys, ...current.keys}) {
      final previous = seeded[key];
      final edited = current[key];
      final replica = replacements[key];
      if (edited == null && replica == null) continue;
      if (edited != null &&
          previous != null &&
          replica != null &&
          jsonEncode(edited.data) == jsonEncode(previous.data) &&
          edited.deleted == previous.deleted) {
        continue;
      }
      final base = previous?.version;
      final record = edited?._atVersion(base) ??
          LocalWorkspaceRecord(
            id: replica!.id,
            kind: replica.kind,
            data: replica.data,
            deleted: true,
            version: base,
          );
      await _store.putRecord(record);
      await _store.putOperation(_Operation(_newId(), record));
      if (replica?.version != base) await _store.putConflict(key, replica);
    }
  }

  Future<void> sync() => _run(() async {
        final binding = await _requiredBinding();
        final code = await _openBinding(binding);
        await _pull(binding, code);
        await _push(binding, code);
        await _pull(binding, code);
      });

  Future<void> _push(Map<String, Object?> binding, _PairingCode code) async {
    final operations = await _store.operations(readyOnly: true);
    var offset = 0;
    while (offset < operations.length) {
      var limit = min(20, operations.length - offset);
      while (true) {
        final page = operations.sublist(offset, offset + limit);
        late Map<String, Object?> reply;
        try {
          reply = await _exchange(binding, code, 'push', {
            'operations': page.map((operation) => operation.toJson()).toList(),
          });
        } on _PacketTooLarge {
          if (limit == 1) rethrow;
          limit = max(1, limit ~/ 2);
          continue;
        }
        await _applyPush(page, reply);
        offset += limit;
        break;
      }
    }
  }

  Future<void> _applyPush(
      List<_Operation> operations, Map<String, Object?> reply) async {
    final byId = {for (final operation in operations) operation.id: operation};
    final accepted = <_Operation>[];
    for (final id in _list(reply['accepted'])) {
      final operation = byId.remove(id);
      if (operation == null) {
        throw const FormatException('电脑返回了未知的同步操作');
      }
      accepted.add(operation);
    }
    final conflicts = <(_Operation, LocalWorkspaceRecord?)>[];
    for (final value in _list(reply['conflicts'])) {
      final json = _object(value);
      final operation = byId.remove(json['op_id']);
      if (operation == null || !json.containsKey('current')) {
        throw const FormatException('电脑返回了无效的冲突记录');
      }
      final remote = json['current'] == null
          ? null
          : LocalWorkspaceRecord.fromJson(json['current']);
      if (remote != null && remote._key != operation.record._key) {
        throw const FormatException('冲突与本机记录不匹配');
      }
      conflicts.add((operation, remote));
    }
    if (byId.isNotEmpty) throw const FormatException('电脑未确认全部同步操作');
    await _store.transaction(() async {
      for (final operation in accepted) {
        await _store.putRecord(operation.record._atVersion(operation.id));
        await _store.clearOperation(operation.record._key);
      }
      for (final (operation, remote) in conflicts) {
        await _store.putConflict(operation.record._key, remote);
      }
    });
  }

  Future<void> _pull(Map<String, Object?> binding, _PairingCode code) async {
    var limit = 20;
    while (true) {
      final after = binding['cursor'] as int;
      late Map<String, Object?> reply;
      try {
        reply = await _exchange(binding, code, 'pull', {
          'after': after,
          'limit': limit,
        });
      } on _PacketTooLarge {
        if (limit == 1) rethrow;
        limit = max(1, limit ~/ 2);
        continue;
      }
      final cursor = reply['cursor'];
      final more = reply['has_more'];
      if (cursor is! int ||
          more is! bool ||
          cursor < after ||
          (more && cursor == after)) {
        throw const FormatException('电脑返回了无效的同步游标');
      }
      var previous = after;
      final changes = <LocalWorkspaceRecord>[];
      for (final value in _list(reply['changes'])) {
        final json = _object(value);
        final seq = json['seq'];
        if (seq is! int || seq <= previous || seq > cursor) {
          throw const FormatException('电脑返回了无序的同步记录');
        }
        previous = seq;
        changes.add(LocalWorkspaceRecord.fromJson(json['record']));
      }
      if (cursor != previous) {
        throw const FormatException('同步游标超出了已接收的记录');
      }
      final next = {...binding, 'cursor': cursor};
      await _store.transaction(() async {
        for (final record in changes) {
          await _applyChange(record);
        }
        await _store.putMeta('binding', next);
      });
      binding['cursor'] = cursor;
      if (!more) return;
    }
  }

  Future<void> _applyChange(LocalWorkspaceRecord record) async {
    final pending = await _store.operation(record._key);
    if (pending == null || pending.id == record.version) {
      await _store.putRecord(record);
      if (pending != null) await _store.clearOperation(record._key);
    } else if (pending.record.version != record.version) {
      await _store.putConflict(record._key, record);
    }
  }

  Future<void> resolveConflict(String opId, {required bool keepLocal}) =>
      _run(() async {
        final conflict = (await _store.conflicts())
            .where((value) => value.opId == opId)
            .firstOrNull;
        if (conflict == null) throw StateError('冲突已变更，请刷新后再处理');
        final key = conflict.local._key;
        await _store.transaction(() async {
          await _store.clearOperation(key);
          if (keepLocal) {
            final record = conflict.local._atVersion(conflict.current?.version);
            await _store.putRecord(record);
            await _store.putOperation(_Operation(_newId(), record));
          } else if (conflict.current == null) {
            await _store.removeRecord(key);
          } else {
            await _store.putRecord(conflict.current!);
          }
        });
      });

  Future<void> unbind() => _run(() async {
        final binding = await _requiredBinding();
        _remoteUnbindConfirmed = false;
        try {
          final code = await _openBinding(binding);
          await _exchange(binding, code, 'unbind', const {});
          _remoteUnbindConfirmed = true;
        } on Exception {
          // Unlink locally even if the computer cannot be reached.
        } on StateError {
          // A revoked or unreadable key must not prevent local unlinking.
        }
        await _store.transaction(() async {
          await _store.detachReplica();
          await _store.removeMeta('binding');
        });
      });

  Future<void> restoreArchive(String id) => _run(() async {
        await _store.transaction(() async {
          if (await _store.meta('binding') != null) {
            throw StateError('请先解除电脑绑定再恢复归档');
          }
          final archived = await _store.archivedRecords(id);
          if (archived == null) throw StateError('未找到本机归档');
          final current = (await _store.records())
              .where((record) => !record.deleted)
              .toList(growable: false);
          await _store.archive(current);
          await _store.clearReplica();
          for (final record in archived.reversed) {
            await _store.putRecord(record._atVersion(null));
          }
        });
      });

  Future<Map<String, Object?>> _requiredBinding() async {
    final binding = await _store.meta('binding');
    if (binding == null) throw StateError('尚未绑定电脑');
    return binding;
  }

  Future<_PairingCode> _openBinding(Map<String, Object?> binding) async {
    final key = await _cipher.decrypt(binding['key'] as String);
    return _PairingCode.validate(binding['endpoint'], key);
  }

  Future<Map<String, Object?>> _exchange(
    Map<String, Object?> binding,
    _PairingCode code,
    String action,
    Map<String, Object?> payload,
  ) async {
    final id = _newId();
    final reply = await _peer.send(
      endpoint: code.endpoint,
      key: code.key,
      request: {
        ...payload,
        'request_id': id,
        'action': action,
        'workspace_id': binding['workspace_id'],
      },
    );
    _checkReply(reply, id);
    if (reply.containsKey('workspace_id') &&
        reply['workspace_id'] != binding['workspace_id']) {
      throw const FormatException('电脑工作区已切换，请重新绑定');
    }
    return reply;
  }

  Future<void> _run(Future<void> Function() action) async {
    if (_disposed) return;
    if (_busy) throw StateError('正在处理本地工作区，请稍候');
    _busy = true;
    notifyListeners();
    try {
      await _store.exclusive(() async {
        try {
          await action();
        } finally {
          if (!_disposed) await _refresh();
        }
      });
    } finally {
      _busy = false;
      if (!_disposed) notifyListeners();
    }
  }

  Future<void> _refresh() async {
    final binding = await _store.meta('binding');
    _endpoint = binding?['endpoint'] as String?;
    _records = List.unmodifiable(
        (await _store.records()).where((record) => !record.deleted));
    _conflicts = List.unmodifiable(await _store.conflicts());
    _pendingCount = (await _store.operations()).length;
    _archives = List.unmodifiable(await _store.archives());
  }

  @visibleForTesting
  Future<void> closeDatabase() => _store.close();

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}

class _WorkspaceDatabase extends GeneratedDatabase {
  _WorkspaceDatabase(super.executor);

  Future<void> _tail = Future.value();

  Future<void> exclusive(Future<void> Function() action) {
    final next = _tail.then((_) => action());
    _tail = next.then<void>((_) {}, onError: (Object _, StackTrace __) {});
    return next;
  }

  @override
  Iterable<TableInfo<Table, dynamic>> get allTables => const [];

  @override
  int get schemaVersion => 1;

  @override
  MigrationStrategy get migration => MigrationStrategy(
        onCreate: (_) async {
          for (final table in ['records', 'outbox', 'conflicts', 'meta']) {
            await customStatement(
                'CREATE TABLE $table (id TEXT PRIMARY KEY, json TEXT NOT NULL)');
          }
          await customStatement(
              'CREATE TABLE archives (id TEXT PRIMARY KEY, created_at INTEGER NOT NULL, json TEXT NOT NULL)');
        },
      );

  Future<void> _put(String table, String id, Object? value) => customStatement(
        'INSERT INTO $table (id, json) VALUES (?, ?) '
        'ON CONFLICT(id) DO UPDATE SET json = excluded.json',
        [id, jsonEncode(value)],
      );

  Future<void> _remove(String table, String id) =>
      customStatement('DELETE FROM $table WHERE id = ?', [id]);

  Future<Object?> _get(String table, String id) async {
    final row = await customSelect('SELECT json FROM $table WHERE id = ?',
        variables: [Variable(id)]).getSingleOrNull();
    return row == null ? null : jsonDecode(row.read<String>('json'));
  }

  Future<Map<String, Object?>?> meta(String id) async {
    final value = await _get('meta', id);
    return value == null ? null : _object(value);
  }

  Future<void> putMeta(String id, Map<String, Object?> value) =>
      _put('meta', id, value);

  Future<void> removeMeta(String id) => _remove('meta', id);

  Future<LocalWorkspaceRecord?> record(String kind, String id) async {
    final value = await _get('records', _recordKey(kind, id));
    return value == null ? null : LocalWorkspaceRecord.fromJson(value);
  }

  Future<LocalWorkspaceRecord?> uniqueRecord(String id) async {
    final matches = (await records()).where((record) => record.id == id);
    if (matches.isEmpty) return null;
    if (matches.length > 1) throw StateError('请选择记录类型后重试');
    return matches.single;
  }

  Future<List<LocalWorkspaceRecord>> records() async {
    final rows =
        await customSelect('SELECT json FROM records ORDER BY rowid DESC')
            .get();
    return rows
        .map((row) =>
            LocalWorkspaceRecord.fromJson(jsonDecode(row.read<String>('json'))))
        .toList(growable: false);
  }

  Future<void> putRecord(LocalWorkspaceRecord record) =>
      _put('records', record._key, record.toJson());

  Future<void> removeRecord(String id) => _remove('records', id);

  Future<_Operation?> operation(String id) async {
    final value = await _get('outbox', id);
    return value == null ? null : _Operation.fromJson(value);
  }

  Future<List<_Operation>> operations({bool readyOnly = false}) async {
    final rows = await customSelect(
      'SELECT outbox.json FROM outbox '
      '${readyOnly ? 'LEFT JOIN conflicts USING(id) WHERE conflicts.id IS NULL ' : ''}'
      'ORDER BY outbox.rowid',
    ).get();
    return rows
        .map((row) => _Operation.fromJson(jsonDecode(row.read<String>('json'))))
        .toList(growable: false);
  }

  Future<void> putOperation(_Operation operation) =>
      _put('outbox', operation.record._key, operation.toJson());

  Future<void> clearOperation(String id) async {
    await _remove('outbox', id);
    await _remove('conflicts', id);
  }

  Future<void> putConflict(String id, LocalWorkspaceRecord? remote) =>
      _put('conflicts', id, remote?.toJson());

  Future<List<LocalWorkspaceConflict>> conflicts() async {
    final rows = await customSelect(
      'SELECT outbox.json AS operation, conflicts.json AS current '
      'FROM conflicts JOIN outbox USING(id) ORDER BY conflicts.rowid',
    ).get();
    return rows.map((row) {
      final operation =
          _Operation.fromJson(jsonDecode(row.read<String>('operation')));
      final remote = jsonDecode(row.read<String>('current'));
      return LocalWorkspaceConflict(
        opId: operation.id,
        local: operation.record,
        current: remote == null ? null : LocalWorkspaceRecord.fromJson(remote),
      );
    }).toList(growable: false);
  }

  Future<void> archive(List<LocalWorkspaceRecord> records) => customStatement(
        'INSERT INTO archives (id, created_at, json) VALUES (?, ?, ?)',
        [
          _newId(),
          DateTime.now().millisecondsSinceEpoch,
          jsonEncode(records.map((record) => record.toJson()).toList()),
        ],
      );

  Iterable<LocalWorkspaceRecord> _decodeArchive(Object? value) => _list(value)
      .map(LocalWorkspaceRecord.fromJson)
      .where((record) => !record.deleted);

  Future<List<LocalWorkspaceRecord>?> archivedRecords(String id) async {
    final value = await _get('archives', id);
    return value == null ? null : _decodeArchive(value).toList(growable: false);
  }

  Future<List<LocalWorkspaceArchive>> archives() async {
    final rows = await customSelect(
            'SELECT * FROM archives ORDER BY created_at DESC, rowid DESC')
        .get();
    return rows.map((row) {
      return LocalWorkspaceArchive(
        id: row.read<String>('id'),
        createdAt:
            DateTime.fromMillisecondsSinceEpoch(row.read<int>('created_at')),
        records: List.unmodifiable(
            _decodeArchive(jsonDecode(row.read<String>('json')))),
      );
    }).toList(growable: false);
  }

  Future<void> clearReplica() async {
    await customStatement('DELETE FROM records');
    await customStatement('DELETE FROM outbox');
    await customStatement('DELETE FROM conflicts');
  }

  Future<void> detachReplica() async {
    final kept = (await records()).where((record) => !record.deleted);
    await clearReplica();
    for (final record in kept) {
      await putRecord(record._atVersion(null));
    }
  }
}

const _kinds = {'customer', 'product', 'order'};
final _random = Random.secure();

String _recordKey(String kind, String id) => '$kind:$id';

String _newId() => List.generate(
    16, (_) => _random.nextInt(256).toRadixString(16).padLeft(2, '0')).join();

Map<String, Object?> _object(Object? value) {
  if (value is! Map) throw const FormatException('本地工作区数据格式无效');
  return Map<String, Object?>.from(value);
}

List<Object?> _list(Object? value) {
  if (value is! List) throw const FormatException('本地工作区列表格式无效');
  return List<Object?>.from(value);
}
