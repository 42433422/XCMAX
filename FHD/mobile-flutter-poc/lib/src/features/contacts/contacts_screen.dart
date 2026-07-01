import 'package:flutter/material.dart';

import '../../data/ai_employee_profile.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../policy/avatar_policy.dart';
import '../../theme/app_theme.dart';
import '../../theme/message_avatar_layout.dart';
import '../../widgets/app_avatar.dart';
import 'employee_profile_screen.dart';
import '../scan/scan_qr_screen.dart';

class AiEmployeesScreen extends StatefulWidget {
  const AiEmployeesScreen({
    super.key,
    this.repository,
    this.onBack,
  });

  final MobileRepository? repository;
  final VoidCallback? onBack;

  @override
  State<AiEmployeesScreen> createState() => _AiEmployeesScreenState();
}

class _AiEmployeesScreenState extends State<AiEmployeesScreen> {
  final _controller = TextEditingController();
  late final MobileRepository _repository;
  late Future<List<AiEmployeeProfile>> _employeesFuture;
  String _query = '';

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _employeesFuture = _repository.loadAiEmployees();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.page,
      body: SafeArea(
        bottom: false,
        child: FutureBuilder<List<AiEmployeeProfile>>(
          future: _employeesFuture,
          builder: (context, snapshot) {
            final source = snapshot.data ?? const <AiEmployeeProfile>[];
            final employees = _filteredEmployees(source);
            final hasEmployees = source.isNotEmpty;
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _AiEmployeeTopBar(
                  count: employees.length,
                  onBack: widget.onBack,
                  onRefresh: _refresh,
                  onScan: _openScan,
                ),
                if (!hasEmployees)
                  Expanded(child: _AiEmployeeEmptyState(onScan: _openScan))
                else ...[
                  _AiEmployeeSearchBar(
                    controller: _controller,
                    value: _query,
                    onChanged: (value) => setState(() => _query = value),
                    onClear: () {
                      _controller.clear();
                      setState(() => _query = '');
                    },
                  ),
                  Expanded(
                    child: employees.isEmpty
                        ? const _AiEmployeeSearchEmptyState()
                        : ListView.separated(
                            padding: EdgeInsets.zero,
                            itemBuilder: (context, index) {
                              final employee = employees[index];
                              return _AiEmployeeRow(
                                employee: employee,
                                repository: _repository,
                              );
                            },
                            separatorBuilder: (_, __) => const Divider(
                              indent: MessageAvatarLayout
                                  .employeePickerDividerStart,
                            ),
                            itemCount: employees.length,
                          ),
                  ),
                ],
              ],
            );
          },
        ),
      ),
    );
  }

  void _refresh() {
    setState(() {
      _employeesFuture = _repository.loadAiEmployees();
    });
  }

  void _openScan() {
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => ScanQrScreen(repository: _repository)),
    );
  }

  List<AiEmployeeProfile> _filteredEmployees(
    List<AiEmployeeProfile> source,
  ) {
    final keyword = _query.trim().toLowerCase();
    if (keyword.isEmpty) return source;
    return source.where((employee) {
      return employee.name.toLowerCase().contains(keyword) ||
          employee.modName.toLowerCase().contains(keyword) ||
          employee.employeeId.toLowerCase().contains(keyword);
    }).toList(growable: false);
  }
}

class _AiEmployeeTopBar extends StatelessWidget {
  const _AiEmployeeTopBar({
    required this.count,
    this.onBack,
    required this.onRefresh,
    required this.onScan,
  });

  final int count;
  final VoidCallback? onBack;
  final VoidCallback onRefresh;
  final VoidCallback onScan;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      height: 64,
      color: colors.surface,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 20, 0),
        child: Row(
          children: [
            if (onBack != null) ...[
              IconButton(
                onPressed: onBack,
                icon: const Icon(Icons.arrow_back, size: 26),
                color: colors.textPrimary,
                tooltip: '返回',
              ),
              const SizedBox(width: 4),
            ],
            Expanded(
              child: Text(
                key: const ValueKey('ai_employee_title'),
                count > 0 ? 'AI员工($count)' : 'AI员工',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 18,
                  height: 1.33,
                  fontWeight: FontWeight.w600,
                  letterSpacing: 0,
                ).copyWith(color: colors.textPrimary),
              ),
            ),
            IconButton(
              onPressed: onRefresh,
              icon: const Icon(Icons.refresh, size: 24),
              color: colors.textSecondary,
              tooltip: '刷新AI员工',
            ),
            IconButton(
              onPressed: onScan,
              icon: const Icon(Icons.qr_code_scanner, size: 24),
              color: colors.textSecondary,
              tooltip: '扫码绑定',
            ),
          ],
        ),
      ),
    );
  }
}

class _AiEmployeeSearchBar extends StatelessWidget {
  const _AiEmployeeSearchBar({
    required this.controller,
    required this.value,
    required this.onChanged,
    required this.onClear,
  });

  final TextEditingController controller;
  final String value;
  final ValueChanged<String> onChanged;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      color: colors.page,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      child: Container(
        key: const ValueKey('ai_employee_search_bar'),
        height: 38,
        decoration: BoxDecoration(
          color: colors.surfaceHigh,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: colors.divider, width: 0.5),
        ),
        child: Row(
          children: [
            const SizedBox(width: 14),
            Icon(Icons.search, size: 20, color: colors.textTertiary),
            const SizedBox(width: 8),
            Expanded(
              child: TextField(
                controller: controller,
                onChanged: onChanged,
                maxLines: 1,
                textAlignVertical: TextAlignVertical.center,
                style: TextStyle(
                  color: colors.textPrimary,
                  fontSize: 15,
                  height: 1.2,
                  letterSpacing: 0,
                ),
                decoration: InputDecoration(
                  isCollapsed: true,
                  border: InputBorder.none,
                  hintText: '查找会话或伙伴',
                  hintStyle: TextStyle(
                    color: colors.textTertiary,
                    fontSize: 15,
                    height: 1.2,
                    letterSpacing: 0,
                  ),
                ),
              ),
            ),
            if (value.isNotEmpty)
              Tooltip(
                message: '清除',
                child: GestureDetector(
                  onTap: onClear,
                  child: Container(
                    width: 18,
                    height: 18,
                    decoration: BoxDecoration(
                      color: colors.divider,
                      shape: BoxShape.circle,
                    ),
                    alignment: Alignment.center,
                    child: Text(
                      '×',
                      style: TextStyle(
                        color: colors.surface,
                        fontSize: 12,
                        height: 1,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 0,
                      ),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _AiEmployeeRow extends StatelessWidget {
  const _AiEmployeeRow({
    required this.employee,
    required this.repository,
  });

  final AiEmployeeProfile employee;
  final MobileRepository repository;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Material(
      color: colors.surface,
      child: InkWell(
        onTap: () {
          Navigator.of(context).push(
            MaterialPageRoute(
              builder: (_) => AiEmployeeProfileScreen(
                employee: employee,
                repository: repository,
              ),
            ),
          );
        },
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: MessageAvatarLayout.employeePickerRowHorizontalPadding,
            vertical: MessageAvatarLayout.employeePickerRowVerticalPadding,
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              AppAvatar(
                imageSource: employee.avatarUrl,
                fallback: employeeAvatarFallback(
                  employeeId: employee.employeeId,
                  name: employee.name,
                ),
                size: MessageAvatarLayout.employeePickerAvatarSize,
                borderRadius: MessageAvatarLayout.employeePickerAvatarRadius,
                contentDescription: employee.name,
              ),
              const SizedBox(
                width: MessageAvatarLayout.employeePickerAvatarTextGap,
              ),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      employee.name,
                      maxLines: 1,
                      overflow: TextOverflow.clip,
                      style: TextStyle(
                        color: colors.textPrimary,
                        fontSize: 16,
                        height: 1.38,
                        fontWeight: FontWeight.w500,
                        letterSpacing: 0,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      employee.summary,
                      maxLines: 1,
                      overflow: TextOverflow.clip,
                      style: TextStyle(
                        color: colors.textSecondary,
                        fontSize: 13,
                        height: 1.31,
                        fontWeight: FontWeight.w500,
                        letterSpacing: 0,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      employee.contactLine,
                      maxLines: 1,
                      overflow: TextOverflow.clip,
                      style: TextStyle(
                        color: colors.brand,
                        fontSize: 11,
                        height: 1.27,
                        fontWeight: FontWeight.w500,
                        letterSpacing: 0,
                      ),
                    ),
                  ],
                ),
              ),
              Icon(
                Icons.chevron_right,
                size: 20,
                color: colors.textSecondary,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _AiEmployeeEmptyState extends StatelessWidget {
  const _AiEmployeeEmptyState({
    required this.onScan,
  });

  final VoidCallback onScan;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 64,
              height: 64,
              decoration: BoxDecoration(
                color: colors.brand.withValues(alpha: 0.10),
                borderRadius: BorderRadius.circular(18),
              ),
              child: Icon(
                Icons.auto_awesome,
                size: 34,
                color: colors.brand,
              ),
            ),
            const SizedBox(height: 16),
            Text(
              '暂无 AI 员工',
              style: TextStyle(
                color: colors.textPrimary,
                fontSize: 15,
                height: 1.33,
                fontWeight: FontWeight.w500,
                letterSpacing: 0,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              '扫码绑定企业端或登录管理端后，员工会自动同步到这里。',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: colors.textSecondary,
                fontSize: 13,
                height: 1.38,
                letterSpacing: 0,
              ),
            ),
            const SizedBox(height: 24),
            ElevatedButton.icon(
              onPressed: onScan,
              icon: const Icon(Icons.qr_code_scanner, size: 18),
              label: const Text('扫码绑定'),
              style: ElevatedButton.styleFrom(
                backgroundColor: colors.brand,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _AiEmployeeSearchEmptyState extends StatelessWidget {
  const _AiEmployeeSearchEmptyState();

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Align(
      alignment: Alignment.topCenter,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 32),
        child: Text(
          '未找到匹配的 AI 员工',
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
