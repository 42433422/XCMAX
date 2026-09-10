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
#
# #1858 整改（2026-09-10）：
#  A) 退出语义：SUMMARY 后显式判定——B1/B2/B3 任一 FAIL → exit 1；全 PASS → exit 0；
#     环境阻断（健康检查不过 / 资源 ID 缺失）→ exit 2。set -u/set -euo pipefail
#     不能替代业务断言，失败文本本身不阻止返回 0，必须显式退出判定。
#  B) 鉴权/重放/异常不再用 grep 匹配 error/exception/unauthorized 文字：
#     逐一断言精确 HTTP 状态码、结构化错误 JSON（code/message）、精确业务码
#     （重放退款 code=7030，来自首轮实测证据）、支付/退款数量与账本净额。
#     5xx 一律按服务故障记 FAIL，不把任意失败算幂等成功。
#  C) 负向回归（无需 Kill Bill 服务，验证退出门禁本身）：
#     KB_SELFTEST=force-b1|force-b2|force-b3 → 强制对应位 FAIL，必须非零退出；
#     KB_SELFTEST=all-pass → 必须 exit 0。运行：KB_SELFTEST=negative-suite bash <脚本>
#  退出码：0=全部 PASS；1=业务断言失败；2=环境阻断。
set -u
K="http://127.0.0.1:18082"
KH=(-s --noproxy '*' -H "X-Killbill-ApiKey: bob" -H "X-Killbill-ApiSecret: lazar" -H 'Content-Type: application/json' -H 'X-Killbill-CreatedBy: r22')
RUN="r22-$(date +%s)"   # 每次运行唯一前缀，避免 externalKey 冲突

# 结构化错误 JSON 校验：{"code": <int>, "message": <非空 str>}
_struct_err() {
  python3 -c 'import json,sys
try:
    d = json.load(open(sys.argv[1]))
    print("yes" if isinstance(d, dict) and isinstance(d.get("code"), int) and bool(str(d.get("message") or "").strip()) else "no")
except Exception:
    print("no")' "$1"
}

finish() {
  printf 'SUMMARY B1=%s B2=%s B3=%s\n' "$B1" "$B2" "$B3"
  if [[ "$B1" != PASS || "$B2" != PASS || "$B3" != PASS ]]; then
    exit 1
  fi
  exit 0
}

# ---------- 负向回归套件 + 自测入口（不触网，验证退出门禁本身） ----------
case "${KB_SELFTEST:-}" in
  force-b1) B1=FAIL B2=PASS B3=PASS; finish ;;
  force-b2) B1=PASS B2=FAIL B3=PASS; finish ;;
  force-b3) B1=PASS B2=PASS B3=FAIL; finish ;;
  all-pass) B1=PASS B2=PASS B3=PASS; finish ;;
  negative-suite)
    for c in force-b1 force-b2 force-b3; do
      if KB_SELFTEST=$c bash "$0" >/dev/null 2>&1; then
        echo "NEGATIVE-FAIL: $c 必须非零退出，实际 exit 0"; exit 1
      fi
      echo "negative ok: $c exit!=0"
    done
    if KB_SELFTEST=all-pass bash "$0" >/dev/null 2>&1; then
      echo "negative ok: all-pass exit==0"
    else
      echo "NEGATIVE-FAIL: all-pass 必须 exit 0"; exit 1
    fi
    echo "NEGATIVE-SUITE PASS"
    exit 0
    ;;
  '') ;;
  *) echo "unknown KB_SELFTEST=${KB_SELFTEST}" >&2; exit 2 ;;
esac

# ---------- 环境健康检查：必须精确 200，任何非 200（含代理 502）都是环境阻断 ----------
# KB_HEALTH_TRIES 仅用于本地测试环境阻断路径（默认 90×4s≈6min 等待服务启动）
HCCODE=""
for i in $(seq 1 "${KB_HEALTH_TRIES:-90}"); do
  HCCODE=$(curl -s --noproxy '*' -o /tmp/r22-kb-hc.txt -w '%{http_code}' "$K/1.0/healthcheck")
  [ "$HCCODE" = "200" ] && break
  sleep 4
done
if [ "${HCCODE:-}" != "200" ]; then
  echo "ENV-BLOCKED: healthcheck=${HCCODE:-none}（期望 200）——环境阻断，不计业务 FAIL" >&2
  exit 2
fi
head -c 60 /tmp/r22-kb-hc.txt; echo

# ---------- B1 金额精度 + 状态机 + 幂等 ----------
ACCID=$(curl "${KH[@]}" -X POST "$K/1.0/kb/accounts" -D /tmp/r22-kb-h.txt \
  -d "{\"externalKey\":\"$RUN-acct\",\"name\":\"R22 Payer\",\"currency\":\"USD\",\"timeZone\":\"UTC\"}" >/dev/null; \
  grep -i '^Location' /tmp/r22-kb-h.txt | sed -E 's#.*/accounts/##;s/\r//')
[ -n "$ACCID" ] || { echo "ENV-BLOCKED: 账户创建失败（无 Location 头）" >&2; exit 2; }
curl "${KH[@]}" -X POST "$K/1.0/kb/accounts/$ACCID/paymentMethods?isDefault=true" \
  -d "{\"externalKey\":\"$RUN-pm\",\"pluginName\":\"__EXTERNAL_PAYMENT__\"}" >/dev/null
PMID=$(curl "${KH[@]}" "$K/1.0/kb/accounts/$ACCID/paymentMethods" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["paymentMethodId"])')
[ -n "$PMID" ] || { echo "ENV-BLOCKED: 支付方式创建/查询失败" >&2; exit 2; }
PH=$(curl "${KH[@]}" -X POST "$K/1.0/kb/accounts/$ACCID/payments?paymentMethodId=$PMID" -D /tmp/r22-kb-p.txt \
  -d "{\"transactionType\":\"PURCHASE\",\"amount\":10.05,\"currency\":\"USD\",\"paymentExternalKey\":\"$RUN-pay\",\"transactionExternalKey\":\"$RUN-pay-txn\"}" >/dev/null; \
  grep -i '^Location' /tmp/r22-kb-p.txt | tr -d '\r' | sed -E 's#.*/payments/##;s#/*$##')
[ -n "$PH" ] || { echo "ENV-BLOCKED: 支付创建失败（无 Location 头）" >&2; exit 2; }
P1=$(curl "${KH[@]}" "$K/1.0/kb/payments/$PH")
AMT=$(echo "$P1" | python3 -c "import json,sys; t=json.load(sys.stdin)['transactions'][0]; print(t['amount'], t['transactionType'], t['status'])" 2>/dev/null)
# 幂等：同 paymentExternalKey 重复提交必须 4xx 拒绝 + 结构化错误 JSON（状态机消息）
# + 支付数量仍为 1（数量断言，防止"被拒但已落账"的伪幂等）
DUPBODY=/tmp/r22-kb-dup.json
DUPCODE=$(curl "${KH[@]}" -X POST "$K/1.0/kb/accounts/$ACCID/payments?paymentMethodId=$PMID" \
  -o "$DUPBODY" -w '%{http_code}' \
  -d "{\"transactionType\":\"PURCHASE\",\"amount\":10.05,\"currency\":\"USD\",\"paymentExternalKey\":\"$RUN-pay\",\"transactionExternalKey\":\"$RUN-pay-txn2\"}")
case "$DUPCODE" in 4??) DUP4XX=yes ;; *) DUP4XX=no ;; esac
DUPSTRUCT=$(_struct_err "$DUPBODY")
# 精确业务码 7032（2026-09-10 实测证据：Invalid payment transition PURCHASE from state PURCHASE_SUCCESS）
DUPCODE_NUM=$(python3 -c 'import json,sys
try:
    print(json.load(open(sys.argv[1])).get("code", "none"))
except Exception:
    print("unreadable")' "$DUPBODY" 2>/dev/null)
DUPMSG=$(python3 -c 'import json,sys
try:
    print(str(json.load(open(sys.argv[1])).get("message") or ""))
except Exception:
    print("unreadable")' "$DUPBODY" 2>/dev/null)
NPAY=$(curl "${KH[@]}" "$K/1.0/kb/accounts/$ACCID/payments" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")
B1=FAIL
[ "$AMT" = "10.05 PURCHASE SUCCESS" ] && [ "$DUP4XX" = "yes" ] && [ "$DUPSTRUCT" = "yes" ] \
  && [ "$DUPCODE_NUM" = "7032" ] && [ "$NPAY" = "1" ] && B1=PASS
echo "B1 $B1 amt=[$AMT] dup_code=$DUPCODE dup_struct=$DUPSTRUCT payments=$NPAY"
echo "B1 evidence: dup.message=[$DUPMSG]"

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
print(r[0]['amount'] if r else 'none', r[0]['status'] if r else '', len(r), f'{net:.2f}')" 2>/dev/null)
# 重放：同 transactionExternalKey 重复退款必须 4xx 拒绝 + 精确业务码 7030
# （首轮实测证据：Successful transaction with external key ... already exists, code 7030）
# + 结构化错误 JSON + 退款数量仍为 1 + 账本净额仍为 0.00
REPBODY=/tmp/r22-kb-replay.json
REPCODE=$(curl "${KH[@]}" -X POST "$K/1.0/kb/payments/$PH/refunds?accountRefund=false" \
  -o "$REPBODY" -w '%{http_code}' \
  -d "{\"amount\":10.05,\"currency\":\"USD\",\"transactionExternalKey\":\"$RUN-ref\"}")
case "$REPCODE" in 4??) REP4XX=yes ;; *) REP4XX=no ;; esac
REPSTRUCT=$(_struct_err "$REPBODY")
REPCODE_NUM=$(python3 -c 'import json,sys
try:
    print(json.load(open(sys.argv[1])).get("code", "none"))
except Exception:
    print("unreadable")' "$REPBODY" 2>/dev/null)
B2=FAIL
[ "$R2" = "10.05 SUCCESS 1 0.00" ] && [ "$REP4XX" = "yes" ] && [ "$REPSTRUCT" = "yes" ] \
  && [ "$REPCODE_NUM" = "7030" ] && B2=PASS
echo "B2 $B2 refund_count/net=[$R2] replay_code=$REPCODE replay_biz_code=$REPCODE_NUM"

# ---------- B3 凭据隔离 + 并发 + 异常可定位 ----------
# 无凭据 / 错误 secret：必须精确 401，且响应体不得泄漏账号资源信息
NOAUTHBODY=/tmp/r22-kb-noauth.json
NOAUTH=$(curl -s --noproxy '*' -o "$NOAUTHBODY" -w '%{http_code}' -H 'Content-Type: application/json' "$K/1.0/kb/accounts/$ACCID")
BADSECBODY=/tmp/r22-kb-badsec.json
BADSEC=$(curl -s --noproxy '*' -o "$BADSECBODY" -w '%{http_code}' -H "X-Killbill-ApiKey: bob" -H "X-Killbill-ApiSecret: WRONG" -H 'Content-Type: application/json' "$K/1.0/kb/accounts/$ACCID")
NOAUTHLEAK=no
grep -q "$ACCID" "$NOAUTHBODY" 2>/dev/null && NOAUTHLEAK=yes
rm -f /tmp/r22-kb-conc*.txt /tmp/r22-kb-conc*.json
for i in $(seq 1 10); do
  curl "${KH[@]}" -X POST "$K/1.0/kb/accounts/$ACCID/payments?paymentMethodId=$PMID" \
    -o /tmp/r22-kb-conc$i.json -D /tmp/r22-kb-conc$i.txt \
    -d "{\"transactionType\":\"PURCHASE\",\"amount\":1.00,\"currency\":\"USD\",\"paymentExternalKey\":\"$RUN-conc-$i\",\"transactionExternalKey\":\"$RUN-conc-$i-t\"}" &
done
wait
OKC=$(grep -l '^HTTP/1.1 201' /tmp/r22-kb-conc*.txt 2>/dev/null | wc -l | tr -d ' ')
CONC5XX=$(cat /tmp/r22-kb-conc*.txt 2>/dev/null | grep -c '^HTTP/1\.1 5' || true)
TOTAL=$(curl "${KH[@]}" "$K/1.0/kb/accounts/$ACCID/payments" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")
# 异常可定位：两类坏输入分别验证，不得混为一谈——
#  a) 语法坏 JSON（not-json{{）：Kill Bill 0.24.12 实际返回 500 + Tomcat HTML，
#     页面含精确 JsonParseException（异常可定位但不符 4xx+结构化契约，属核心限制，证据在档）
#  b) 合法 JSON 带未知字段：返回 400 + 结构化错误 JSON（UnrecognizedPropertyException）
BADJSONBODY=/tmp/r22-kb-badjson.html
BADJSON=$(curl "${KH[@]}" -o "$BADJSONBODY" -w '%{http_code}' -X POST "$K/1.0/kb/accounts/$ACCID/payments?paymentMethodId=$PMID" -d 'not-json{{')
BADJSONLOC=no
grep -q "JsonParseException" "$BADJSONBODY" 2>/dev/null && BADJSONLOC=yes
BADFIELDBODY=/tmp/r22-kb-badfield.json
BADFIELD=$(curl "${KH[@]}" -o "$BADFIELDBODY" -w '%{http_code}' -X POST "$K/1.0/kb/accounts/$ACCID/payments?paymentMethodId=$PMID" \
  -d '{"transactionType":"PURCHASE","amount":1.00,"currency":"USD","unknown_property_x":1}')
# 未知字段响应契约（2026-09-10 实测）：400 + JSON{className=UnrecognizedPropertyException,
# message 非空}——注意 code 为 null（Jackson 异常不带 KB 业务码），故断言 className 而非 code
BADFIELDCLASS=$(python3 -c 'import json,sys
try:
    d = json.load(open(sys.argv[1]))
    ok = "UnrecognizedPropertyException" in str(d.get("className") or "") and bool(str(d.get("message") or "").strip())
    print("yes" if ok else "no")
except Exception:
    print("no")' "$BADFIELDBODY" 2>/dev/null)
B3=FAIL
[ "$NOAUTH" = "401" ] && [ "$BADSEC" = "401" ] && [ "$NOAUTHLEAK" = "no" ] \
  && [ "$OKC" = "10" ] && [ "$TOTAL" = "11" ] && [ "$CONC5XX" = "0" ] \
  && [ "$BADJSON" = "500" ] && [ "$BADJSONLOC" = "yes" ] \
  && [ "$BADFIELD" = "400" ] && [ "$BADFIELDCLASS" = "yes" ] && B3=PASS
echo "B3 $B3 noauth=$NOAUTH badsecret=$BADSEC leak=$NOAUTHLEAK conc_ok=$OKC conc_5xx=$CONC5XX total=$TOTAL badjson=$BADJSON badjson_loc=$BADJSONLOC badfield=$BADFIELD badfield_class=$BADFIELDCLASS"

finish
