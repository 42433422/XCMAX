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
      _repository.loadMe().catchError((_) => MobileMeData.adminFallback()),
      _repository.loadAiCirclePosts().catchError((_) => const <AiCirclePost>[]),
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
                        likeCount: (item.likeCount + (liked ? 1 : -1)).clamp(
                          0,
                          999999,
                        ),
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
            content: Text(mobileProductErrorMessage(error.toString(), '点赞失败')),
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
            content: Text(mobileProductErrorMessage(error.toString(), '评论失败')),
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
