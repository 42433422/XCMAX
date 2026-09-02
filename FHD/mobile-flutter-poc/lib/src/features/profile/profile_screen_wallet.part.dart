part of 'profile_screen.dart';

// 钱包余额卡片组件与余额格式化。
class _WalletBalanceCard extends StatelessWidget {
  const _WalletBalanceCard({required this.wallet, required this.onRefresh});

  final WalletBalanceData wallet;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final balanceText =
        wallet.balance == null ? '—' : _formatBalance(wallet.balance!);
    final currency = wallet.currency.trim().isEmpty ? 'CNY' : wallet.currency;
    final membership =
        wallet.membershipLevel.trim().isEmpty ? '未开通' : wallet.membershipLevel;
    final experience = wallet.experience?.toString() ?? '—';
    final byok = wallet.byokConfigured ? '已开通' : '未开通';

    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onRefresh,
        borderRadius: BorderRadius.circular(16),
        child: Container(
          key: const ValueKey('profile_wallet_card'),
          margin: const EdgeInsets.symmetric(horizontal: 16),
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            gradient: LinearGradient(
              colors: [colors.brand, colors.brandGradientEnd],
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      '账户余额',
                      style: TextStyle(
                        color: colors.chatUserBubbleText.withValues(
                          alpha: 0.85,
                        ),
                        fontSize: 13,
                        height: 1.31,
                        fontWeight: FontWeight.w500,
                        letterSpacing: 0,
                      ),
                    ),
                  ),
                  Icon(
                    Icons.refresh_outlined,
                    size: 16,
                    color: Colors.white.withValues(alpha: 0.85),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(
                    balanceText,
                    style: TextStyle(
                      color: colors.chatUserBubbleText,
                      fontSize: 20,
                      height: 1.4,
                      fontWeight: FontWeight.w600,
                      letterSpacing: 0,
                    ),
                  ),
                  const SizedBox(width: 4),
                  Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Text(
                      currency,
                      style: TextStyle(
                        color: colors.chatUserBubbleText.withValues(
                          alpha: 0.85,
                        ),
                        fontSize: 13,
                        height: 1.31,
                        fontWeight: FontWeight.w500,
                        letterSpacing: 0,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  _BalanceMetric(label: '会员等级', value: membership),
                  _BalanceMetric(label: '经验值', value: experience),
                  _BalanceMetric(label: 'BYOK', value: byok),
                ],
              ),
              if (!wallet.synced && wallet.message.trim().isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(
                  wallet.message,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: colors.chatUserBubbleText.withValues(alpha: 0.7),
                    fontSize: 11,
                    height: 1.27,
                    letterSpacing: 0,
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

class _BalanceMetric extends StatelessWidget {
  const _BalanceMetric({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Text(
          label,
          style: TextStyle(
            color: colors.chatUserBubbleText.withValues(alpha: 0.7),
            fontSize: 11,
            height: 1.27,
            fontWeight: FontWeight.w500,
            letterSpacing: 0,
          ),
        ),
        const SizedBox(height: 2),
        Text(
          value,
          style: TextStyle(
            color: colors.chatUserBubbleText,
            fontSize: 15,
            height: 1.4,
            fontWeight: FontWeight.w500,
            letterSpacing: 0,
          ),
        ),
      ],
    );
  }
}

String _formatBalance(double value) {
  final fixed = value.toStringAsFixed(2);
  final parts = fixed.split('.');
  final integer = parts.first;
  final buffer = StringBuffer();
  for (var i = 0; i < integer.length; i++) {
    final remaining = integer.length - i;
    buffer.write(integer[i]);
    if (remaining > 1 && remaining % 3 == 1) {
      buffer.write(',');
    }
  }
  return '${buffer.toString()}.${parts.last}';
}
