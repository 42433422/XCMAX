import 'package:flutter/material.dart';

import '../../data/mobile_repository.dart';
import '../../models/conversation.dart';
import '../../policy/pinned_ids.dart';
import '../chat/chat_screen.dart';

/// Existing OCR deep links use the same owned attachment flow as chat.
class OcrScreen extends StatelessWidget {
  const OcrScreen({super.key, this.repository});
  final MobileRepository? repository;

  @override
  Widget build(BuildContext context) => ChatScreen(
        repository: repository,
        conversation: const ConversationItem(
          id: PinnedIds.assistant,
          type: ConversationType.pinnedAssistant,
          title: '小C',
          subtitle: '',
          timestampText: '',
        ),
        initialMessages: const [],
      );
}
