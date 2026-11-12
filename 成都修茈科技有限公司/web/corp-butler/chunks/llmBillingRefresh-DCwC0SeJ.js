import { i as e, n as t, r as n, t as r } from '../corp-butler.js'
var i = n(`wallet`, () => {
  let n = e(null),
    r = e(null),
    i = e(!1),
    a = e(null),
    o = e(null)
  function s(e) {
    let t = Number(e)
    r.value = Number.isFinite(t) && t >= 0 ? Math.floor(t) : null
  }
  async function c(e = 2) {
    ;((i.value = !0), (a.value = null))
    for (let r = 0; r <= e; r++)
      try {
        let e = await t.balance(),
          r = Number(e?.balance)
        if (e && Number.isFinite(r))
          return (
            (n.value = r),
            s(e.membership_reference_yuan),
            (o.value = Date.now()),
            console.log(`[Wallet] 余额刷新成功: ¥${r.toFixed(2)}`),
            n.value
          )
        throw Error(`Invalid API response format`)
      } catch (t) {
        ;(console.warn(`[Wallet] 余额刷新失败 (尝试 ${r + 1}/${e + 1}):`, t),
          r < e
            ? await new Promise((e) => setTimeout(e, 1e3 * (r + 1)))
            : ((a.value = t instanceof Error ? t.message : String(t)), console.error(`[Wallet] 所有重试失败，余额设为 null`)))
      }
    return ((n.value = null), (r.value = null), null)
  }
  function l(e) {
    let t = Number(e)
    ;((n.value = Number.isFinite(t) ? t : null), n.value !== null && (o.value = Date.now()))
  }
  function u() {
    ;((n.value = null), (r.value = null), (a.value = null), (o.value = null))
  }
  return {
    balance: n,
    membershipReferenceYuan: r,
    loading: i,
    error: a,
    lastUpdated: o,
    refreshBalance: c,
    setBalance: l,
    setMembershipReferenceYuan: s,
    clear: u,
  }
})
function a() {
  queueMicrotask(() => {
    try {
      ;(r().refreshSession(!0), i().refreshBalance())
    } catch {}
  })
}
export { a as refreshLevelAndWalletAfterLlm }
