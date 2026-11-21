import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late HttpServer server;
  late HttpClient http;
  late MobileApiClient api;
  final methods = <String>[];
  Map<String, Object?> receipt = {};
  String? doneState;
  setUp(() async {
    methods.clear();
    doneState = null;
    receipt = {'turn_id': 'original-turn', 'run_id': 'original-run',
      'status': 'completed', 'message': '已核对原结果'};
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    http = HttpClient();
    api = MobileApiClient(
        config: MobileApiConfig(baseUrl: 'http://127.0.0.1:${server.port}/'),
        sessionStore: MemoryMobileSessionStore(), httpClient: http);
    server.listen((request) async {
      methods.add(request.method);
      if (request.method == 'POST') {
        final body = jsonDecode(await utf8.decodeStream(request)) as Map;
        final context = body['context'] ?? body;
        expect(context['turn_id'], 'original-turn');
        expect(context['idempotency_key'], 'original-turn');
        request.response.headers.contentType = ContentType('text', 'event-stream');
        request.response.write('data: {"type":"token","text":"partial"}\n\n');
        if (doneState != null) {
          request.response.write('data: ${jsonEncode({'type': 'done', 'result': {
            'success': true, 'execution_state': doneState, 'run_id': 'original-run', 'response': '尚未完成'
          }})}\n\n');
        }
      } else {
        expect(request.uri.path, '/api/conversations/session-1');
        expect(request.uri.queryParameters['turn_id'], 'original-turn');
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({'success': true, 'turn_receipt': receipt}));
      }
      await request.response.close();
    });
  });
  tearDown(() async {
    api.dispose();
    http.close(force: true);
    await server.close(force: true);
  });

  test('EOF reads the matching original turn once without another POST', () async {
    expect(await api.streamChat('写入订单', sessionId: 'session-1',
        idempotencyKey: 'original-turn'), '已核对原结果');
    expect(methods, ['POST', 'GET']);
  });

  test('manual reconciliation only reads the original turn', () async {
    expect(await api.streamChat('写入订单', sessionId: 'session-1',
        idempotencyKey: 'original-turn', resumeOnly: true), '已核对原结果');
    expect(methods, ['GET']);
  });

  test('employee EOF reads its original stable turn without resending', () async {
    expect(await api.streamEmployeeChat(message: '执行员工任务', employeeId: 'worker',
        modId: 'mod-1', conversationId: 'session-1', idempotencyKey: 'original-turn'), '已核对原结果');
    expect(methods, ['POST', 'GET']);
  });

  for (final status in ['queued', 'waiting_approval', 'waiting_input', 'waiting_auth', 'blocked', 'unknown']) {
    test('done delivery does not mean task $status completed', () async {
      doneState = status;
      await expectLater(api.streamChat('执行', sessionId: 'session-1', idempotencyKey: 'original-turn'),
          throwsA(isA<MobileApiException>().having((error) => error.errorCode, 'code', 'CHAT_RECEIPT_PENDING')));
      expect(methods, ['POST']);
    });
  }

  test('a server-authoritative durable text turn does not require a tool run', () async {
    receipt.remove('run_id');
    receipt.addAll({'receipt_kind': 'turn', 'durable': true});
    expect(await api.streamChat('你好', sessionId: 'session-1',
        idempotencyKey: 'original-turn', resumeOnly: true), '已核对原结果');
    expect(methods, ['GET']);
  });

  test('attachment reconciliation does not need old upload credentials', () async {
    expect(await api.streamAttachmentChat('', conversationId: 'session-1',
        idempotencyKey: 'original-turn', resumeOnly: true, attachments: const [
          MobileChatAttachment(uploadId: 'expired', name: 'report.csv',
              baseUrl: 'https://old-upload.example/', authGeneration: -1, conversationId: 'old-session'),
        ]), '已核对原结果');
    expect(methods, ['GET']);
  });

  for (final envelope in ['data', 'result', 'payload', 'business_result']) {
    test('inner $envelope pending overrides outer completed', () {
      expect(() => chatReceiptText({'execution_state': 'completed', 'success': true,
        envelope: {'execution_state': 'running', 'requires_reconciliation': true}}, 'original-turn', '不可冒充成功'),
        throwsA(isA<MobileApiException>().having((error) => error.body['execution_state'], 'state', 'unknown')));
    });
  }

  test('execution identity without a terminal state never confirms completion', () {
    expect(() => chatReceiptText({'success': true, 'run_id': 'original-run', 'response': '已提交'},
        'original-turn', ''), throwsA(isA<MobileApiException>().having((error) => error.errorCode, 'code', 'CHAT_RECEIPT_PENDING')));
    expect(chatReceiptText({'response': '纯文本回复'}, 'text-turn', ''), '纯文本回复');
  });

  for (final mismatch in ['other-turn', 'unknown', 'running', 'contradictory', 'missing-run']) {
    test('does not complete or replay $mismatch receipt', () async {
      if (mismatch == 'other-turn') {
        receipt['turn_id'] = mismatch;
      } else if (mismatch == 'contradictory') {
        receipt['requires_reconciliation'] = true;
      } else if (mismatch == 'missing-run') {
        receipt.remove('run_id');
      } else {
        receipt['status'] = mismatch;
      }
      await expectLater(api.streamChat('写入订单', sessionId: 'session-1',
          idempotencyKey: 'original-turn'), throwsA(isA<MobileApiException>()
          .having((error) => error.errorCode, 'code', 'CHAT_RECEIPT_PENDING')));
      expect(methods, ['POST', 'GET']);
    });
  }
}
