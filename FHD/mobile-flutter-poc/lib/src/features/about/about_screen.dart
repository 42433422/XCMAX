import 'package:flutter/material.dart';

import '../../api/mobile_api.dart';
import '../../data/mobile_repository_scope.dart';
import '../../platform/external_url_launcher.dart';
import '../../theme/app_assets.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';
import '../update/android_package_update_installer.dart';
import '../update/android_update_check.dart';

class AboutScreen extends StatefulWidget {
  const AboutScreen({
    super.key,
    this.api,
    this.openExternalUrl,
    this.updateInstaller = const MethodChannelAndroidPackageUpdateInstaller(),
  });

  final MobileApiClient? api;
  final ExternalUrlLauncher? openExternalUrl;
  final AndroidPackageUpdateInstaller updateInstaller;

  static const companyName = '成都修茈科技有限公司';
  static const brandUrl = 'https://xiu-ci.com';
  static const appVersion = MobileAndroidBuild.displayVersion;
  static const websiteIcp = '蜀ICP备2026014056号-3A';
  static const appFilingSubtitle = '审核通过 2026-04-08';

  @override
  State<AboutScreen> createState() => _AboutScreenState();
}

class _AboutScreenState extends State<AboutScreen> {
  late final MobileApiClient _api;
  late final ExternalUrlLauncher _openExternalUrl;
  var _checkingUpdate = false;

  @override
  void initState() {
    super.initState();
    _api = widget.api ??
        MobileRepositoryScope.maybeRead(context)?.client ??
        MobileApiClient();
    _openExternalUrl = widget.openExternalUrl ?? launchExternalUrl;
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
              title: '关于',
              showBack: true,
              onBack: () => Navigator.of(context).maybePop(),
            ),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.only(bottom: 32),
                children: [
                  const SizedBox(height: 32),
                  Center(
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(16),
                      child: Image.asset(
                        appLauncherIconAsset,
                        width: 72,
                        height: 72,
                        fit: BoxFit.contain,
                      ),
                    ),
                  ),
                  const SizedBox(height: 12),
                  Center(
                    child: Text(
                      'XCAGI',
                      style: TextStyle(
                        color: colors.textPrimary,
                        fontSize: 20,
                        height: 1.3,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 0,
                      ),
                    ),
                  ),
                  const SizedBox(height: 2),
                  Center(
                    child: Text(
                      AboutScreen.appVersion,
                      style: TextStyle(
                        color: colors.textSecondary,
                        fontSize: 13,
                        height: 1.31,
                        letterSpacing: 0,
                      ),
                    ),
                  ),
                  const SizedBox(height: 24),
                  const WeSectionCaption('信息'),
                  WeCellGroup(
                    children: [
                      const WeCell(
                        title: '公司',
                        subtitle: AboutScreen.companyName,
                        showArrow: false,
                      ),
                      WeCell(
                        title: '官网',
                        subtitle: AboutScreen.brandUrl,
                        onTap: _openBrandUrl,
                      ),
                      WeCell(
                        title: '检查更新',
                        subtitle: AboutScreen.appVersion,
                        showDivider: false,
                        onTap: _checkingUpdate ? null : _checkForUpdate,
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  const ComplianceFooter(),
                ],
              ),
            ),
          ],
        ),
      ),
    );
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

  Future<void> _openBrandUrl() async {
    final opened = await _openExternalUrl(Uri.parse(AboutScreen.brandUrl));
    if (!mounted || opened) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('无法打开官网')),
    );
  }
}

class ComplianceFooter extends StatelessWidget {
  const ComplianceFooter({super.key});

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Column(
        children: [
          Text(
            AboutScreen.companyName,
            textAlign: TextAlign.center,
            style: TextStyle(
              color: colors.textTertiary,
              fontSize: 11,
              height: 1.27,
              letterSpacing: 0,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            AboutScreen.websiteIcp,
            textAlign: TextAlign.center,
            style: TextStyle(
              color: colors.textTertiary,
              fontSize: 11,
              height: 1.27,
              letterSpacing: 0,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            AboutScreen.appFilingSubtitle,
            textAlign: TextAlign.center,
            style: TextStyle(
              color: colors.textTertiary,
              fontSize: 11,
              height: 1.27,
              letterSpacing: 0,
            ),
          ),
        ],
      ),
    );
  }
}
