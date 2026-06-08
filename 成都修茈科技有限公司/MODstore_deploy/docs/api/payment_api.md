# payment_api

## POST /refund

### 请求体

- `out_trade_no`: str (必填)
- `reason`: str (默认值: "用户申请退款")
- `refund_reason`: Optional[str] (默认值: null, 描述: "结构化退款原因（用于风控/对账归档）。空时取 reason 兜底。", 最大长度: 256)

### 响应示例

```json
{"ok": true}
```
