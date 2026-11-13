import 'package:flutter/material.dart';
import 'package:lpinyin/lpinyin.dart';

import '../../data/ai_employee_profile.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../policy/avatar_policy.dart';
import '../../theme/app_theme.dart';
import '../../theme/message_avatar_layout.dart';
import '../../widgets/app_avatar.dart';
import 'employee_profile_screen.dart';

class AiEmployeesScreen extends StatefulWidget {
  const AiEmployeesScreen({super.key, this.repository, this.onBack});

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
                ),
                if (!hasEmployees)
                  const Expanded(child: _AiEmployeeEmptyState())
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
                        : _AiEmployeeIndexedList(
                            employees: employees,
                            repository: _repository,
                            showIndex: _query.trim().isEmpty,
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

  List<AiEmployeeProfile> _filteredEmployees(List<AiEmployeeProfile> source) {
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
  });

  final int count;
  final VoidCallback? onBack;
  final VoidCallback onRefresh;

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
                  hintText: '查找员工',
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

const _aiEmployeeIndexRowHeight = 64.0;
const _aiEmployeeIndexSectionHeight = 28.0;

class _AiEmployeeIndexedList extends StatefulWidget {
  const _AiEmployeeIndexedList({
    required this.employees,
    required this.repository,
    required this.showIndex,
  });

  final List<AiEmployeeProfile> employees;
  final MobileRepository repository;
  final bool showIndex;

  @override
  State<_AiEmployeeIndexedList> createState() => _AiEmployeeIndexedListState();
}

class _AiEmployeeIndexedListState extends State<_AiEmployeeIndexedList> {
  final _scrollController = ScrollController();
  String _activeLetter = '';

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final groups = _groupByInitial(widget.employees);
    final entries = <Object>[];
    final offsets = <String, double>{};
    var offset = 0.0;
    for (final entry in groups.entries) {
      offsets[entry.key] = offset;
      entries.add(entry.key);
      offset += _aiEmployeeIndexSectionHeight;
      entries.addAll(entry.value);
      offset += entry.value.length * _aiEmployeeIndexRowHeight;
    }

    final list = ListView.builder(
      controller: _scrollController,
      padding: EdgeInsets.only(right: widget.showIndex ? 24 : 0),
      itemCount: entries.length,
      itemBuilder: (context, index) {
        final entry = entries[index];
        if (entry is String) {
          return _AiEmployeeIndexSection(letter: entry);
        }
        return _AiEmployeeRow(
          employee: entry as AiEmployeeProfile,
          repository: widget.repository,
        );
      },
    );

    if (!widget.showIndex || groups.isEmpty) return list;

    return Stack(
      children: [
        Positioned.fill(child: list),
        Positioned(
          top: 8,
          bottom: 8,
          right: 0,
          child: _AiEmployeeIndexBar(
            letters: groups.keys.toList(growable: false),
            activeLetter: _activeLetter,
            onSelected: (letter) {
              setState(() => _activeLetter = letter);
              _jumpTo(offsets[letter] ?? 0);
            },
          ),
        ),
      ],
    );
  }

  void _jumpTo(double offset) {
    if (!_scrollController.hasClients) return;
    _scrollController.animateTo(
      offset.clamp(0.0, _scrollController.position.maxScrollExtent),
      duration: const Duration(milliseconds: 180),
      curve: Curves.easeOut,
    );
  }
}

Map<String, List<AiEmployeeProfile>> _groupByInitial(
  List<AiEmployeeProfile> employees,
) {
  final groups = <String, List<AiEmployeeProfile>>{};
  for (final employee in employees) {
    groups.putIfAbsent(_pinyinInitial(employee.name), () => []).add(employee);
  }
  final letters = groups.keys.toList()
    ..sort((a, b) {
      if (a == '#') return 1;
      if (b == '#') return -1;
      return a.compareTo(b);
    });
  return {for (final letter in letters) letter: groups[letter]!};
}

String _pinyinInitial(String name) {
  final trimmed = name.trim();
  if (trimmed.isEmpty) return '#';
  final first = trimmed.substring(0, 1);
  final upper = first.toUpperCase();
  if (upper.codeUnitAt(0) >= 0x41 && upper.codeUnitAt(0) <= 0x5A) return upper;
  final short = PinyinHelper.getShortPinyin(first).trim().toUpperCase();
  if (short.isEmpty) return '#';
  final initial = short.substring(0, 1);
  if (initial.codeUnitAt(0) >= 0x41 && initial.codeUnitAt(0) <= 0x5A) {
    return initial;
  }
  return '#';
}

class _AiEmployeeIndexSection extends StatelessWidget {
  const _AiEmployeeIndexSection({required this.letter});

  final String letter;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      height: _aiEmployeeIndexSectionHeight,
      color: colors.page,
      alignment: Alignment.centerLeft,
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Text(
        letter,
        style: TextStyle(
          color: colors.textSecondary,
          fontSize: 12,
          fontWeight: FontWeight.w600,
          height: 1.2,
          letterSpacing: 0,
        ),
      ),
    );
  }
}

class _AiEmployeeIndexBar extends StatelessWidget {
  const _AiEmployeeIndexBar({
    required this.letters,
    required this.activeLetter,
    required this.onSelected,
  });

  final List<String> letters;
  final String activeLetter;
  final ValueChanged<String> onSelected;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return LayoutBuilder(
      builder: (context, constraints) {
        void selectAt(double dy) {
          if (letters.isEmpty) return;
          final slot = constraints.maxHeight / letters.length;
          final index = (dy / slot).floor().clamp(0, letters.length - 1);
          final letter = letters[index];
          if (letter != activeLetter) onSelected(letter);
        }

        return GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTapDown: (details) => selectAt(details.localPosition.dy),
          onVerticalDragStart: (details) => selectAt(details.localPosition.dy),
          onVerticalDragUpdate: (details) => selectAt(details.localPosition.dy),
          child: Container(
            width: 26,
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Column(
              children: [
                for (final letter in letters)
                  Expanded(
                    child: Center(
                      child: Text(
                        letter,
                        style: TextStyle(
                          color: letter == activeLetter
                              ? colors.brand
                              : colors.textSecondary,
                          fontSize: 10,
                          height: 1,
                          fontWeight: letter == activeLetter
                              ? FontWeight.w700
                              : FontWeight.w500,
                          letterSpacing: 0,
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        );
      },
    );
  }
}

class _AiEmployeeRow extends StatelessWidget {
  const _AiEmployeeRow({required this.employee, required this.repository});

  final AiEmployeeProfile employee;
  final MobileRepository repository;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return SizedBox(
      height: _aiEmployeeIndexRowHeight,
      child: Material(
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
          child: Container(
            decoration: BoxDecoration(
              border: Border(
                bottom: BorderSide(color: colors.divider, width: 0.5),
              ),
            ),
            padding: const EdgeInsets.symmetric(
              horizontal: MessageAvatarLayout.employeePickerRowHorizontalPadding,
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
                  child: Text(
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
                ),
                Icon(Icons.chevron_right, size: 20, color: colors.textSecondary),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _AiEmployeeEmptyState extends StatelessWidget {
  const _AiEmployeeEmptyState();

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
              child: Icon(Icons.auto_awesome, size: 34, color: colors.brand),
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
