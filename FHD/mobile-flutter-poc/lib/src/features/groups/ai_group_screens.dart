import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../api/mobile_models.dart' show MobileMeData;
import '../../data/ai_employee_profile.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../models/conversation.dart';
import '../../policy/avatar_policy.dart';
import '../../policy/pinned_ids.dart';
import '../../platform/android_record_audio_permission.dart';
import '../../theme/app_theme.dart';
import '../../theme/message_avatar_layout.dart';
import '../../widgets/app_avatar.dart';
import '../../widgets/group_grid_avatar.dart';
import '../../widgets/we_ui.dart';
import '../voice/voice_input_sheet.dart';

// 按职责拆分为 part 文件：候选数据、各页面 State 与 UI 组件组。
part 'ai_group_screens_data.part.dart';
part 'ai_group_screens_list.part.dart';
part 'ai_group_screens_chat.part.dart';
part 'ai_group_screens_chat_state.part.dart';
part 'ai_group_screens_create.part.dart';
part 'ai_group_screens_bubble.part.dart';
part 'ai_group_screens_widgets.part.dart';
part 'ai_group_screens_tiles.part.dart';
part 'ai_group_screens_sheets.part.dart';

enum GroupWorkMode {
  dispatch('任务派工', '输入要派发的任务', Icons.groups),
  followup('验收回访', '可补充要回访哪一单', Icons.check),
  bugfix('问题修复', '输入要修复的问题', Icons.refresh);

  const GroupWorkMode(this.label, this.placeholder, this.icon);

  final String label;
  final String placeholder;
  final IconData icon;
}

class AiGroupListScreen extends StatefulWidget {
  const AiGroupListScreen({
    super.key,
    this.repository,
    this.initialGroups = const [],
  });

  final MobileRepository? repository;
  final List<AiGroupConversation> initialGroups;

  @override
  State<AiGroupListScreen> createState() => _AiGroupListScreenState();
}

class AiGroupChatScreen extends StatefulWidget {
  const AiGroupChatScreen({
    super.key,
    required this.initialGroup,
    this.repository,
  });

  final AiGroupConversation initialGroup;
  final MobileRepository? repository;

  @override
  State<AiGroupChatScreen> createState() => _AiGroupChatScreenState();
}

class AiGroupCreateScreen extends StatefulWidget {
  const AiGroupCreateScreen({super.key, this.repository});

  final MobileRepository? repository;

  @override
  State<AiGroupCreateScreen> createState() => _AiGroupCreateScreenState();
}
