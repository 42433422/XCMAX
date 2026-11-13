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
