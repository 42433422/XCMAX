import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';

void main() {
  late HttpServer server;
  late HttpClient http;
  late MobileApiClient api;
  late String base;
  setUp(() async {
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    http = HttpClient();
    base = 'http://127.0.0.1:${server.port}/';
    api = MobileApiClient(
        config: const MobileApiConfig(baseUrl: 'http://unused.invalid/'),
        httpClient: http,
        sessionStore: MemoryMobileSessionStore(MobileSessionData(
            accessToken: 'owned-token',
            userId: 7,
            serverMode: 'lan',
            localBaseUrl: base)));
  });
  tearDown(() async {
    http.close(force: true);
    await server.close(force: true);
  });

  test('upload and chat use same selected backend, actor and conversation',
      () async {
    final requests = <String>[];
    server.listen((request) async {
      expect(request.headers.value('authorization'), 'Bearer owned-token');
      requests.add(request.uri.path);
      final raw = await utf8.decodeStream(request);
      if (request.uri.path.endsWith('upload')) {
        expect(request.headers.contentType!.mimeType, 'multipart/form-data');
        expect(raw, contains('name="file"; filename="report.csv"'));
        expect(raw, contains('a,b\n1,2'));
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({
          'success': true,
          'data': {'upload_id': 'owned-123'}
        }));
      } else {
        final body = jsonDecode(raw) as Map;
        expect(body['session_id'], 'pinned:assistant');
        expect(body['context']['attachment_upload_ids'], ['owned-123']);
        expect(body['context']['idempotency_key'], 'turn-test');
        request.response.headers.contentType =
            ContentType('text', 'event-stream', charset: 'utf-8');
        request.response
            .write('data: {"type":"done","result":{"response":"已读取"}}\n\n');
      }
      await request.response.close();
    });
    final attachment = await api.uploadChatAttachment(
        name: 'report.csv',
        bytes: utf8.encode('a,b\n1,2'),
        conversationId: 'pinned:assistant');
    expect(
        await api.streamAttachmentChat('分析附件',
            conversationId: 'pinned:assistant',
            idempotencyKey: 'turn-test',
            attachments: [attachment]),
        '已读取');
    expect(requests,
        ['/api/platform-shell/chat-office-file-upload', '/api/ai/chat/stream']);
  });

  test('interrupted attachment stream is not reported as completed', () async {
    server.listen((request) async {
      await request.drain<void>();
      request.response.headers.contentType =
          ContentType('text', 'event-stream', charset: 'utf-8');
      request.response.write('data: {"type":"token","text":"partial"}\n\n');
      await request.response.close();
    });
    final receipt = MobileChatAttachment(
        uploadId: 'owned',
        name: 'a.csv',
        baseUrl: base,
        authGeneration: api.authGeneration,
        conversationId: 'c');
    await expectLater(
        api.streamAttachmentChat('分析',
            conversationId: 'c',
            idempotencyKey: 'turn-test',
            attachments: [receipt]),
        throwsA(isA<MobileApiException>()
            .having((e) => e.errorCode, 'code', 'CHAT_RECEIPT_PENDING')));
  });

  test('untrusted upload without owned receipt is not accepted', () async {
    server.listen((request) async {
      await request.drain<void>();
      request.response.headers.contentType = ContentType.json;
      request.response.write(
          '{"success":true,"data":{"file_path":"uploads/a.xls","attachment_warning":"请另存为 XLSX"}}');
      await request.response.close();
    });
    await expectLater(
        api.uploadChatAttachment(
            name: 'a.xls', bytes: [1], conversationId: 'c'),
        throwsA(isA<MobileApiException>()
            .having((e) => e.message, 'message', '请另存为 XLSX')));
  });

  test(
      'expired session and mismatched conversation reject attachment before network',
      () async {
    final receipt = MobileChatAttachment(
        uploadId: 'owned',
        name: 'a.csv',
        baseUrl: base,
        authGeneration: api.authGeneration,
        conversationId: 'c');
    await expectLater(
        api.streamAttachmentChat('分析',
            conversationId: 'other',
            idempotencyKey: 'turn-test',
            attachments: [receipt]),
        throwsA(isA<MobileApiException>()));
    await api.clearActiveAuth();
    await expectLater(
        api.streamAttachmentChat('分析',
            conversationId: 'c',
            idempotencyKey: 'turn-test',
            attachments: [receipt]),
        throwsA(isA<MobileApiException>()));
  });

  test('logout while upload is in flight never returns old-account receipt',
      () async {
    server.listen((request) async {
      await request.drain<void>();
      await api.clearActiveAuth();
      request.response.headers.contentType = ContentType.json;
      request.response
          .write('{"success":true,"data":{"upload_id":"old-owner"}}');
      await request.response.close();
    });
    await expectLater(
        api.uploadChatAttachment(
            name: 'a.csv', bytes: [1], conversationId: 'c'),
        throwsA(isA<MobileApiException>()
            .having((e) => e.statusCode, 'status', 409)));
  });

  test('oversize file and too many references are rejected locally', () async {
    await expectLater(
        api.uploadChatAttachment(
            name: 'a.csv',
            bytes: List.filled(16 * 1024 * 1024 + 1, 0),
            conversationId: 'c'),
        throwsA(isA<MobileApiException>()
            .having((e) => e.statusCode, 'status', 413)));
    final receipt = MobileChatAttachment(
        uploadId: 'owned',
        name: 'a.csv',
        baseUrl: base,
        authGeneration: api.authGeneration,
        conversationId: 'c');
    await expectLater(
        api.streamAttachmentChat('分析',
            conversationId: 'c',
            idempotencyKey: 'turn-test',
            attachments: List.filled(5, receipt)),
        throwsA(isA<MobileApiException>()));
  });
}
