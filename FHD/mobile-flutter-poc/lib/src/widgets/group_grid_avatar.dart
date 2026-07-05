import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../models/conversation.dart';
import '../policy/avatar_policy.dart';
import '../theme/app_theme.dart';
import '../theme/message_avatar_layout.dart';
import 'app_avatar.dart';

class GroupGridAvatar extends StatelessWidget {
  const GroupGridAvatar({
    super.key,
    required this.members,
    this.size = MessageAvatarLayout.conversationAvatarSize,
  });

  final List<AiGroupMember> members;
  final double size;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    const gap = 1.5;
    final shown = members.take(9).toList(growable: false);
    final count = shown.length;
    final columns = count <= 1 ? 1 : (count <= 4 ? 2 : 3);
    final rows = count == 0 ? 1 : (count / columns).ceil();
    final cell = (size - gap * (columns + 1)) / columns;

    return ClipRRect(
      borderRadius: MessageAvatarLayout.conversationAvatarRadius,
      child: Container(
        width: size,
        height: size,
        color: colors.divider,
        alignment: Alignment.center,
        child: count == 0
            ? Icon(
                Icons.group,
                size: size * 0.52,
                color: colors.textTertiary,
              )
            : Padding(
                padding: const EdgeInsets.all(gap),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    for (var row = 0; row < rows; row++) ...[
                      Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          for (var column = 0; column < columns; column++) ...[
                            _GroupAvatarCell(
                              member: _memberAt(
                                shown,
                                row * columns + column,
                              ),
                              size: cell,
                            ),
                            if (column < columns - 1)
                              const SizedBox(width: gap),
                          ],
                        ],
                      ),
                      if (row < rows - 1) const SizedBox(height: gap),
                    ],
                  ],
                ),
              ),
      ),
    );
  }

  AiGroupMember? _memberAt(List<AiGroupMember> members, int index) {
    if (index < 0 || index >= math.min(members.length, 9)) return null;
    return members[index];
  }
}

class _GroupAvatarCell extends StatelessWidget {
  const _GroupAvatarCell({required this.member, required this.size});

  final AiGroupMember? member;
  final double size;

  @override
  Widget build(BuildContext context) {
    final member = this.member;
    if (member == null) return SizedBox.square(dimension: size);
    return AppAvatar(
      key: ValueKey('group_avatar_cell_${member.employeeId}'),
      imageSource: member.avatarUrl,
      fallback: aiGroupAvatarFallback(
        employeeId: member.employeeId,
        name: member.name,
        avatarKey: member.avatarKey,
      ),
      size: size,
      borderRadius: BorderRadius.circular(3),
      contentDescription: member.name,
    );
  }
}
