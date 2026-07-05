import 'package:flutter/material.dart';

import '../../api/mobile_models.dart';
import '../../data/ai_employee_profile.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../policy/android_error_policy.dart';
import '../../policy/avatar_policy.dart';
import '../../theme/app_theme.dart';
import '../../widgets/app_avatar.dart';
import '../../widgets/we_ui.dart';
import '../contacts/employee_profile_screen.dart';

class AiCircleScreen extends StatefulWidget {
  const AiCircleScreen({super.key, this.repository});

  final MobileRepository? repository;

  @override
  State<AiCircleScreen> createState() => _AiCircleScreenState();
}

class _AiCircleScreenState extends State<AiCircleScreen> {
  late final MobileRepository _repository;
  late Future<_AiCircleData> _future;

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _future = _load();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.page,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            WeTopBar(
              title: 'AI交流圈',
              showBack: true,
              onBack: () => Navigator.of(context).maybePop(),
            ),
            Expanded(
              child: FutureBuilder<_AiCircleData>(
                future: _future,
                builder: (context, snapshot) {
                  final data = snapshot.data ??
                      _AiCircleData(
                        account: MobileMeData.adminFallback(),
                        employees: const <AiEmployeeProfile>[],
                        posts: <AiCirclePost>[],
                      );
                  return RefreshIndicator(
                    color: colors.brand,
                    onRefresh: _refresh,
                    child: ListView(
                      physics: const AlwaysScrollableScrollPhysics(),
                      padding: const EdgeInsets.only(bottom: 24),
                      children: [
                        _AiCircleHeader(
                          employees: data.employees,
                          account: data.account,
                        ),
                        if (data.posts.isEmpty)
                          _AiCircleEmptyState(
                            loading: snapshot.connectionState ==
                                ConnectionState.waiting,
                          )
                        else
                          for (final post in data.posts)
                            _AiCirclePostCard(
                              post: post,
                              employee: _employeeForPost(data.employees, post),
                              onLike: () => _toggleLike(post),
                              onComment: (text) => _addComment(post, text),
                              onOpenHome: () =>
                                  _openEmployee(data.employees, post),
                            ),
                      ],
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<_AiCircleData> _load() async {
    final results = await Future.wait<Object>([
      _repository.loadAiEmployees().catchError(
            (_) => const <AiEmployeeProfile>[],
          ),
      _repository.loadMe().catchError(
            (_) => MobileMeData.adminFallback(),
          ),
      _repository.loadAiCirclePosts().catchError(
            (_) => const <AiCirclePost>[],
          ),
    ]);
    return _AiCircleData(
      employees: results[0] as List<AiEmployeeProfile>,
      account: results[1] as MobileMeData,
      posts: results[2] as List<AiCirclePost>,
    );
  }

  Future<void> _refresh() async {
    final future = _load();
    setState(() {
      _future = future;
    });
    await future;
  }

  Future<void> _toggleLike(AiCirclePost post) async {
    final data = await _future;
    final liked = !post.likedByMe;
    setState(() {
      _future = Future.value(
        data.copyWith(
          posts: data.posts
              .map(
                (item) => item.id == post.id
                    ? item.copyWith(
                        likedByMe: liked,
                        likeCount: (item.likeCount + (liked ? 1 : -1))
                            .clamp(0, 999999),
                      )
                    : item,
              )
              .toList(growable: false),
        ),
      );
    });
    try {
      await _repository.toggleAiCircleLike(post.id);
      await _refresh();
    } catch (error) {
      setState(() {
        _future = Future.value(data);
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(androidProductErrorMessage(error.toString(), '点赞失败')),
          ),
        );
      }
    }
  }

  Future<void> _addComment(AiCirclePost post, String text) async {
    try {
      await _repository.addAiCircleComment(post.id, text);
      await _refresh();
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(androidProductErrorMessage(error.toString(), '评论失败')),
          ),
        );
      }
    }
  }

  void _openEmployee(List<AiEmployeeProfile> employees, AiCirclePost post) {
    final employee = _employeeForPost(employees, post);
    if (employee == null) return;
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => AiEmployeeProfileScreen(
          employee: employee,
          repository: _repository,
        ),
      ),
    );
  }

  AiEmployeeProfile? _employeeForPost(
    List<AiEmployeeProfile> employees,
    AiCirclePost post,
  ) {
    final id = post.employeeId?.trim();
    if (id == null || id.isEmpty) return null;
    for (final employee in employees) {
      if (employee.employeeId == id) return employee;
    }
    return null;
  }
}

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
                        '${employees.length} 位智能伙伴正在企业账号里值守',
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
                          contentDescription:
                              account.displayName.ifEmpty('当前账号'),
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
                        '企业账号生态',
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
  const _CircleCommentInput({
    required this.controller,
    required this.onSend,
  });

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
