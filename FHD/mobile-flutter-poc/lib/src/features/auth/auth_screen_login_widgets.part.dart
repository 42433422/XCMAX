// part 文件：登录表单组件。

part of 'auth_screen.dart';


const _termsUrl = 'https://xiu-ci.com/legal/terms';
const _privacyUrl = 'https://xiu-ci.com/legal/privacy';

class _AuthLogo extends StatelessWidget {
  const _AuthLogo();

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(18),
      child: SizedBox(
        width: 72,
        height: 72,
        child: Center(
          child: Image.asset(
            appLauncherForegroundAsset,
            width: 50,
            height: 50,
            fit: BoxFit.contain,
          ),
        ),
      ),
    );
  }
}

class _AccountKindSegment extends StatelessWidget {
  const _AccountKindSegment({required this.adminMode, required this.onChanged});

  final bool adminMode;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      decoration: BoxDecoration(
        color: colors.surfaceHigh,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: colors.divider, width: 0.5),
      ),
      padding: const EdgeInsets.all(4),
      child: Row(
        children: [
          Expanded(
            child: _AccountKindSegmentItem(
              label: '服务器后台',
              selected: adminMode,
              onTap: () => onChanged(true),
            ),
          ),
          const SizedBox(width: 4),
          Expanded(
            child: _AccountKindSegmentItem(
              label: '企业工作台',
              selected: !adminMode,
              onTap: () => onChanged(false),
            ),
          ),
        ],
      ),
    );
  }
}

class _AccountKindSegmentItem extends StatelessWidget {
  const _AccountKindSegmentItem({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(14),
      child: Container(
        height: 36,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: selected ? colors.brand : Colors.transparent,
          borderRadius: BorderRadius.circular(14),
        ),
        child: Text(
          label,
          style: TextStyle(
            color: selected ? Colors.white : colors.textSecondary,
            fontSize: 14,
            height: 1.29,
            fontWeight: FontWeight.w500,
            letterSpacing: 0,
          ),
        ),
      ),
    );
  }
}

class _AuthTextField extends StatefulWidget {
  const _AuthTextField({
    required this.controller,
    required this.hintText,
    this.obscureText = false,
    this.suffix,
    this.onChanged,
  });

  final TextEditingController controller;
  final String hintText;
  final bool obscureText;
  final Widget? suffix;
  final ValueChanged<String>? onChanged;

  @override
  State<_AuthTextField> createState() => _AuthTextFieldState();
}

class _AuthTextFieldState extends State<_AuthTextField> {
  final _focusNode = FocusNode();
  var _focused = false;

  @override
  void initState() {
    super.initState();
    _focusNode.addListener(_handleFocusChanged);
  }

  @override
  void dispose() {
    _focusNode
      ..removeListener(_handleFocusChanged)
      ..dispose();
    super.dispose();
  }

  void _handleFocusChanged() {
    if (_focused == _focusNode.hasFocus) return;
    setState(() => _focused = _focusNode.hasFocus);
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      height: 46,
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: _focused ? colors.brand : colors.divider,
          width: 1,
        ),
      ),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: widget.controller,
              focusNode: _focusNode,
              obscureText: widget.obscureText,
              onChanged: widget.onChanged,
              style: TextStyle(
                color: colors.textPrimary,
                fontSize: 15,
                height: 1.4,
                letterSpacing: 0,
              ),
              decoration: InputDecoration(
                isDense: true,
                hintText: widget.hintText,
                border: InputBorder.none,
                contentPadding: const EdgeInsets.symmetric(horizontal: 16),
                hintStyle: TextStyle(
                  color: colors.textSecondary,
                  fontSize: 15,
                  height: 1.4,
                  letterSpacing: 0,
                ),
              ),
            ),
          ),
          if (widget.suffix != null)
            Padding(
              padding: const EdgeInsets.only(right: 4),
              child: widget.suffix!,
            ),
        ],
      ),
    );
  }
}
