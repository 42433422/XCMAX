// part 文件：圈子互动按钮、评论区与数据工具。

part of 'ai_circle_screen.dart';

class _CircleActionButton extends StatelessWidget {
  const _CircleActionButton({
    required this.icon,
    required this.label,
    required this.tint,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final Color tint;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      borderRadius: BorderRadius.circular(8),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
          child: Row(
            children: [
              Icon(icon, size: 18, color: tint),
              const SizedBox(width: 4),
              Text(
                label,
                style: TextStyle(
                  color: tint,
                  fontSize: 13,
                  height: 1.31,
                  fontWeight: FontWeight.w500,
                  letterSpacing: 0,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _CircleComments extends StatelessWidget {
  const _CircleComments({required this.comments});

  final List<AiCircleComment> comments;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
      decoration: BoxDecoration(
        color: colors.replyBoxBg,
        borderRadius: BorderRadius.circular(4),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final comment in comments)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 1),
              child: Text(
                '${comment.authorName.ifEmpty('用户')}：${comment.body}',
                style: TextStyle(
                  color: colors.textSecondary,
                  fontSize: 14,
                  height: 1.36,
                  letterSpacing: 0,
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _CircleCommentInput extends StatelessWidget {
  const _CircleCommentInput({required this.controller, required this.onSend});

  final TextEditingController controller;
  final VoidCallback onSend;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Row(
      children: [
        Expanded(
          child: TextField(
            controller: controller,
            maxLines: 1,
            style: TextStyle(
              color: colors.textPrimary,
              fontSize: 15,
              height: 1.4,
              letterSpacing: 0,
            ),
            decoration: InputDecoration(
              hintText: '写评论…',
              hintStyle: TextStyle(
                color: colors.textSecondary,
                fontSize: 14,
                height: 1.36,
                letterSpacing: 0,
              ),
              isDense: true,
              contentPadding: const EdgeInsets.symmetric(
                horizontal: 12,
                vertical: 10,
              ),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(6),
              ),
            ),
          ),
        ),
        TextButton(onPressed: onSend, child: const Text('发送')),
      ],
    );
  }
}

class _AiCircleData {
  const _AiCircleData({
    required this.account,
    required this.employees,
    required this.posts,
  });

  final MobileMeData account;
  final List<AiEmployeeProfile> employees;
  final List<AiCirclePost> posts;

  _AiCircleData copyWith({List<AiCirclePost>? posts}) {
    return _AiCircleData(
      account: account,
      employees: employees,
      posts: posts ?? this.posts,
    );
  }
}

String _formatCircleTime(String iso) {
  if (iso.trim().isEmpty) return '';
  final cleaned = iso.replaceAll('T', ' ');
  return cleaned.length >= 16 ? cleaned.substring(0, 16) : cleaned;
}
