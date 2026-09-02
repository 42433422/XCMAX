// part 文件：深链员工页与启动期占位屏幕。

part of 'mobile_startup_shell.dart';

class _DeepLinkedAiEmployeeProfileScreen extends StatelessWidget {
  const _DeepLinkedAiEmployeeProfileScreen({
    required this.repository,
    required this.modId,
    required this.employeeId,
  });

  final MobileRepository repository;
  final String modId;
  final String employeeId;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return FutureBuilder(
      future: repository.loadAiEmployees(),
      builder: (context, snapshot) {
        final employees = snapshot.data ?? const [];
        final normalizedModId = modId.trim();
        final normalizedEmployeeId = employeeId.trim();
        final matches = employees.where((employee) {
          final employeeMatches =
              employee.employeeId.trim() == normalizedEmployeeId;
          final modMatches = normalizedModId.isEmpty ||
              employee.modId.trim() == normalizedModId;
          return employeeMatches && modMatches;
        });
        final employee = matches.isEmpty ? null : matches.first;
        if (employee != null) {
          return AiEmployeeProfileScreen(
            employee: employee,
            repository: repository,
          );
        }
        return Scaffold(
          backgroundColor: colors.page,
          body: SafeArea(
            bottom: false,
            child: Column(
              children: [
                WeTopBar(
                  title: 'AI员工',
                  showBack: true,
                  onBack: () => Navigator.of(context).maybePop(),
                ),
                Expanded(
                  child: Center(
                    child: Text(
                      snapshot.connectionState == ConnectionState.waiting
                          ? '正在同步员工资料'
                          : '未找到该 AI 员工',
                      style: TextStyle(
                        color: colors.textSecondary,
                        fontSize: 16,
                        height: 1.38,
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

class _StartupLoadingScreen extends StatelessWidget {
  const _StartupLoadingScreen();

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.surface,
      body: const Center(
        child: SizedBox(
          width: 28,
          height: 28,
          child: CircularProgressIndicator(strokeWidth: 2.4),
        ),
      ),
    );
  }
}

class _BiometricLockScreen extends StatelessWidget {
  const _BiometricLockScreen();

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.surface,
      body: SafeArea(
        child: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(16),
                child: Image.asset(
                  appLauncherIconAsset,
                  width: 64,
                  height: 64,
                  fit: BoxFit.contain,
                ),
              ),
              const SizedBox(height: 16),
              Text(
                '正在验证身份',
                style: TextStyle(
                  color: colors.textPrimary,
                  fontSize: 17,
                  height: 1.29,
                  fontWeight: FontWeight.w600,
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
