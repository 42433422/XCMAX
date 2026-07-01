import 'package:flutter/material.dart';

import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';

class MobileOnboardingScreen extends StatefulWidget {
  const MobileOnboardingScreen({
    super.key,
    this.repository,
    this.initialIndustries,
    this.onFinish,
  });

  final MobileRepository? repository;
  final List<OnboardingIndustry>? initialIndustries;
  final VoidCallback? onFinish;

  @override
  State<MobileOnboardingScreen> createState() => _MobileOnboardingScreenState();
}

class _MobileOnboardingScreenState extends State<MobileOnboardingScreen> {
  late final MobileRepository _repository;
  late Future<List<OnboardingIndustry>> _industriesFuture;
  var _step = 0;
  var _selectedIndustryId = '';
  var _status = '等待检查行业基础能力状态';
  var _working = false;

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _industriesFuture = _loadIndustries();
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
              title: '启动配置',
              actions: [
                IconButton(
                  onPressed: _reload,
                  icon: const Icon(Icons.refresh),
                  tooltip: '刷新',
                  color: colors.textPrimary,
                ),
              ],
            ),
            Expanded(
              child: FutureBuilder<List<OnboardingIndustry>>(
                future: _industriesFuture,
                builder: (context, snapshot) {
                  final industries =
                      snapshot.data ?? widget.initialIndustries ?? const [];
                  if (_selectedIndustryId.isEmpty && industries.isNotEmpty) {
                    _selectedIndustryId = industries.first.id;
                  }
                  final selected = _selectedIndustry(industries);
                  final selectedTitle =
                      selected?.title ?? _selectedIndustryId.ifEmpty('通用');
                  return ListView(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 20,
                      vertical: 16,
                    ),
                    children: [
                      StepRail(current: _step),
                      const SizedBox(height: 14),
                      if (_step == 0)
                        _IntroStep(
                          onNext: () => setState(() => _step = 1),
                          onFinish: _finish,
                        )
                      else if (_step == 1)
                        _IndustryStep(
                          industries: industries,
                          selectedIndustryId: _selectedIndustryId,
                          onSelect: (id) {
                            setState(() => _selectedIndustryId = id);
                          },
                          onNext: _selectIndustry,
                          onReload: _reload,
                        )
                      else
                        _CapabilityStep(
                          industryTitle: selectedTitle,
                          status: _status,
                          working: _working,
                          onInstall: _bootstrapIndustry,
                          onReload: _reload,
                          onNext: _finish,
                        ),
                    ],
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<List<OnboardingIndustry>> _loadIndustries() async {
    if (widget.initialIndustries != null) return widget.initialIndustries!;
    return _repository.loadOnboardingIndustries();
  }

  OnboardingIndustry? _selectedIndustry(List<OnboardingIndustry> industries) {
    for (final industry in industries) {
      if (industry.id == _selectedIndustryId) return industry;
    }
    return null;
  }

  void _reload() {
    setState(() {
      _industriesFuture = _loadIndustries();
    });
  }

  Future<void> _selectIndustry() async {
    if (_selectedIndustryId.trim().isEmpty) return;
    setState(() => _working = true);
    try {
      await _repository.selectOnboardingIndustry(_selectedIndustryId);
      if (!mounted) return;
      setState(() {
        _status = '行业已绑定到当前账号';
        _step = 2;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _status = error.toString());
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }

  Future<void> _bootstrapIndustry() async {
    setState(() => _working = true);
    try {
      final result = await _repository.bootstrapIndustry(_selectedIndustryId);
      if (mounted) setState(() => _status = result);
    } catch (error) {
      if (mounted) setState(() => _status = error.toString());
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }

  void _finish() {
    widget.onFinish?.call();
    if (widget.onFinish == null) Navigator.of(context).maybePop();
  }
}

class StepRail extends StatelessWidget {
  const StepRail({super.key, required this.current});

  final int current;

  static const titles = ['认识XC', '行业定型', '补基础线'];

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Row(
      children: [
        for (var index = 0; index < titles.length; index += 1) ...[
          Expanded(
            child: Container(
              height: 34,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: index <= current
                    ? colors.brandContainer
                    : colors.surfaceHigh,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                titles[index],
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  color: index <= current ? colors.brand : colors.textSecondary,
                  fontSize: 13,
                  height: 1.31,
                  fontWeight:
                      index == current ? FontWeight.w600 : FontWeight.w400,
                  letterSpacing: 0,
                ),
              ),
            ),
          ),
          if (index < titles.length - 1) const SizedBox(width: 8),
        ],
      ],
    );
  }
}

class _IntroStep extends StatelessWidget {
  const _IntroStep({
    required this.onNext,
    required this.onFinish,
  });

  final VoidCallback onNext;
  final VoidCallback onFinish;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        const _FlowBlock(
          icon: Icons.cloud_done,
          title: '移动端将独立连接 XCAGI 宿主',
          body: '注册或登录后先同步账号、市场令牌和企业会话，再按行业装齐基础能力。',
        ),
        const SizedBox(height: 14),
        SizedBox(
          width: double.infinity,
          child: FilledButton(onPressed: onNext, child: const Text('开始行业配置')),
        ),
        SizedBox(
          width: double.infinity,
          child:
              OutlinedButton(onPressed: onFinish, child: const Text('稍后进入应用')),
        ),
      ],
    );
  }
}

class _IndustryStep extends StatelessWidget {
  const _IndustryStep({
    required this.industries,
    required this.selectedIndustryId,
    required this.onSelect,
    required this.onNext,
    required this.onReload,
  });

  final List<OnboardingIndustry> industries;
  final String selectedIndustryId;
  final ValueChanged<String> onSelect;
  final VoidCallback onNext;
  final VoidCallback onReload;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        const _FlowBlock(
          icon: Icons.extension,
          title: '选择行业',
          body: '这里使用后端行业目录，和桌面端的行业筛选来源一致。',
        ),
        const SizedBox(height: 14),
        if (industries.isEmpty) ...[
          const _StatusBlock('行业目录暂未同步，刷新后继续。'),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton(
                onPressed: onReload, child: const Text('刷新行业目录')),
          ),
        ] else ...[
          for (final industry in industries.take(8)) ...[
            _SelectableIndustryRow(
              industry: industry,
              selected: industry.id == selectedIndustryId,
              onTap: () => onSelect(industry.id),
            ),
            const SizedBox(height: 8),
          ],
        ],
        SizedBox(
          width: double.infinity,
          child: FilledButton(
            onPressed: selectedIndustryId.trim().isEmpty ? null : onNext,
            child: const Text('继续'),
          ),
        ),
      ],
    );
  }
}

class _CapabilityStep extends StatelessWidget {
  const _CapabilityStep({
    required this.industryTitle,
    required this.status,
    required this.working,
    required this.onInstall,
    required this.onReload,
    required this.onNext,
  });

  final String industryTitle;
  final String status;
  final bool working;
  final VoidCallback onInstall;
  final VoidCallback onReload;
  final VoidCallback onNext;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        _FlowBlock(
          icon: Icons.check_circle,
          title: '装齐 $industryTitle 基础包',
          body: '移动端直接调用市场安装接口，补齐宿主基础包和行业种子能力。',
        ),
        const SizedBox(height: 14),
        _StatusBlock(status.trim().isEmpty ? '等待检查行业基础能力状态' : status),
        SizedBox(
          width: double.infinity,
          child: FilledButton(
            onPressed: working ? null : onInstall,
            child: Text(working ? '处理中…' : '装齐基础包'),
          ),
        ),
        SizedBox(
          width: double.infinity,
          child: OutlinedButton(onPressed: onReload, child: const Text('重新检查')),
        ),
        SizedBox(
          width: double.infinity,
          child: FilledButton(onPressed: onNext, child: const Text('进入应用')),
        ),
      ],
    );
  }
}

class _FlowBlock extends StatelessWidget {
  const _FlowBlock({
    required this.icon,
    required this.title,
    required this.body,
  });

  final IconData icon;
  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: colors.surfaceHigh,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 24, color: colors.textPrimary),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: TextStyle(
                    color: colors.textPrimary,
                    fontSize: 17,
                    height: 1.29,
                    fontWeight: FontWeight.w600,
                    letterSpacing: 0,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  body,
                  style: TextStyle(
                    color: colors.textSecondary,
                    fontSize: 15,
                    height: 1.4,
                    letterSpacing: 0,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _SelectableIndustryRow extends StatelessWidget {
  const _SelectableIndustryRow({
    required this.industry,
    required this.selected,
    required this.onTap,
  });

  final OnboardingIndustry industry;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: selected ? colors.brandContainer : colors.surfaceHigh,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              industry.title,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: colors.textPrimary,
                fontSize: 15,
                height: 1.4,
                fontWeight: FontWeight.w600,
                letterSpacing: 0,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              industry.subtitle.ifEmpty('装齐 ${industry.title} 基础能力'),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: colors.textSecondary,
                fontSize: 13,
                height: 1.31,
                letterSpacing: 0,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _StatusBlock extends StatelessWidget {
  const _StatusBlock(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 14),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: colors.surfaceHigh,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        text,
        style: TextStyle(
          color: colors.textPrimary,
          fontSize: 15,
          height: 1.4,
          letterSpacing: 0,
        ),
      ),
    );
  }
}

extension on String {
  String ifEmpty(String fallback) => trim().isEmpty ? fallback : trim();
}
