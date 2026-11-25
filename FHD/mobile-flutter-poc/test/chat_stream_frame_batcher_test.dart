import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/features/chat/chat_stream_frame_batcher.dart';

void main() {
  testWidgets('100 tokens coalesce into one callback on the next frame', (tester) async {
    final deliveries = <String>[];
    final batcher = ChatStreamFrameBatcher((id, text) => deliveries.add('$id:$text'));
    for (var i = 0; i < 100; i++) {
      batcher.append('assistant-1', '字');
    }
    expect(deliveries, isEmpty);
    await tester.pump();
    expect(deliveries, ['assistant-1:NaN']);
    batcher.dispose();
  });

  testWidgets('stop flush keeps partial text without a second frame update', (tester) async {
    final deliveries = <String>[];
    final batcher = ChatStreamFrameBatcher((id, text) => deliveries.add('$id:$text'));
    batcher.append('assistant-1', 'partial');
    batcher.flushFor('assistant-1');
    expect(deliveries, ['assistant-1:partial']);
    await tester.pump();
    expect(deliveries, hasLength(1));
    batcher.dispose();
  });

  testWidgets('identity changes and cancellation drop stale tokens', (tester) async {
    final deliveries = <String>[];
    final batcher = ChatStreamFrameBatcher((id, text) => deliveries.add('$id:$text'));
    batcher.append('old', 'stale');
    batcher.append('new', 'fresh');
    batcher.clearFor('old');
    await tester.pump();
    expect(deliveries, ['new:fresh']);
    batcher.append('new', 'cancelled');
    batcher.dispose();
    await tester.pump();
    expect(deliveries, hasLength(1));
  });
}
