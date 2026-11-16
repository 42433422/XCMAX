import 'dart:async';

import 'package:flutter/material.dart';

import '../../api/mobile_models.dart';
import '../../data/ai_employee_profile.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../policy/mobile_error_policy.dart';
import '../../policy/avatar_policy.dart';
import '../../theme/app_theme.dart';
import '../../widgets/app_avatar.dart';
import '../../widgets/we_ui.dart';
import '../contacts/employee_profile_screen.dart';

part 'ai_circle_screen_widgets.part.dart';
part 'ai_circle_screen_comments.part.dart';

class AiCircleScreen extends StatefulWidget {
  const AiCircleScreen({super.key, this.repository});

  final MobileRepository? repository;

  @override
  State<AiCircleScreen> createState() => _AiCircleScreenState();
}

class _AiCircleScreenState extends State<AiCircleScreen> {
  late final MobileRepository _repository;
  _AiCircleData? _data;
  Object? _loadError;
  var _loading = true;
  var _loadRequest = 0;
  final _pendingLikes = <int, bool>{};

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    unawaited(_refresh());
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final data = _data ??
        _AiCircleData(
          account: MobileMeData.adminFallback(),
          employees: const [],
          posts: const [],
        );
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
              child: RefreshIndicator(
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
                    if (_loadError != null)
                      ListTile(
                        title:
                            Text(_data == null ? '动态加载失败' : '动态更新失败，已保留当前内容'),
                        subtitle: Text(mobileErrorText(_loadError!)),
                        trailing: TextButton(
                          onPressed: _loading ? null : _refresh,
                          child: const Text('重试'),
                        ),
                      ),
                    if (data.posts.isEmpty && _loadError == null)
                      _AiCircleEmptyState(
                        loading: _loading,
                      )
                    else
                      for (final post in data.posts)
                        _AiCirclePostCard(
                          key: ValueKey(post.id),
                          post: _withLike(post, _pendingLikes[post.id]),
                          employee: _employeeForPost(data.employees, post),
                          onLike: () => _toggleLike(post),
                          onComment: (text) => _addComment(post, text),
                          onOpenHome: () => _openEmployee(data.employees, post),
                        ),
                  ],
                ),
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
            (_) => _data?.employees ?? const <AiEmployeeProfile>[],
          ),
      _repository
          .loadMe()
          .catchError((_) => _data?.account ?? MobileMeData.adminFallback()),
      _repository.loadAiCirclePosts(),
    ]);
    return _AiCircleData(
      employees: results[0] as List<AiEmployeeProfile>,
      account: results[1] as MobileMeData,
      posts: results[2] as List<AiCirclePost>,
    );
  }

  Future<void> _refresh() async {
    if (!mounted) return;
    final request = ++_loadRequest;
    setState(() {
      _loading = true;
      _loadError = null;
    });
    try {
      final data = await _load();
      if (!mounted || request != _loadRequest) return;
      setState(() {
        _data = data;
        _loading = false;
      });
    } catch (error) {
      if (!mounted || request != _loadRequest) return;
      setState(() {
        _loadError = error;
        _loading = false;
      });
    }
  }

  AiCirclePost _withLike(AiCirclePost post, bool? liked) =>
      liked == null || liked == post.likedByMe
          ? post
          : post.copyWith(
              likedByMe: liked,
              likeCount: (post.likeCount + (liked ? 1 : -1)).clamp(0, 999999),
            );

  Future<void> _toggleLike(AiCirclePost post) async {
    if (_pendingLikes.containsKey(post.id)) return;
    final liked = !post.likedByMe;
    setState(() => _pendingLikes[post.id] = liked);
    try {
      await _repository.toggleAiCircleLike(post.id);
      if (!mounted) return;
      setState(() {
        _data = _data?.copyWith(posts: [
          for (final item in _data!.posts)
            item.id == post.id ? _withLike(item, liked) : item,
        ]);
        _pendingLikes.remove(post.id);
      });
      await _refresh();
    } catch (error) {
      if (mounted) {
        setState(() => _pendingLikes.remove(post.id));
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(mobileErrorText(error, fallback: '点赞失败')),
          ),
        );
      }
    }
  }

  Future<bool> _addComment(AiCirclePost post, String text) async {
    try {
      await _repository.addAiCircleComment(post.id, text);
      await _refresh();
      return true;
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(mobileErrorText(error, fallback: '评论失败')),
          ),
        );
      }
      return false;
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
