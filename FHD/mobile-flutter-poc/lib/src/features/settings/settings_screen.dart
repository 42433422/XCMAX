import 'dart:async';

import 'package:flutter/material.dart';

import '../../api/mobile_api.dart';
import '../../data/mobile_repository_scope.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';
import '../update/android_package_update_installer.dart';
import '../update/android_update_check.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({
    super.key,
    this.api,
    this.updateInstaller = const MethodChannelAndroidPackageUpdateInstaller(),
  });

  final MobileApiClient? api;
  final AndroidPackageUpdateInstaller updateInstaller;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final MobileApiClient _api;
  var _biometric = false;
  var _themeMode = 'system';
  var _submittingFeedback = false;
  var _checkingUpdate = false;
  final _feedbackController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _api = widget.api ??
        MobileRepositoryScope.maybeRead(context)?.client ??
        MobileApiClient();
    _loadCachedSettings();
  }

  @override
  void dispose() {
    _feedbackController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.surface,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            WeTopBar(
              title: '设置',
              showBack: Navigator.of(context).canPop(),
              onBack: Navigator.of(context).canPop()
                  ? () => Navigator.of(context).maybePop()
                  : null,
            ),
            Expanded(
              child: ListView(
                padding: EdgeInsets.zero,
                children: [
                  const WeSectionCaption('安全'),
                  WeCellGroup(
                    children: [
                      WeCell(
                        title: '生物识别解锁',
                        subtitle: _biometric ? '已开启' : '未开启',
                        icon: Icons.fingerprint,
                        iconColor: colors.brand,
                        iconBg: colors.brandContainer,
                        trailing: _WeSwitch(
                          checked: _biometric,
                          onChanged: _setBiometricEnabled,
                        ),
                        showArrow: false,
                        showDivider: false,
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  const WeSectionCaption('外观'),
                  WeCellGroup(
                    children: [
                      WeCell(
                        title: '主题模式',
                        subtitle: _themeLabel(_themeMode),
                        icon: Icons.palette,
                        iconColor: colors.success,
                        iconBg:
                            Theme.of(context).colorScheme.secondaryContainer,
                        showArrow: false,
                        showDivider: false,
                      ),
                      Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 16,
                          vertical: 8,
                        ),
                        child: Row(
                          children: [
                            _ThemeModeChip(
                              label: '跟随',
                              icon: Icons.tune,
                              selected: _themeMode == 'system',
                              onTap: () => _setThemeMode('system'),
                            ),
                            const SizedBox(width: 8),
                            _ThemeModeChip(
                              label: '浅色',
                              icon: Icons.light_mode,
                              selected: _themeMode == 'light',
                              onTap: () => _setThemeMode('light'),
                            ),
                            const SizedBox(width: 8),
                            _ThemeModeChip(
                              label: '深色',
                              icon: Icons.dark_mode,
                              selected: _themeMode == 'dark',
                              onTap: () => _setThemeMode('dark'),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  const WeSectionCaption('反馈'),
                  WeCellGroup(
                    children: [
                      WeCell(
                        title: '问题反馈',
                        subtitle: '提交后进入企业支持队列',
                        icon: Icons.bug_report,
                        iconColor: colors.warning,
                        iconBg: colors.warning.withValues(alpha: 0.14),
                        showArrow: false,
                        showDivider: false,
                      ),
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 16),
                        child: WeField(
                          controller: _feedbackController,
                          placeholder: '描述问题或建议',
                          maxLength: 500,
                          singleLine: false,
                          onChanged: (_) => setState(() {}),
                        ),
                      ),
                      const SizedBox(height: 8),
                      WeBlockButton(
                        text: '提交反馈',
                        onPressed: _submitFeedback,
                        enabled: _feedbackController.text.trim().isNotEmpty &&
                            !_submittingFeedback,
                      ),
                      const SizedBox(
                        key: ValueKey('settings_feedback_bottom_spacer'),
                        height: XcagiSpacing.md,
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  const WeSectionCaption('版本'),
                  WeCellGroup(
                    children: [
                      WeCell(
                        title: '检查更新',
                        subtitle: '获取企业版移动端最新构建',
                        icon: Icons.system_update,
                        iconColor: colors.success,
                        iconBg:
                            Theme.of(context).colorScheme.secondaryContainer,
                        showDivider: false,
                        onTap: _checkingUpdate ? null : _checkForUpdate,
                      ),
                    ],
                  ),
                  const SizedBox(height: 24),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _loadCachedSettings() async {
    try {
      final session = await _api.loadSession();
      if (!mounted) return;
      setState(() {
        _biometric = session.biometricEnabled;
        _themeMode = _normalizeThemeMode(session.themeMode);
      });
    } catch (_) {
      // Keep Android defaults when local settings storage is unavailable.
    }
  }

  void _setBiometricEnabled(bool value) {
    setState(() => _biometric = value);
    unawaited(_api.saveLocalSettings(biometricEnabled: value));
  }

  void _setThemeMode(String mode) {
    final normalized = _normalizeThemeMode(mode);
    setState(() => _themeMode = normalized);
    unawaited(_api.saveLocalSettings(themeMode: normalized));
  }

  Future<void> _submitFeedback() async {
    final message = _feedbackController.text.trim();
    if (message.isEmpty || _submittingFeedback) return;
    setState(() => _submittingFeedback = true);
    try {
      final response = await _api.submitFeedback(message);
      if (!response.success) {
        throw MobileApiException(
          statusCode: 200,
          message: response.message,
          body: response.raw,
        );
      }
      _feedbackController.clear();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('感谢您的反馈，我们会尽快处理')),
      );
    } catch (error) {
      if (!mounted) return;
      final message = error is MobileApiException
          ? error.message
          : error.toString().replaceFirst('Exception: ', '');
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(message.isEmpty ? '反馈提交失败，请稍后重试' : message)),
      );
    } finally {
      if (mounted) setState(() => _submittingFeedback = false);
    }
  }

  Future<void> _checkForUpdate() async {
    if (_checkingUpdate) return;
    setState(() => _checkingUpdate = true);
    try {
      await runAndroidUpdateCheck(
        context,
        _api,
        installer: widget.updateInstaller,
      );
    } finally {
      if (mounted) setState(() => _checkingUpdate = false);
    }
  }
}

class _WeSwitch extends StatelessWidget {
  const _WeSwitch({
    required this.checked,
    required this.onChanged,
  });

  final bool checked;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return GestureDetector(
      onTap: () => onChanged(!checked),
      child: AnimatedContainer(
        key: const ValueKey('settings_we_switch'),
        duration: const Duration(milliseconds: 180),
        curve: Curves.easeOut,
        width: 46,
        height: 28,
        padding: const EdgeInsets.all(3),
        decoration: BoxDecoration(
          color: checked
              ? colors.weChatOnline
              : Theme.of(context).colorScheme.outline.withValues(alpha: 0.28),
          borderRadius: BorderRadius.circular(14),
        ),
        alignment: checked ? Alignment.centerRight : Alignment.centerLeft,
        child: Container(
          width: 22,
          height: 22,
          decoration: BoxDecoration(
            color: Colors.white,
            shape: BoxShape.circle,
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.18),
                blurRadius: 2,
                offset: const Offset(0, 1),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ThemeModeChip extends StatelessWidget {
  const _ThemeModeChip({
    required this.label,
    required this.icon,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final IconData icon;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final scheme = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;
    final selectedForeground = scheme.onPrimary;
    return Expanded(
      child: Material(
        color: selected ? colors.brand : colors.surfaceHigh,
        borderRadius: BorderRadius.circular(10),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(10),
          child: SizedBox(
            height: 38,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(
                  icon,
                  size: 15,
                  color: selected ? selectedForeground : colors.textSecondary,
                ),
                const SizedBox(width: 5),
                Text(
                  label,
                  style: textTheme.labelMedium?.copyWith(
                    color: selected ? selectedForeground : colors.textSecondary,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

String _themeLabel(String mode) {
  switch (_normalizeThemeMode(mode)) {
    case 'dark':
      return '深色';
    case 'light':
      return '浅色';
    default:
      return '跟随系统';
  }
}

String _normalizeThemeMode(String mode) {
  final normalized = mode.trim().toLowerCase();
  if (normalized == 'light' || normalized == 'dark') return normalized;
  return 'system';
}
