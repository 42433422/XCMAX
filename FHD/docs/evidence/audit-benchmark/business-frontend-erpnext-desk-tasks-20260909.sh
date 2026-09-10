#!/bin/bash
# R22 business-frontend 域开源锚点实测：ERPNext Desk（HTTP API 层）任务集 B1-B3
# B1 登录后核心业务任务+输入校验+空状态；B2 加载/失败/健康/结果状态来自真实服务；B3 筛选/编辑/导出语义一致
set -u
B="http://127.0.0.1:18081"; HOST="r22.localhost"; CK=/tmp/r22-desk-ck.txt
U=Administrator; P=r22pass123
API=(-s --noproxy '*' -H "Host: $HOST" -b "$CK" -c "$CK")

rm -f "$CK"
LOGIN=$(curl "${API[@]}" -X POST "$B/api/method/login" -H 'Content-Type: application/json' -d "{\"usr\":\"$U\",\"pwd\":\"$P\"}")
echo "$LOGIN" | grep -qi '"message":"logged in"' || { echo "LOGIN FAIL: $LOGIN"; exit 1; }

# ---------- B1 核心业务任务 + 输入校验 + 空状态 ----------
# 1a 确保物料存在（建单核心任务的前置）
curl "${API[@]}" -X POST "$B/api/method/frappe.client.get" -H 'Content-Type: application/json' \
  -d "{\"reference_doctype\":\"Item\",\"name\":\"R22-BENCH-ITEM\"}" | grep -q '"exc_type"' && {
  curl "${API[@]}" -X POST "$B/api/method/frappe.client.insert" -H 'Content-Type: application/json' -d '{
    "doc":{"doctype":"Item","item_code":"R22-BENCH-ITEM","item_name":"R22 Bench Item","stock_uom":"Nos","is_sales_item":1,"is_stock_item":0,"item_group":"All Item Groups"}}' > /dev/null
}
# 1b 核心任务：Desk API 建销售订单
CUST=$(curl "${API[@]}" "$B/api/method/frappe.client.get_list?doctype=Customer&limit_page_length=1&fields=%5B%22name%22%5D" | python3 -c "import json,sys; print(json.load(sys.stdin)['message'][0]['name'])")
SO=$(curl "${API[@]}" -X POST "$B/api/method/frappe.client.insert" -H 'Content-Type: application/json' -d "{
  \"doc\":{\"doctype\":\"Sales Order\",\"customer\":\"$CUST\",\"company\":\"R22 Bench Co\",\"order_type\":\"Sales\",
         \"delivery_date\":\"2026-09-30\",
         \"items\":[{\"item_code\":\"R22-BENCH-ITEM\",\"qty\":3,\"rate\":100}]}}")
SONAME=$(echo "$SO" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('message',{}).get('name',''))" 2>/dev/null)
[ -z "$SONAME" ] && SONAME=$(echo "$SO" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('message',{}).get('data',{}).get('name',''))" 2>/dev/null)
# 1c 输入校验：不存在的物料建单必须被服务端拒绝
BAD=$(curl "${API[@]}" -X POST "$B/api/method/frappe.client.insert" -H 'Content-Type: application/json' -d "{
  \"doc\":{\"doctype\":\"Sales Order\",\"customer\":\"$CUST\",\"company\":\"R22 Bench Co\",\"delivery_date\":\"2026-09-30\",
         \"items\":[{\"item_code\":\"NO-SUCH-ITEM-9999\",\"qty\":1,\"rate\":1}]}" | grep -cE '"exc_type"|"ValidationError"|not found')
# 1d 输入校验：数量为 0 的订单行被拒（服务端校验，非前端）
Q0=$(curl "${API[@]}" -X POST "$B/api/method/frappe.client.insert" -H 'Content-Type: application/json' -d "{
  \"doc\":{\"doctype\":\"Sales Order\",\"customer\":\"$CUST\",\"company\":\"R22 Bench Co\",\"delivery_date\":\"2026-09-30\",
         \"items\":[{\"item_code\":\"R22-BENCH-ITEM\",\"qty\":0,\"rate\":1}]}" | grep -cE '"exc_type"')
# 1e 空状态：不存在的筛选条件返回空列表（不是报错）
EMPTY=$(curl "${API[@]}" "$B/api/method/frappe.client.get_list?doctype=Sales+Order&filters=%5B%5B%22Sales+Order%22%2C%22name%22%2C%22%3D%22%2C%22SO-NONEXISTENT-R22%22%5D%5D" | grep -c '"message":\[\]')
B1=FAIL
[ -n "$SONAME" ] && [ "$BAD" -ge 1 ] && [ "$Q0" -ge 1 ] && [ "$EMPTY" -ge 1 ] && B1=PASS
echo "B1 $B1 so=$SONAME bad_item=$BAD qty0=$Q0 empty=$EMPTY"

# ---------- B2 加载/失败/健康/结果状态来自真实服务 ----------
# 2a 健康：ping 返回 200（真实服务探针）
PING=$(curl "${API[@]}" -o /dev/null -w '%{http_code}' "$B/api/method/ping")
# 2b 失败状态：不存在的 DocType 查询返回服务端错误（不是前端伪造）
FAILSTATE=$(curl "${API[@]}" "$B/api/method/frappe.client.get_list?doctype=NoSuchDocTypeR22" | grep -cE '"exc_type"|"http_status_code": 4')
# 2c 结果状态：列表 total_count 与真实 DB 行数一致（服务端计算）
LIST=$(curl "${API[@]}" "$B/api/method/frappe.client.get_list?doctype=Sales+Order&limit_page_length=0&fields=%5B%22name%22%5D")
NAPI=$(echo "$LIST" | python3 -c "import json,sys; print(len(json.load(sys.stdin)['message']))")
NDB=$(docker exec r22-erpnext-backend-1 bash -c "cd /home/frappe/frappe-bench && bench --site r22.localhost execute frappe.db.count --args '[\"Sales Order\"]'" 2>/dev/null | tr -d '\r')
# 2d 未登录状态真实拒绝（删 cookie 后核心 API 401/403）
curl "${API[@]}" -o /dev/null "$B/api/method/login" 2>/dev/null
NOAUTH=$(curl -s --noproxy '*' -H "Host: $HOST" "$B/api/method/frappe.client.get_list?doctype=Sales+Order&limit_page_length=1" | grep -cE '"exc_type"|"http_status_code": (401|403)')
curl "${API[@]}" -X POST "$B/api/method/login" -H 'Content-Type: application/json' -d "{\"usr\":\"$U\",\"pwd\":\"$P\"}" > /dev/null
B2=FAIL
[ "$PING" = "200" ] && [ "$FAILSTATE" -ge 1 ] && [ "$NAPI" = "$NDB" ] && [ "$NOAUTH" -ge 1 ] && B2=PASS
echo "B2 $B2 ping=$PING failstate=$FAILSTATE api=$NAPI db=$NDB noauth=$NOAUTH"

# ---------- B3 筛选/编辑/导出语义一致 ----------
# 3a 编辑：改订单 po_no 后重新加载值一致
MARK="R22-PO-$SONAME"
curl "${API[@]}" -X POST "$B/api/method/frappe.client.set_value" -H 'Content-Type: application/json' \
  -d "{\"doctype\":\"Sales Order\",\"name\":\"$SONAME\",\"fieldname\":\"po_no\",\"value\":\"$MARK\"}" > /dev/null
RELOAD=$(curl "${API[@]}" -X POST "$B/api/method/frappe.client.get" -H 'Content-Type: application/json' \
  -d "{\"doctype\":\"Sales Order\",\"name\":\"$SONAME\"}" | grep -c "$MARK")
# 3b 筛选：按 name 精确筛选命中且仅命中该单
FILT=$(curl "${API[@]}" "$B/api/method/frappe.client.get_list?doctype=Sales+Order&filters=%5B%5B%22Sales+Order%22%2C%22name%22%2C%22%3D%22%2C%22$SONAME%22%5D%5D&fields=%5B%22name%22%5D")
FILT_OK=$(echo "$FILT" | python3 -c "import json,sys; m=json.load(sys.stdin)['message']; print(1 if len(m)==1 and m[0]['name']=='$SONAME' else 0)")
# 3c 导出：真实数据导出（export_data）含编辑后的标记（与 DB 一致）
curl "${API[@]}" -o /tmp/r22-desk-export.csv "$B/api/method/frappe.core.doctype.data_export.exporter.export_data?doctype=Sales%20Order&format=CSV" 2>/dev/null
head -c 400 /tmp/r22-desk-export.csv > /tmp/r22-desk-export-sample.txt
grep -q "$MARK" /tmp/r22-desk-export.csv && EXPOK=1 || EXPOK=0
B3=FAIL
[ "$RELOAD" -ge 1 ] && [ "$FILT_OK" = "1" ] && [ "$EXPOK" = "1" ] && B3=PASS
echo "B3 $B3 reload=$RELOAD filt=$FILT_OK export_ok=$EXPOK"

echo "SUMMARY B1=$B1 B2=$B2 B3=$B3"
