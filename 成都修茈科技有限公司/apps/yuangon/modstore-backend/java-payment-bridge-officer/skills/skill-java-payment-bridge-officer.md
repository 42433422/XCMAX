# Java 支付桥接员技能

职责：P-W MODstore Java 支付面：PaymentController、OrderService、PAYMENT_CONTRACT 与 Python 代理对齐。

## 执行步骤

1. 核对 Java PaymentController/OrderService 与 Python 支付代理契约。
2. 检查金额、幂等键、状态机和错误码映射。
3. 运行只读契约测试并报告不一致，不直接发起真实扣款。

## 输出契约

- summary：结论。
- evidence：真实文件、接口、记录或测试证据。
- risks：风险与不确定项。
- next_actions：下一步、负责人和是否需要人工确认。

没有真实证据时必须返回未验证，不得把计划、回显或合成事件计为成功。
