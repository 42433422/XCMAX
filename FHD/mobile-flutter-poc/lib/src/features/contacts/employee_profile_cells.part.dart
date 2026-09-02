part of 'employee_profile_screen.dart';

class _CirclePreview extends StatelessWidget {
  const _CirclePreview({required this.employee, required this.onTap});

  final AiEmployeeProfile employee;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final abilities = employee.abilityLabels().take(3).toList(growable: false);
    return Material(
      color: colors.surface,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
          child: Column(
            children: [
              Row(
                children: [
                  Icon(Icons.forum, size: 20, color: colors.momentAccent),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('AI交流圈', style: _titleStyle(colors)),
                        const SizedBox(height: 2),
                        Text(
                          '进入交流圈 · 查看 ${employee.name} 的动态与能力更新',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: _bodyStyle(colors),
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
              if (abilities.isNotEmpty) ...[
                const SizedBox(height: 12),
                Padding(
                  padding: const EdgeInsets.only(left: 30),
                  child: Row(
                    children: [
                      for (final ability in abilities) ...[
                        _PreviewTile(
                          label: ability,
                          color: _aiEmployeeAvatarColor(
                            '${employee.key}:$ability',
                          ),
                        ),
                        const SizedBox(width: 8),
                      ],
                    ],
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _PreviewTile extends StatelessWidget {
  const _PreviewTile({required this.label, required this.color});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 44,
      height: 44,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.16),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        label.characters.take(2).toString(),
        style: TextStyle(
          color: color,
          fontSize: 11,
          height: 1.27,
          fontWeight: FontWeight.w600,
          letterSpacing: 0,
        ),
      ),
    );
  }
}

class _ActionRow extends StatelessWidget {
  const _ActionRow({required this.text, required this.icon, this.onTap});

  final String text;
  final IconData icon;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Material(
      color: colors.surface,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 14),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, size: 22, color: colors.brand),
              const SizedBox(width: 10),
              Text(
                text,
                style: TextStyle(
                  color: colors.brand,
                  fontSize: 17,
                  height: 1.29,
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

Color _aiEmployeeAvatarColor(String key) {
  const colors = [
    Color(0xFF3370FF),
    Color(0xFF00B578),
    Color(0xFF8B5CF6),
    Color(0xFF00ACC1),
    Color(0xFFED7B2F),
    Color(0xFF494E56),
  ];
  return colors[_floorMod(_javaStringHash(key), colors.length)];
}

int _javaStringHash(String value) {
  var hash = 0;
  for (final codeUnit in value.codeUnits) {
    hash = (31 * hash + codeUnit) & 0xFFFFFFFF;
  }
  return hash >= 0x80000000 ? hash - 0x100000000 : hash;
}

int _floorMod(int value, int mod) {
  final remainder = value % mod;
  return remainder < 0 ? remainder + mod : remainder;
}

TextStyle _titleStyle(XcagiThemeColors colors) {
  return TextStyle(
    color: colors.textPrimary,
    fontSize: 17,
    height: 1.29,
    fontWeight: FontWeight.w500,
    letterSpacing: 0,
  );
}

TextStyle _bodyStyle(XcagiThemeColors colors) {
  return TextStyle(
    color: colors.textSecondary,
    fontSize: 15,
    height: 1.4,
    letterSpacing: 0,
  );
}
