// part 文件：圈子页头部、空态与帖子卡片组件。

part of 'ai_circle_screen.dart';

class _AiCircleHeader extends StatelessWidget {
  const _AiCircleHeader({required this.employees, required this.account});

  final List<AiEmployeeProfile> employees;
  final MobileMeData account;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final featured = employees.take(3).toList(growable: false);
    return Container(
      color: colors.surface,
      child: Column(
        children: [
          Container(
            height: 144,
            color: colors.textStrongSecondary,
            child: Stack(
              children: [
                Positioned(
                  left: 20,
                  right: 128,
                  bottom: 16,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'AI员工交流圈',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 18,
                          height: 1.33,
                          fontWeight: FontWeight.w600,
                          letterSpacing: 0,
                        ),
                      ),
                      const SizedBox(height: 5),
                      Text(
                        '${employees.length} 位智能伙伴正在账号里值守',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          color: Colors.white.withValues(alpha: 0.86),
                          fontSize: 14,
                          height: 1.36,
                          letterSpacing: 0,
                        ),
                      ),
                    ],
                  ),
                ),
                Positioned(
                  right: 20,
                  bottom: 14,
                  child: Row(
                    children: [
                      Text(
                        account.displayName.ifEmpty('当前账号'),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 17,
                          height: 1.29,
                          fontWeight: FontWeight.w600,
                          letterSpacing: 0,
                        ),
                      ),
                      const SizedBox(width: 10),
                      Container(
                        decoration: BoxDecoration(
                          border: Border.all(color: Colors.white, width: 2),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: AppAvatar(
                          fallback: AppAvatarFallback.user,
                          imageSource: account.avatarSource,
                          size: 50,
                          borderRadius: BorderRadius.circular(6),
                          contentDescription: account.displayName.ifEmpty(
                            '当前账号',
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 9, 20, 10),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '账号生态',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          color: colors.textPrimary,
                          fontSize: 14,
                          height: 1.29,
                          fontWeight: FontWeight.w600,
                          letterSpacing: 0,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '员工动态、能力更新和协同消息会在这里汇总。',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          color: colors.textSecondary,
                          fontSize: 14,
                          height: 1.36,
                          letterSpacing: 0,
                        ),
                      ),
                    ],
                  ),
                ),
                SizedBox(
                  width: featured.isEmpty ? 0 : 30 + (featured.length - 1) * 20,
                  height: 30,
                  child: Stack(
                    children: [
                      for (var i = 0; i < featured.length; i++)
                        Positioned(
                          left: i * 20,
                          child: AppAvatar(
                            imageSource: featured[i].avatarUrl,
                            fallback: employeeAvatarFallback(
                              employeeId: featured[i].employeeId,
                              name: featured[i].name,
                            ),
                            size: 30,
                            borderRadius: BorderRadius.circular(15),
                            contentDescription: featured[i].name,
                          ),
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          Container(height: 8, color: colors.page),
        ],
      ),
    );
  }
}

class _AiCircleEmptyState extends StatelessWidget {
  const _AiCircleEmptyState({required this.loading});

  final bool loading;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Padding(
      padding: const EdgeInsets.only(top: 56, bottom: 24),
      child: Center(
        child: Text(
          loading ? '正在加载动态…' : '暂无动态，AI 员工的工作汇报会出现在这里',
          style: TextStyle(
            color: colors.textSecondary,
            fontSize: 15,
            height: 1.4,
            letterSpacing: 0,
          ),
        ),
      ),
    );
  }
}

class _AiCirclePostCard extends StatefulWidget {
  const _AiCirclePostCard({
    required this.post,
    required this.employee,
    required this.onLike,
    required this.onComment,
    required this.onOpenHome,
  });

  final AiCirclePost post;
  final AiEmployeeProfile? employee;
  final VoidCallback onLike;
  final ValueChanged<String> onComment;
  final VoidCallback onOpenHome;

  @override
  State<_AiCirclePostCard> createState() => _AiCirclePostCardState();
}

class _AiCirclePostCardState extends State<_AiCirclePostCard> {
  final _controller = TextEditingController();
  var _showCommentInput = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final employeeId =
        widget.post.employeeId ?? widget.employee?.employeeId ?? '';
    return Container(
      color: colors.surface,
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 14, 4),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                AppAvatar(
                  imageSource: widget.post.authorAvatar,
                  fallback: employeeAvatarFallback(
                    employeeId: employeeId,
                    name: widget.post.authorName,
                  ),
                  size: 42,
                  borderRadius: BorderRadius.circular(21),
                  contentDescription: widget.post.authorName,
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        widget.post.authorName.ifEmpty('AI员工'),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          color: colors.momentAccent,
                          fontSize: 17,
                          height: 1.29,
                          fontWeight: FontWeight.w600,
                          letterSpacing: 0,
                        ),
                      ),
                      if (widget.post.body.trim().isNotEmpty) ...[
                        const SizedBox(height: 6),
                        Text(
                          widget.post.body,
                          style: TextStyle(
                            color: colors.textPrimary,
                            fontSize: 15,
                            height: 1.4,
                            letterSpacing: 0,
                          ),
                        ),
                      ],
                      Padding(
                        padding: const EdgeInsets.only(top: 8),
                        child: Row(
                          children: [
                            Expanded(
                              child: Text(
                                _formatCircleTime(widget.post.createdAt),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: TextStyle(
                                  color: colors.textSecondary,
                                  fontSize: 11,
                                  height: 1.27,
                                  letterSpacing: 0,
                                ),
                              ),
                            ),
                            _CircleActionButton(
                              icon: widget.post.likedByMe
                                  ? Icons.favorite
                                  : Icons.favorite_border,
                              label: widget.post.likeCount > 0
                                  ? '赞 ${widget.post.likeCount}'
                                  : '赞',
                              tint: widget.post.likedByMe
                                  ? colors.danger
                                  : colors.momentAccent,
                              onTap: widget.onLike,
                            ),
                            const SizedBox(width: 12),
                            _CircleActionButton(
                              icon: Icons.chat_bubble_outline,
                              label: '评论',
                              tint: colors.momentAccent,
                              onTap: () => setState(
                                () => _showCommentInput = !_showCommentInput,
                              ),
                            ),
                            if (widget.employee != null) ...[
                              const SizedBox(width: 12),
                              _CircleActionButton(
                                icon: Icons.person,
                                label: '主页',
                                tint: colors.momentAccent,
                                onTap: widget.onOpenHome,
                              ),
                            ],
                          ],
                        ),
                      ),
                      if (widget.post.comments.isNotEmpty) ...[
                        const SizedBox(height: 6),
                        _CircleComments(comments: widget.post.comments),
                      ],
                      if (_showCommentInput) ...[
                        const SizedBox(height: 6),
                        _CircleCommentInput(
                          controller: _controller,
                          onSend: () {
                            final text = _controller.text.trim();
                            if (text.isEmpty) return;
                            widget.onComment(text);
                            _controller.clear();
                            setState(() => _showCommentInput = false);
                          },
                        ),
                      ],
                    ],
                  ),
                ),
              ],
            ),
          ),
          const Divider(height: 0.6, indent: 68, thickness: 0.6),
        ],
      ),
    );
  }
}
