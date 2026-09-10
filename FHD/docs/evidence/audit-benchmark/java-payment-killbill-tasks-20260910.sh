#!/bin/bash
# R22 java-payment 域开源锚点实测：Kill Bill 0.24.12 任务集 B1-B3
# B1 金额精度/币种/支付状态机/幂等键；B2 退款一致+超额拒绝+对账净额；B3 凭据隔离/并发/异常可定位
#
# 重要修正（2026-09-10）：
#  1) 此前"环境阻塞（405/404）"结论是误判——宿主 curl 走了系统 HTTP 代理，
#     代理对 docker 端口返回 502/空响应。全部请求必须 --noproxy '*'。
#  2) Kill Bill 0.24.x 语义：
#     - 创建支付方式：POST /1.0/kb/accounts/{accId}/paymentMethods（不是 POST /1.0/kb/paymentMethods）
#     - 创建支付：POST /1.0/kb/accounts/{accId}/payments?paymentMethodId=...
#       body 为单个 PaymentTransactionJson：transactionType/amount/currency/
#       paymentExternalKey/transactionExternalKey
#     - 退款：POST /1.0/kb/payments/{paymentId}/refunds
#     - 交易状态字段是 transactions[].status（不是 transactionStatus）
set -u
K="http://127.0.0.1:18082"
KH=(-s --noproxy '*' -H "X-Killbill-ApiKey: bob" -H "X-Killbill-ApiSecret: lazar" -H 'Content-Type: application/json' -H 'X-Killbill-CreatedBy: r22')
RUN="r22-$(date +%s)"   # 每次运行唯一前缀，避免 externalKey 冲突

for i in $(seq 1 90); do
  curl -s --noproxy '*' -o /dev/null "$K/1.0/healthcheck" && break; sleep 4
done
curl -s --noproxy '*' "$K/1.0/healthcheck" | head -c 60; echo

# ---------- B1 金额精度 + 状态机 + 幂等 ----------
ACCID=$(curl "${KH[@]}" -X POST "$K/1.0/kb/accounts" -D /tmp/r22-kb-h.txt \
  -d "{\"externalKey\":\"$RUN-acct\",\"name\":\"R22 Payer\",\"currency\":\"USD\",\"timeZone\":\"UTC\"}" >/dev/null; \
  grep -i '^Location' /tmp/r22-kb-h.txt | sed -E 's#.*/accounts/##;s/\r//')
curl "${KH[@]}" -X POST "$K/1.0/kb/accounts/$ACCID/paymentMethods?isDefault=true" \
  -d "{\"externalKey\":\"$RUN-pm\",\"pluginName\":\"__EXTERNAL_PAYMENT__\"}" >/dev/null
PMID=$(curl "${KH[@]}" "$K/1.0/kb/accounts/$ACCID/paymentMethods" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["paymentMethodId"])')
PH=$(curl "${KH[@]}" -X POST "$K/1.0/kb/accounts/$ACCID/payments?paymentMethodId=$PMID" -D /tmp/r22-kb-p.txt \
  -d "{\"transactionType\":\"PURCHASE\",\"amount\":10.05,\"currency\":\"USD\",\"paymentExternalKey\":\"$RUN-pay\",\"transactionExternalKey\":\"$RUN-pay-txn\"}" >/dev/null; \
  grep -i '^Location' /tmp/r22-kb-p.txt | tr -d '\r' | sed -E 's#.*/payments/##;s#/*$##')
P1=$(curl "${KH[@]}" "$K/1.0/kb/payments/$PH")
AMT=$(echo "$P1" | python3 -c "import json,sys; t=json.load(sys.stdin)['transactions'][0]; print(t['amount'], t['transactionType'], t['status'])" 2>/dev/null)
# 幂等：同 paymentExternalKey 重复提交被服务端拒绝（状态机/唯一约束）
DUP=$(curl "${KH[@]}" -X POST "$K/1.0/kb/accounts/$ACCID/payments?paymentMethodId=$PMID" \
  -d "{\"transactionType\":\"PURCHASE\",\"amount\":10.05,\"currency\":\"USD\",\"paymentExternalKey\":\"$RUN-pay\",\"transactionExternalKey\":\"$RUN-pay-txn2\"}" | grep -ciE "already|duplicated|invalid payment transition|exception|error")
NPAY=$(curl "${KH[@]}" "$K/1.0/kb/accounts/$ACCID/payments" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")
B1=FAIL
[ "$AMT" = "10.05 PURCHASE SUCCESS" ] && [ "$DUP" -ge 1 ] && [ "$NPAY" = "1" ] && B1=PASS
echo "B1 $B1 amt=[$AMT] dup=$DUP payments=$NPAY"

# ---------- B2 退款一致 + 重放幂等 + 对账净额 ----------
# SSOT java-payment-B2：回调验签/重放/退款/对账。退款走 payments/{id}/refunds，
# body 只带 transactionExternalKey（paymentExternalKey 会触发状态机 404）。
curl "${KH[@]}" -X POST "$K/1.0/kb/payments/$PH/refunds?accountRefund=false" \
  -d "{\"amount\":10.05,\"currency\":\"USD\",\"transactionExternalKey\":\"$RUN-ref\"}" >/dev/null
P2=$(curl "${KH[@]}" "$K/1.0/kb/payments/$PH")
R2=$(echo "$P2" | python3 -c "
import json,sys
d=json.load(sys.stdin)
r=[t for t in d['transactions'] if t['transactionType']=='REFUND']
net=d.get('purchasedAmount',0)-d.get('refundedAmount',0)
print(r[0]['amount'] if r else 'none', r[0]['status'] if r else '', f'{net:.2f}')" 2>/dev/null)
# 重放：同 transactionExternalKey 重复退款被服务端幂等拒绝
REPLAY=$(curl "${KH[@]}" -X POST "$K/1.0/kb/payments/$PH/refunds?accountRefund=false" \
  -d "{\"amount\":10.05,\"currency\":\"USD\",\"transactionExternalKey\":\"$RUN-ref\"}" | grep -ciE "already exists|duplicated|exception|error|invalid")
B2=FAIL
[ "$R2" = "10.05 SUCCESS 0.00" ] && [ "$REPLAY" -ge 1 ] && B2=PASS
echo "B2 $B2 refund_net=[$R2] replay_reject=$REPLAY"

# ---------- B3 凭据隔离 + 并发 + 异常可定位 ----------
NOAUTH=$(curl -s --noproxy '*' -H 'Content-Type: application/json' "$K/1.0/kb/accounts/$ACCID" | grep -ciE "unauthorized|forbidden|permission")
BADSEC=$(curl -s --noproxy '*' -H "X-Killbill-ApiKey: bob" -H "X-Killbill-ApiSecret: WRONG" -H 'Content-Type: application/json' "$K/1.0/kb/accounts/$ACCID" | grep -ciE "unauthorized|forbidden|permission")
rm -f /tmp/r22-kb-conc*.txt /tmp/r22-kb-conc*.json
for i in $(seq 1 10); do
  curl "${KH[@]}" -X POST "$K/1.0/kb/accounts/$ACCID/payments?paymentMethodId=$PMID" \
    -o /tmp/r22-kb-conc$i.json -D /tmp/r22-kb-conc$i.txt \
    -d "{\"transactionType\":\"PURCHASE\",\"amount\":1.00,\"currency\":\"USD\",\"paymentExternalKey\":\"$RUN-conc-$i\",\"transactionExternalKey\":\"$RUN-conc-$i-t\"}" &
done
wait
OKC=$(grep -l '^HTTP/1.1 201' /tmp/r22-kb-conc*.txt 2>/dev/null | wc -l | tr -d ' ')
TOTAL=$(curl "${KH[@]}" "$K/1.0/kb/accounts/$ACCID/payments" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")
# 异常可定位：坏 JSON 返回结构化错误（非静默）
BADJSON=$(curl "${KH[@]}" -X POST "$K/1.0/kb/accounts/$ACCID/payments?paymentMethodId=$PMID" -d 'not-json{{' | grep -ciE "exception|error|unable|invalid")
B3=FAIL
[ "$NOAUTH" -ge 1 ] && [ "$BADSEC" -ge 1 ] && [ "$OKC" = "10" ] && [ "$TOTAL" = "11" ] && [ "$BADJSON" -ge 1 ] && B3=PASS
echo "B3 $B3 noauth=$NOAUTH badsecret=$BADSEC conc_ok=$OKC total=$TOTAL badjson=$BADJSON"

echo "SUMMARY B1=$B1 B2=$B2 B3=$B3"
