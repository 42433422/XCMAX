import 'package:flutter/material.dart';

import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';

class MarketListScreen extends StatefulWidget {
  const MarketListScreen({
    super.key,
    this.repository,
    this.initialIndustries,
    this.initialCapabilities,
    this.initialPlans,
  });

  final MobileRepository? repository;
  final List<OnboardingIndustry>? initialIndustries;
  final List<MarketCapability>? initialCapabilities;
  final List<PaymentPlan>? initialPlans;

  @override
  State<MarketListScreen> createState() => _MarketListScreenState();
}

class _MarketListScreenState extends State<MarketListScreen> {
  late final MobileRepository _repository;
  late Future<_MarketViewData> _future;
  var _paymentChannel = 'mobile_h5';
  var _status = '';
  var _workingId = '';

  static const _paymentChannels = [
    ('mobile_h5', '手机网页'),
    ('alipay', '支付宝'),
    ('wechat_h5', '微信支付'),
  ];

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _future = _load();
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
              title: 'MODstore',
              actions: [
                IconButton(
                  onPressed: _refresh,
                  icon: const Icon(Icons.refresh),
                  tooltip: '刷新',
                  color: colors.textPrimary,
                ),
              ],
            ),
            Expanded(
              child: FutureBuilder<_MarketViewData>(
                future: _future,
                builder: (context, snapshot) {
                  final data = snapshot.data ?? _MarketViewData.empty();
                  final status = _status.ifEmpty(data.status);
                  final industryStatus = status;
                  final paymentStatus = status;
                  final industries = data.industries.take(6).toList();
                  final plans = data.plans.take(4).toList();
                  return RefreshIndicator(
                    color: colors.brand,
                    onRefresh: _refresh,
                    child: ListView(
                      physics: const AlwaysScrollableScrollPhysics(),
                      padding: const EdgeInsets.only(top: 12, bottom: 96),
                      children: [
                        const WeSectionCaption('行业初始化'),
                        WeCellGroup(
                          children: [
                            if (industries.isEmpty)
                              WeCell(
                                title: '行业目录',
                                subtitle: industryStatus.ifEmpty('登录后自动同步可选行业'),
                                icon: Icons.extension,
                                showArrow: false,
                              )
                            else
                              for (var i = 0; i < industries.length; i++)
                                WeCell(
                                  title: industries[i].title,
                                  subtitle: industries[i].subtitle.ifEmpty(
                                      industryStatus.ifEmpty('装齐行业基础能力')),
                                  icon: Icons.extension,
                                  showArrow: false,
                                  showDivider: i < industries.length - 1,
                                  trailing: _MarketActionButton(
                                    text: _workingId == industries[i].id
                                        ? '处理中'
                                        : '装齐',
                                    onPressed: _workingId.isEmpty
                                        ? () => _bootstrap(industries[i])
                                        : null,
                                  ),
                                ),
                          ],
                        ),
                        const WeSectionCaption('模型服务'),
                        WeCellGroup(
                          children: [
                            WeCell(
                              title: '手机充值渠道',
                              subtitle: '当前：${_channelTitle(_paymentChannel)}',
                              icon: Icons.extension,
                              showArrow: false,
                            ),
                            for (final channel in _paymentChannels)
                              WeCell(
                                title: channel.$2,
                                subtitle: _paymentChannel == channel.$1
                                    ? '当前充值与购买渠道'
                                    : '切换到${channel.$2}',
                                icon: Icons.extension,
                                showArrow: false,
                                trailing: _MarketActionButton(
                                  text: _paymentChannel == channel.$1
                                      ? '当前'
                                      : '选择',
                                  onPressed: () {
                                    setState(() {
                                      _paymentChannel = channel.$1;
                                    });
                                  },
                                ),
                              ),
                            WeCell(
                              title: '钱包充值',
                              subtitle: paymentStatus.ifEmpty('用当前手机渠道充值 50 元'),
                              icon: Icons.extension,
                              showArrow: false,
                              trailing: _MarketActionButton(
                                text: '充50',
                                onPressed:
                                    _workingId.isEmpty ? _rechargeWallet : null,
                              ),
                            ),
                            if (plans.isEmpty)
                              WeCell(
                                title: '套餐与钱包',
                                subtitle:
                                    paymentStatus.ifEmpty('刷新后同步市场套餐与会员状态'),
                                icon: Icons.extension,
                                showArrow: false,
                              )
                            else
                              for (var i = 0; i < plans.length; i++)
                                WeCell(
                                  title: plans[i].title,
                                  subtitle: plans[i].subtitle.ifEmpty(
                                        paymentStatus.ifEmpty('市场统一收银台'),
                                      ),
                                  icon: Icons.extension,
                                  showArrow: false,
                                  showDivider: i < plans.length - 1,
                                  trailing: _MarketActionButton(
                                    text: '购买',
                                    onPressed: _workingId.isEmpty
                                        ? () => _checkout(plans[i])
                                        : null,
                                  ),
                                ),
                          ],
                        ),
                        const WeSectionCaption('可用能力'),
                        WeCellGroup(
                          children: [
                            if (data.capabilities.isEmpty)
                              const WeCell(
                                title: '暂无可用能力',
                                subtitle: '先装齐行业能力或刷新市场目录',
                                icon: Icons.extension,
                                showArrow: false,
                              )
                            else
                              for (var i = 0; i < data.capabilities.length; i++)
                                WeCell(
                                  title: data.capabilities[i].title,
                                  subtitle: data.capabilities[i].subtitle
                                      .ifEmpty('从企业端同步的能力包'),
                                  icon: Icons.extension,
                                  showArrow: false,
                                  showDivider: i < data.capabilities.length - 1,
                                  trailing: _MarketActionButton(
                                    text: '使用',
                                    onPressed: _workingId.isEmpty
                                        ? () => _useCapability(
                                              data.capabilities[i],
                                            )
                                        : null,
                                  ),
                                ),
                          ],
                        ),
                      ],
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<_MarketViewData> _load() async {
    final errors = <String>[];
    final List<OnboardingIndustry> industries = widget.initialIndustries ??
        await _readOr(
          _repository.loadOnboardingIndustries,
          const <OnboardingIndustry>[],
          errors,
        );
    final List<PaymentPlan> plans = widget.initialPlans ??
        await _readOr(
          _repository.loadPaymentPlans,
          const <PaymentPlan>[],
          errors,
        );
    final List<MarketCapability> capabilities = widget.initialCapabilities ??
        await _readOr(
          _repository.loadMarketCapabilities,
          const <MarketCapability>[],
          errors,
        );
    return _MarketViewData(
      industries: industries,
      capabilities: capabilities,
      plans: plans,
      status: errors.join('\n'),
    );
  }

  Future<void> _refresh() async {
    final future = _load();
    setState(() {
      _future = future;
      _status = '';
    });
    await future;
  }

  Future<T> _readOr<T>(
    Future<T> Function() loader,
    T fallback,
    List<String> errors,
  ) async {
    try {
      return await loader();
    } catch (error) {
      errors.add(error.toString());
      return fallback;
    }
  }

  Future<void> _bootstrap(OnboardingIndustry industry) async {
    await _runAction(
        industry.id, () => _repository.bootstrapIndustry(industry.id));
  }

  Future<void> _checkout(PaymentPlan plan) async {
    await _runAction(
      plan.id,
      () => _repository.checkoutPaymentPlan(
        planId: plan.id,
        channel: _paymentChannel,
      ),
    );
  }

  Future<void> _rechargeWallet() async {
    await _runAction(
      'wallet',
      () => _repository.checkoutWalletRecharge(channel: _paymentChannel),
    );
  }

  Future<void> _useCapability(MarketCapability item) async {
    await _runAction(item.id, () async {
      await _repository.installMarketMod(item.id);
      return '${item.title} 已安装';
    });
  }

  Future<void> _runAction(String id, Future<String> Function() action) async {
    setState(() => _workingId = id);
    try {
      final message = await action();
      if (!mounted) return;
      setState(() => _status = message);
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(message)));
    } catch (error) {
      if (!mounted) return;
      setState(() => _status = error.toString());
    } finally {
      if (mounted) setState(() => _workingId = '');
    }
  }

  String _channelTitle(String id) {
    for (final channel in _paymentChannels) {
      if (channel.$1 == id) return channel.$2;
    }
    return '手机网页';
  }
}

class _MarketViewData {
  const _MarketViewData({
    required this.industries,
    required this.capabilities,
    required this.plans,
    required this.status,
  });

  final List<OnboardingIndustry> industries;
  final List<MarketCapability> capabilities;
  final List<PaymentPlan> plans;
  final String status;

  factory _MarketViewData.empty() {
    return const _MarketViewData(
      industries: [],
      capabilities: [],
      plans: [],
      status: '',
    );
  }
}

class _MarketActionButton extends StatelessWidget {
  const _MarketActionButton({
    required this.text,
    required this.onPressed,
  });

  final String text;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return TextButton(
      onPressed: onPressed,
      child: Text(
        text,
        style: TextStyle(
          color: onPressed == null ? colors.textTertiary : colors.brand,
        ),
      ),
    );
  }
}

extension on String {
  String ifEmpty(String fallback) => trim().isEmpty ? fallback : trim();
}
