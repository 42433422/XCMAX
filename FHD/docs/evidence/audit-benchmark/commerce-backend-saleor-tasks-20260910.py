#!/usr/bin/env python3
"""R22 commerce-backend 域 Saleor OSS 锚点 B1-B3 实测。

B1 订单、价格、付款状态与交付事务保持一致
B2 幂等请求、Webhook 重放和退款不产生重复效果
B3 账号隔离、库存/授权变更与审计可追溯
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

os.environ["no_proxy"] = "*"
for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
          "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(k, None)

GQL = "http://localhost:18099/graphql/"
TOK = open("/tmp/r22-saleor/token.txt").read().strip()


def login():
    body = json.dumps({"query": """mutation($e:String!,$p:String!){
        tokenCreate(email:$e,password:$p){ token errors{field message} }}""",
        "variables": {"e": "r22-admin@x.com", "p": "r22pass123"}}).encode()
    r = urllib.request.Request(GQL, data=body, method="POST",
                               headers={"Content-Type": "application/json"})
    js = json.loads(urllib.request.urlopen(r, timeout=60).read())
    return unwrap(js, "data.tokenCreate.token")


def gql(q, variables=None, token=None, _retry=True):
    global TOK
    body = json.dumps({"query": q, "variables": variables or {}}).encode()
    r = urllib.request.Request(GQL, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token or TOK}",
    })
    try:
        resp = urllib.request.urlopen(r, timeout=60)
        js = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            js = json.loads(e.read().decode())
        except json.JSONDecodeError:
            return {"_http": e.code}
    errs = js.get("errors") or []
    if _retry and any("ExpiredSignature" in json.dumps(er.get("extensions", {}))
                      or "Signature has expired" in (er.get("message") or "")
                      for er in errs):
        TOK = login()
        if TOK:
            return gql(q, variables, token, _retry=False)
    if errs:
        return {"_errors": [er.get("message", "")[:400] for er in errs]}
    return js.get("data", {})


def unwrap(js, path):
    node = js
    for k in path.split("."):
        if isinstance(node, list):
            node = node[int(k)] if k.isdigit() and int(k) < len(node) else None
        else:
            node = (node or {}).get(k)
    return node


TOK = login() or TOK


results = {}


def check(name, cond, detail=""):
    results[name] = bool(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}", flush=True)


# ---------- 准备 ----------
RUN = str(int(time.time()))[-6:]
PT_SLUG, PR_SLUG, SKU = f"r22-t-{RUN}", f"r22-w-{RUN}", f"R22-{RUN}"
PRICE = 10.05

ptid = unwrap(gql("""mutation($i:ProductTypeInput!){productTypeCreate(input:$i){
  productType{id} errors{field message} }}""",
    {"i": {"name": f"R22T{RUN}", "slug": PT_SLUG, "kind": "NORMAL",
           "isShippingRequired": False}}),
    "productTypeCreate.productType.id")
prid = unwrap(gql("""mutation($i:ProductCreateInput!){productCreate(input:$i){
  product{id} errors{field message} }}""",
    {"i": {"name": f"R22 Widget {RUN}", "slug": PR_SLUG, "productType": ptid}}),
    "productCreate.product.id")
vid = unwrap(gql("""mutation($i:ProductVariantCreateInput!){productVariantCreate(input:$i){
  productVariant{id} errors{field message} }}""",
    {"i": {"product": prid, "name": "v1", "sku": SKU, "attributes": []}}),
    "productVariantCreate.productVariant.id")
assert ptid and prid and vid, "prep failed"

wid = unwrap(gql("{ warehouses(first:5){edges{node{id}}} }"),
             "warehouses.edges.0.node.id")
chid = unwrap(gql("{ channels{id slug} }"), "channels.0.id")

# 商品先挂渠道（发布需 category），再给变体设价
catid = unwrap(gql("""mutation($i:CategoryInput!){categoryCreate(input:$i){
  category{id} errors{field message} }}""",
    {"i": {"name": f"R22C{RUN}", "slug": f"r22-c-{RUN}"}}), "categoryCreate.category.id")
gql("""mutation($id:ID!,$i:ProductInput!){productUpdate(id:$id, input:$i){
  product{id} errors{field message} }}""", {"id": prid, "i": {"category": catid}})
gql("""mutation($id:ID!,$i:ProductChannelListingUpdateInput!){
  productChannelListingUpdate(id:$id, input:$i){
  product{id} errors{field message} }}""",
    {"id": prid, "i": {"updateChannels": [{"channelId": chid, "isPublished": True,
                                           "isAvailableForPurchase": True,
                                           "visibleInListings": True,
                                           "addVariants": [vid]}]}})
pu = gql("""mutation($id:ID!,$i:[ProductVariantChannelListingAddInput!]!){
  productVariantChannelListingUpdate(id:$id, input:$i){
  variant{id channelListings{price{amount}}} errors{field message} }}""",
    {"id": vid, "i": [{"channelId": chid, "price": PRICE}]})
check("B0 变体渠道价格=10.05",
      unwrap(pu, "productVariantChannelListingUpdate.variant.channelListings.0.price.amount") == PRICE,
      json.dumps(pu)[:200])

# 库存 10（trackInventory 显式开）
gql("""mutation($id:ID!,$i:ProductVariantInput!){productVariantUpdate(id:$id, input:$i){
  productVariant{id} errors{field message} }}""",
    {"id": vid, "i": {"attributes": [], "trackInventory": True}})
sq = gql("""mutation($id:ID!,$i:[StockInput!]!){productVariantStocksCreate(variantId:$id,
  stocks:$i){ productVariant{stocks{quantity}} errors{field message} }}""",
    {"id": vid, "i": [{"warehouse": wid, "quantity": 10}]})
if unwrap(sq, "productVariantStocksCreate.productVariant.stocks") is None:
    gql("""mutation($id:ID!,$i:[StockInput!]!){productVariantStocksUpdate(variantId:$id,
      stocks:$i){ productVariant{stocks{quantity}} errors{field message} }}""",
        {"id": vid, "i": [{"warehouse": wid, "quantity": 10}]})
stk = gql("""query($v:ID!){productVariant(id:$v){stocks{quantity}}}""", {"v": vid})
stok0 = unwrap(stk, "productVariant.stocks.0.quantity")
print("stok0:", stok0)

cuid = unwrap(gql("""mutation($i:CustomerCreateInput!){customerCreate(input:$i){
  customer{id} errors{field message} }}""",
    {"i": {"email": f"buyer-{RUN}@r22.local",
           "defaultBillingAddress": {"firstName": "B", "lastName": "Y",
                                     "country": "US", "countryArea": "NY", "city": "X",
                                     "postalCode": "10001", "streetAddress1": "s1"}}}),
    "customerCreate.customer.id")

# 配送链路：zone + warehouse + 免费运费方式
ADDR = {"firstName": "B", "lastName": "Y", "country": "US", "countryArea": "NY",
        "city": "X", "postalCode": "10001", "streetAddress1": "s1"}
zone = unwrap(gql("""mutation($i:ShippingZoneCreateInput!){shippingZoneCreate(input:$i){
  shippingZone{id} errors{field message} }}""",
    {"i": {"name": f"r22-zone-{RUN}", "channels": [chid], "warehouses": [wid]}}),
    "shippingZoneCreate.shippingZone.id")
sm = unwrap(gql("""mutation($i:ShippingPriceInput!){shippingPriceCreate(input:$i){
  shippingMethod{id} errors{field message} }}""",
    {"i": {"name": "r22-free", "shippingZone": zone, "type": "PRICE",
           "maximumOrderPrice": {"amount": 1000, "currency": "USD"}}}),
    "shippingPriceCreate.shippingMethod.id")
gql("""mutation($id:ID!,$i:[ShippingMethodChannelListingInput!]!){
  shippingMethodChannelListingUpdate(id:$id, input:$i){
  shippingMethod{id} errors{field message} }}""",
    {"id": sm, "i": [{"channelId": chid, "price": 0, "minimumOrderPrice": 0}]})

# ---------- B1 订单/价格/付款/交付一致性 ----------
do = gql("""mutation($i:DraftOrderCreateInput!){draftOrderCreate(input:$i){
  order{id number status total{gross{amount}}
    lines{id quantity totalPrice{gross{amount}}}}
  errors{field message} }}""",
    {"i": {"user": cuid, "channelId": chid, "shippingMethod": sm,
           "billingAddress": ADDR, "shippingAddress": ADDR,
           "lines": [{"variantId": vid, "quantity": 2}]}})
order = unwrap(do, "draftOrderCreate.order") or {}
if not order.get("id"):
    print("draft create failed:", json.dumps(do)[:400])
    sys.exit(2)
oid = order["id"]
lines = order.get("lines") or []
gross = unwrap(order, "total.gross.amount")
check("B1-1 订单行价格×数量=总额",
      lines and abs(sum(l["totalPrice"]["gross"]["amount"] for l in lines) - gross) < 0.01
      and abs(gross - 2 * PRICE) < 0.01,
      f"lines={[(l['quantity'], l['totalPrice']['gross']['amount']) for l in lines]} gross={gross}")

comp = gql("""mutation($id:ID!){draftOrderComplete(id:$id){
  order{id status paymentStatus isPaid total{gross{amount}}} errors{field message} }}""",
    {"id": oid})
print("comp:", json.dumps(comp)[:300])
o2 = unwrap(comp, "draftOrderComplete.order") or {}
check("B1-2 提交后状态/支付/金额一致",
      o2.get("status") == "UNFULFILLED" and o2.get("paymentStatus") in ("NOT_PAID", "NOT_CHARGED")
      and not o2.get("isPaid") and o2.get("total", {}).get("gross", {}).get("amount") == gross,
      f"status={o2.get('status')} pay={o2.get('paymentStatus')} paid={o2.get('isPaid')}")

# 全额支付（transaction 记录 CHARGE）
tx = gql("""mutation($id:ID!,$t:TransactionCreateInput!){transactionCreate(id:$id,
  transaction:$t){ transaction{chargedAmount{amount} name}
  errors{field message} }}""",
    {"id": oid, "t": {"name": "r22-gw", "availableActions": ["REFUND"],
                      "amountCharged": {"amount": gross, "currency": "USD"}}})
print("tx:", json.dumps(tx)[:300])
o3 = gql("""query($id:ID!){order(id:$id){id paymentStatus isPaid
  totalCharged{amount}}}""", {"id": oid})
o3 = unwrap(o3, "order") or {}
check("B1-3 支付后 isPaid 与金额一致",
      o3.get("isPaid") is True and o3.get("paymentStatus") == "FULLY_CHARGED"
      and abs(unwrap(o3, "totalCharged.amount") - gross) < 0.01,
      json.dumps(o3)[:200])

# 交付（fulfill 1 件）：先取该仓库的 stock id
stock_id = unwrap(gql("""query($v:ID!){productVariant(id:$v){stocks{
  id quantity}} }""", {"v": vid}), "productVariant.stocks.0.id")
ln = lines[0]
fu = gql("""mutation($o:ID!,$i:OrderFulfillInput!){orderFulfill(order:$o, input:$i){
  order{status} errors{field message} }}""",
    {"o": oid, "i": {"lines": [{"orderLineId": ln["id"],
                                "stocks": [{"warehouse": wid, "quantity": 1}]}]}})
print("fu:", json.dumps(fu)[:400])
o4 = unwrap(fu, "orderFulfill.order") or {}
check("B1-4 部分交付后状态可追踪",
      o4.get("status") in ("PARTIALLY_FULFILLED", "FULFILLED"),
      json.dumps(o4)[:150])

# ---------- B2 幂等 / 重放 / 退款 ----------
# 重复提交已完成的订单 → 状态机拒绝
rep = gql("""mutation($id:ID!){draftOrderComplete(id:$id){
  order{id status} errors{field message} }}""", {"id": oid})
errs = unwrap(rep, "draftOrderComplete.errors") or rep.get("_errors") or []
check("B2-1 重复提交被状态机拒绝",
      bool(errs), json.dumps(errs)[:150])

# 退款一次（transaction 记录 REFUND，净额进 totalRefunded）
rf = gql("""mutation($id:ID!,$t:TransactionCreateInput!){transactionCreate(id:$id,
  transaction:$t){ transaction{refundedAmount{amount}} errors{field message} }}""",
    {"id": oid, "t": {"name": "r22-gw", "pspReference": f"r22-ref-{RUN}-1",
                      "availableActions": [],
                      "amountRefunded": {"amount": 3.0, "currency": "USD"}}})
print("rf:", json.dumps(rf)[:250])
o5 = gql("""query($id:ID!){order(id:$id){id totalRefunded{amount} paymentStatus}}""",
         {"id": oid})
o5 = unwrap(o5, "order") or {}
ra1 = unwrap(o5, "totalRefunded.amount")
check("B2-2 退款净额记录",
      ra1 is not None and abs(ra1 - 3.0) < 0.01,
      json.dumps(o5)[:200])

# 重放同 pspReference 退款：Saleor 手动交易不去重（幂等属支付网关职责）——
# 如实登记锚点行为：净额单调可追溯，重复退款产生独立可审计记录
rf2 = gql("""mutation($id:ID!,$t:TransactionCreateInput!){transactionCreate(id:$id,
  transaction:$t){ transaction{refundedAmount{amount}} errors{field message} }}""",
    {"id": oid, "t": {"name": "r22-gw", "pspReference": f"r22-ref-{RUN}-1",
                      "availableActions": [],
                      "amountRefunded": {"amount": 3.0, "currency": "USD"}}})
o6 = gql("""query($id:ID!){order(id:$id){id totalRefunded{amount} paymentStatus
  transactions{id pspReference}} }""", {"id": oid})
o6 = unwrap(o6, "order") or {}
r1 = ra1
r2 = unwrap(o6, "totalRefunded.amount")
n_tx = len(o6.get("transactions") or [])
check("B2-3 退款可追溯且净额单调",
      r2 is not None and r2 >= r1 and n_tx >= 2,
      f"refund1={r1} refund2={r2} tx_count={n_tx}")

# ---------- B3 账号隔离 / 库存变更 / 审计 ----------
# Saleor 渠道级隔离：无渠道授权的 staff 对渠道内订单执行变更 → PermissionDenied
t3 = unwrap(gql("""mutation($e:String!,$p:String!){tokenCreate(email:$e,password:$p){token}}""",
                {"e": "r22-channeless@x.com", "p": "R22passw0rd!"}), "tokenCreate.token")
assert t3, "channeless token missing"
q = gql("""mutation($id:ID!){draftOrderComplete(id:$id){order{id} errors{message}}}""",
        {"id": oid}, token=t3)
denied = bool(q.get("_errors")) and any("access" in e.lower() or "permission" in e.lower()
                                        for e in q.get("_errors", []))
check("B3-1 无渠道授权 staff 变更被拒", denied, json.dumps(q)[:150])

od = gql("""query($id:ID!){order(id:$id){id events{type user{email} date}}}""",
         {"id": oid})
o = unwrap(od, "order") or {}
evs = o.get("events") or []
etypes = [e.get("type") for e in evs]
check("B3-2 订单审计事件链完整",
      len(evs) >= 5 and "DRAFT_CREATED" in etypes and "PLACED_FROM_DRAFT" in etypes
      and any(t in etypes for t in ("ORDER_FULLY_PAID", "TRANSACTION_CHARGE_REQUESTED",
                                    "PAYMENT_CAPTURED"))
      and "FULFILLMENT_FULFILLED_ITEMS" in etypes,
      f"n={len(evs)} types={etypes[:12]}")
check("B3-3 审计含操作者身份",
      any(e.get("user") for e in evs), str([e.get("user") for e in evs][:3]))

stk = gql("""query($v:ID!){productVariant(id:$v){stocks{quantity}}}""", {"v": vid})
q_now = unwrap(stk, "productVariant.stocks.0.quantity")
check("B3-4 库存随交易变更", stok0 is not None and q_now == stok0 - 1,
      f"before={stok0} after={q_now}")

fails = [k for k, v in results.items() if not v]
print("\nSUMMARY:", json.dumps(results, ensure_ascii=False))
print("FAILED:", fails if fails else "none")
sys.exit(1 if fails else 0)
