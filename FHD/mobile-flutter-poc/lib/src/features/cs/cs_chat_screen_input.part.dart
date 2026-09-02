// part 文件：客服聊天输入栏与字符串扩展。

part of 'cs_chat_screen.dart';

class _CsInputBar extends StatelessWidget {
  const _CsInputBar({
    required this.controller,
    required this.streaming,
    required this.onSend,
    required this.onStop,
    required this.onVoice,
  });

  final TextEditingController controller;
  final bool streaming;
  final VoidCallback onSend;
  final VoidCallback onStop;
  final VoidCallback onVoice;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return SafeArea(
      top: false,
      child: Container(
        key: const ValueKey('cs_input_bar_surface'),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: colors.surface,
          border: Border(
            top: BorderSide(color: colors.weChatDivider, width: 0.5),
          ),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            _CsCircleIconButton(
              onPressed: onVoice,
              icon: Icons.mic,
              tooltip: '语音',
              foregroundColor: colors.textSecondary,
            ),
            const SizedBox(width: 6),
            Expanded(
              child: Container(
                constraints: const BoxConstraints(minHeight: 36),
                padding: const EdgeInsets.symmetric(horizontal: 10),
                decoration: BoxDecoration(
                  color: colors.weChatInputBg,
                  borderRadius: BorderRadius.circular(4),
                  border: Border.all(color: colors.weChatDivider, width: 0.5),
                ),
                alignment: Alignment.center,
                child: TextField(
                  controller: controller,
                  maxLines: 1,
                  textInputAction: TextInputAction.send,
                  onSubmitted: (_) => onSend(),
                  decoration: InputDecoration(
                    isCollapsed: true,
                    border: InputBorder.none,
                    hintText: '输入消息...',
                    hintStyle: TextStyle(
                      color: colors.textTertiary,
                      fontSize: 15,
                      height: 1.4,
                      letterSpacing: 0,
                    ),
                  ),
                  style: TextStyle(
                    color: colors.textPrimary,
                    fontSize: 15,
                    height: 1.4,
                    letterSpacing: 0,
                  ),
                ),
              ),
            ),
            const SizedBox(width: 6),
            _CsCircleIconButton(
              onPressed: streaming ? onStop : onSend,
              icon: streaming ? Icons.close : Icons.send,
              tooltip: streaming ? '停止' : '发送',
              backgroundColor: streaming ? colors.danger : colors.brand,
              foregroundColor: colors.surface,
            ),
          ],
        ),
      ),
    );
  }
}

class _CsCircleIconButton extends StatelessWidget {
  const _CsCircleIconButton({
    required this.onPressed,
    required this.icon,
    required this.tooltip,
    this.backgroundColor = Colors.transparent,
    required this.foregroundColor,
  });

  final VoidCallback onPressed;
  final IconData icon;
  final String tooltip;
  final Color backgroundColor;
  final Color foregroundColor;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: Semantics(
        button: true,
        label: tooltip,
        child: Material(
          color: backgroundColor,
          shape: const CircleBorder(),
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            onTap: onPressed,
            customBorder: const CircleBorder(),
            child: SizedBox.square(
              dimension: 36,
              child: Icon(icon, size: 22, color: foregroundColor),
            ),
          ),
        ),
      ),
    );
  }
}

extension on String {
  String ifEmpty(String fallback) => trim().isEmpty ? fallback : this;

  String take(int length) {
    final value = trim();
    return value.length <= length ? value : value.substring(0, length);
  }
}
