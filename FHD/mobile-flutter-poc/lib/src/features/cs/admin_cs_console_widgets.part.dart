// part 文件：客服输入栏、头像与字符串扩展。

part of 'admin_cs_console_screen.dart';

class _AdminCsInputBar extends StatelessWidget {
  const _AdminCsInputBar({
    required this.controller,
    required this.sending,
    required this.onSend,
  });

  final TextEditingController controller;
  final bool sending;
  final VoidCallback onSend;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return SafeArea(
      top: false,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: colors.surface,
          border: Border(
            top: BorderSide(color: colors.weChatDivider, width: 0.5),
          ),
        ),
        child: Row(
          children: [
            Expanded(
              child: TextField(
                controller: controller,
                minLines: 1,
                maxLines: 4,
                onChanged: (_) {},
                decoration: InputDecoration(
                  hintText: '以企业专属客服身份回复...',
                  isDense: true,
                  filled: true,
                  fillColor: colors.weChatInputBg,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(6),
                    borderSide: BorderSide(color: colors.weChatDivider),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(6),
                    borderSide: BorderSide(color: colors.weChatDivider),
                  ),
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 8,
                  ),
                ),
              ),
            ),
            const SizedBox(width: 8),
            IconButton.filled(
              onPressed: sending ? null : onSend,
              icon: const Icon(Icons.send),
              tooltip: '发送',
              style: IconButton.styleFrom(
                backgroundColor: colors.brand,
                foregroundColor: Colors.white,
                disabledBackgroundColor: colors.divider,
                disabledForegroundColor: colors.textTertiary,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _CustomerAvatar extends StatelessWidget {
  const _CustomerAvatar({required this.name, this.size = 44});

  final String name;
  final double size;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final clean = name.trim();
    final letter = clean.isEmpty ? '客' : clean.substring(0, 1);
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: colors.brand,
        borderRadius: BorderRadius.circular(size >= 40 ? 8 : size / 2),
      ),
      child: Text(
        letter,
        style: TextStyle(
          color: Colors.white,
          fontSize: size >= 40 ? 18 : 14,
          height: 1,
          fontWeight: FontWeight.w700,
          letterSpacing: 0,
        ),
      ),
    );
  }
}

extension _AdminCsStringExt on String {
  String ifEmpty(String fallback) => trim().isEmpty ? fallback : this;

  String take(int count) {
    if (length <= count) return this;
    return substring(0, count);
  }
}
