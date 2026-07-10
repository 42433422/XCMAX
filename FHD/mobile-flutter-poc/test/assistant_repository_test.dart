import 'package:archive/archive.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/assistant_assets.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/policy/pinned_ids.dart';

void main() {
  test('assistant search returns sources and sends memory context', () async {
    final api = _AssistantAssetsApi(_MemoryStore());
    final repository = MobileRepository(client: api);

    final result = await repository.searchAssistantMessage(
      body: '今天的官方更新',
      userId: 42,
    );

    expect(result.answer, '联网回答');
    expect(result.sources.single.title, '官方来源');
    expect(result.provider, 'bing_rss');
    expect(api.chatContext['kitten_web_search'], isTrue);
    expect(api.chatContext['assistant_memory'], contains('回答风格'));
    final session = await api.loadSession();
    expect(
      session.cachedChatMessages.values
          .expand((rows) => rows)
          .any((row) => row['sources'] is List),
      isTrue,
    );
  });

  test('assistant memory supports add confirm edit delete and switch',
      () async {
    final api = _AssistantAssetsApi(_MemoryStore());
    final repository = MobileRepository(client: api);

    expect(await repository.assistantMemoryEnabled(), isTrue);
    await repository.setAssistantMemoryEnabled(false);
    expect(await repository.assistantMemoryEnabled(), isFalse);
    final created = await repository.addAssistantMemory(
      key: '称呼',
      value: '叫我老板',
    );
    expect(created.isActive, isTrue);
    await repository.updateAssistantMemory(
      const AssistantMemoryRecord(
        id: 'mem-new',
        type: 'preference',
        key: '称呼',
        value: '叫我吴总',
        status: 'active',
      ),
    );
    expect(api.memories.single['value'], '叫我吴总');
    await repository.deleteAssistantMemory('mem-new');
    expect(api.memories.single['status'], 'deleted');
  });

  test('assistant file OCR TTS and employee availability use existing APIs',
      () async {
    final api = _AssistantAssetsApi(_MemoryStore());
    final repository = MobileRepository(client: api);

    final file = await repository.analyzeAssistantOfficeFile(
      filename: '周报.pdf',
      bytes: [1, 2, 3],
      contentType: 'application/pdf',
    );
    expect(file.employeeId, 'pdf-full-read-employee');
    expect(file.summary, contains('读取完成'));
    expect(
      await repository.recognizeAssistantImage(
        filename: 'photo.jpg',
        bytes: [1],
      ),
      '图片文字',
    );
    expect(await repository.synthesizeAssistantSpeech('你好'),
        startsWith('data:audio'));

    final availability = await repository.loadAssistantEmployeeAvailability();
    expect(availability.isOnline(PinnedIds.trae), isTrue);
    expect(availability.isOnline(PinnedIds.codex), isFalse);
  });

  test('assistant search and memory stay usable with an older cloud node',
      () async {
    final api = _StaleAssistantApi(_MemoryStore());
    final repository = MobileRepository(client: api);

    final result = await repository.searchAssistantMessage(body: '最新进展');
    expect(result.answer, contains('基于实时来源'));
    expect(result.sources.single.url, 'https://example.com/latest');
    expect(result.provider, 'bing_rss');
    expect(api.groundedPrompt, contains('实时来源'));

    final created = await repository.addAssistantMemory(
      key: '回答方式',
      value: '先说结论',
    );
    expect(created.id, startsWith('local_'));
    expect((await repository.loadAssistantMemories()).single.value, '先说结论');
    await repository.updateAssistantMemory(
      AssistantMemoryRecord(
        id: created.id,
        type: created.type,
        key: created.key,
        value: '一句话结论',
        status: created.status,
      ),
    );
    expect((await repository.loadAssistantMemories()).single.value, '一句话结论');
    await repository.deleteAssistantMemory(created.id);
    expect(await repository.loadAssistantMemories(), isEmpty);
  });

  test('file workbench shows local Word text instead of server path metadata',
      () async {
    final archive = Archive()
      ..addFile(
        ArchiveFile.string(
          'word/document.xml',
          '<w:document><w:body><w:p><w:r><w:t>会议结论</w:t></w:r>'
              '</w:p><w:p><w:r><w:t>负责人：小王</w:t></w:r></w:p>'
              '</w:body></w:document>',
        ),
      );
    final bytes = ZipEncoder().encode(archive);
    final repository = MobileRepository(
      client: _MetadataOfficeApi(_MemoryStore()),
    );

    final result = await repository.analyzeAssistantOfficeFile(
      filename: '会议.docx',
      bytes: bytes,
    );

    expect(result.summary, contains('会议结论'));
    expect(result.summary, contains('负责人：小王'));
    expect(result.summary, isNot(contains('output_path')));
  });
}

class _MemoryStore implements MobileSessionStore {
  MobileSessionData data = const MobileSessionData(
    username: 'tester',
    userId: 42,
  );

  @override
  Future<void> clear() async => data = MobileSessionData.empty;

  @override
  Future<MobileSessionData> load() async => data;

  @override
  Future<void> save(MobileSessionData value) async => data = value;
}

class _AssistantAssetsApi extends MobileApiClient {
  _AssistantAssetsApi(MobileSessionStore store) : super(sessionStore: store);

  Map<String, Object?> chatContext = const {};
  List<Map<String, Object?>> memories = [
    {
      'memory_id': 'mem-existing',
      'memory_type': 'preference',
      'key': '回答风格',
      'value': '先给结论',
      'status': 'active',
    },
  ];

  @override
  Future<MobileEnvelope<Map<String, Object?>>> me() async {
    return const MobileEnvelope(
      success: true,
      message: 'ok',
      data: {
        'user': {'id': 42, 'username': 'tester'},
      },
      raw: {},
    );
  }

  @override
  Future<Map<String, Object?>> chat(
    String message, {
    String? sessionId,
    Map<String, Object?> context = const {},
  }) async {
    chatContext = context;
    return {
      'success': true,
      'response': '联网回答',
      'data': {
        'web_search_results': [
          {
            'title': '官方来源',
            'url': 'https://example.com',
            'snippet': '官方摘要',
          },
        ],
        'web_search_meta': {'provider': 'bing_rss', 'query': message},
      },
    };
  }

  @override
  Future<Map<String, Object?>> memoryV2List({
    required String userId,
    String status = '',
  }) async {
    return {
      'success': true,
      'memories': status.isEmpty
          ? memories
          : memories.where((row) => row['status'] == status).toList(),
    };
  }

  @override
  Future<Map<String, Object?>> memoryV2Create({
    required String userId,
    required String key,
    required String value,
    String memoryType = 'preference',
  }) async {
    final row = <String, Object?>{
      'memory_id': 'mem-new',
      'memory_type': memoryType,
      'key': key,
      'value': value,
      'status': 'pending',
    };
    memories = [row];
    return {'success': true, 'memory': row};
  }

  @override
  Future<Map<String, Object?>> memoryV2Confirm({
    required String userId,
    required String memoryId,
  }) async {
    memories = memories
        .map((row) =>
            row['memory_id'] == memoryId ? {...row, 'status': 'active'} : row)
        .toList();
    return {'success': true, 'memory': memories.single};
  }

  @override
  Future<Map<String, Object?>> memoryV2Correct({
    required String userId,
    required String memoryId,
    required String key,
    required String value,
  }) async {
    memories = memories
        .map((row) => row['memory_id'] == memoryId
            ? {...row, 'key': key, 'value': value}
            : row)
        .toList();
    return {'success': true, 'memory': memories.single};
  }

  @override
  Future<Map<String, Object?>> memoryV2Delete({
    required String userId,
    required String memoryId,
  }) async {
    memories = memories
        .map((row) =>
            row['memory_id'] == memoryId ? {...row, 'status': 'deleted'} : row)
        .toList();
    return {'success': true};
  }

  @override
  Future<Map<String, Object?>> uploadOfficeFile({
    required String filename,
    required List<int> bytes,
    String contentType = 'application/octet-stream',
  }) async {
    return {
      'success': true,
      'data': {
        'file_path': 'uploads/chat/$filename',
        'workspace_root': '/tmp/workspace',
      },
    };
  }

  @override
  Future<Map<String, Object?>> runOfficeEmployee({
    required String employeeId,
    required String filePath,
    required String workspaceRoot,
  }) async =>
      {
        'success': true,
        'data': {'summary': '全文读取完成：三条重点'}
      };

  @override
  Future<Map<String, Object?>> recognizeImage({
    required String filename,
    required List<int> bytes,
    String contentType = 'image/jpeg',
  }) async =>
      {'success': true, 'text': '图片文字'};

  @override
  Future<Map<String, Object?>> synthesizeSpeech(
    String text, {
    String voice = 'zh-CN-XiaoxiaoNeural',
  }) async =>
      {
        'success': true,
        'data': {'audioBase64': 'data:audio/mpeg;base64,AA=='},
      };

  @override
  Future<MobileEnvelope<Map<String, Object?>>> relayDesktops() async {
    final now = DateTime.now().toUtc().toIso8601String();
    return MobileEnvelope(
      success: true,
      message: 'ok',
      data: {
        'items': [
          {
            'relay_id': 'relay-online',
            'status': 'paired',
            'last_seen_at': now,
            'label': '测试电脑',
            'capabilities': {
              'codex_cli': false,
              'claude_cli': false,
              'cursor_cli': false,
              'trae_cli': true,
            },
          },
        ],
      },
      raw: const {},
    );
  }
}

class _StaleAssistantApi extends _AssistantAssetsApi {
  _StaleAssistantApi(super.store);

  String groundedPrompt = '';

  Never _stale() => throw const MobileApiException(
        statusCode: 404,
        message: '旧服务端没有此接口',
        body: {},
      );

  @override
  Future<Map<String, Object?>> chat(
    String message, {
    String? sessionId,
    Map<String, Object?> context = const {},
  }) async =>
      _stale();

  @override
  Future<List<Map<String, Object?>>> keylessWebSearch(
    String query, {
    int maxResults = 5,
  }) async =>
      [
        {
          'title': '实时来源',
          'url': 'https://example.com/latest',
          'snippet': '刚刚发布的更新',
        },
      ];

  @override
  Future<String> streamChat(
    String message, {
    String? sessionId,
    int userId = 0,
    List<Map<String, String>> recentMessages = const [],
    Map<String, Object?> context = const {},
    void Function(String token)? onToken,
  }) async {
    groundedPrompt = message;
    return '基于实时来源的回答';
  }

  @override
  Future<Map<String, Object?>> memoryV2List({
    required String userId,
    String status = '',
  }) async =>
      _stale();

  @override
  Future<Map<String, Object?>> memoryV2Create({
    required String userId,
    required String key,
    required String value,
    String memoryType = 'preference',
  }) async =>
      _stale();
}

class _MetadataOfficeApi extends _AssistantAssetsApi {
  _MetadataOfficeApi(super.store);

  @override
  Future<Map<String, Object?>> runOfficeEmployee({
    required String employeeId,
    required String filePath,
    required String workspaceRoot,
  }) async =>
      {
        'success': true,
        'data': {
          'output_path': '/opt/fhd-full/outputs/document_full.json',
          'text_output_path': '/opt/fhd-full/outputs/document_full.txt',
          'output_schema': ['plain_text'],
        },
      };
}
