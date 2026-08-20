function e(e) {
  let t = Object.create(null)
  for (let n of e.split(`,`)) t[n] = 1
  return (e) => e in t
}
var t = {},
  n = [],
  r = () => {},
  i = () => !1,
  a = (e) => e.charCodeAt(0) === 111 && e.charCodeAt(1) === 110 && (e.charCodeAt(2) > 122 || e.charCodeAt(2) < 97),
  o = (e) => e.startsWith(`onUpdate:`),
  s = Object.assign,
  c = (e, t) => {
    let n = e.indexOf(t)
    n > -1 && e.splice(n, 1)
  },
  l = Object.prototype.hasOwnProperty,
  u = (e, t) => l.call(e, t),
  d = Array.isArray,
  f = (e) => x(e) === `[object Map]`,
  p = (e) => x(e) === `[object Set]`,
  m = (e) => x(e) === `[object Date]`,
  h = (e) => typeof e == `function`,
  g = (e) => typeof e == `string`,
  _ = (e) => typeof e == `symbol`,
  v = (e) => typeof e == `object` && !!e,
  y = (e) => (v(e) || h(e)) && h(e.then) && h(e.catch),
  b = Object.prototype.toString,
  x = (e) => b.call(e),
  S = (e) => x(e).slice(8, -1),
  C = (e) => x(e) === `[object Object]`,
  w = (e) => g(e) && e !== `NaN` && e[0] !== `-` && `` + parseInt(e, 10) === e,
  T = e(
    `,key,ref,ref_for,ref_key,onVnodeBeforeMount,onVnodeMounted,onVnodeBeforeUpdate,onVnodeUpdated,onVnodeBeforeUnmount,onVnodeUnmounted`,
  ),
  E = (e) => {
    let t = Object.create(null)
    return (n) => t[n] || (t[n] = e(n))
  },
  D = /-\w/g,
  O = E((e) => e.replace(D, (e) => e.slice(1).toUpperCase())),
  k = /\B([A-Z])/g,
  A = E((e) => e.replace(k, `-$1`).toLowerCase()),
  j = E((e) => e.charAt(0).toUpperCase() + e.slice(1)),
  ee = E((e) => (e ? `on${j(e)}` : ``)),
  M = (e, t) => !Object.is(e, t),
  te = (e, ...t) => {
    for (let n = 0; n < e.length; n++) e[n](...t)
  },
  N = (e, t, n, r = !1) => {
    Object.defineProperty(e, t, { configurable: !0, enumerable: !1, writable: r, value: n })
  },
  ne = (e) => {
    let t = parseFloat(e)
    return isNaN(t) ? e : t
  },
  re = (e) => {
    let t = g(e) ? Number(e) : NaN
    return isNaN(t) ? e : t
  },
  ie,
  ae = () =>
    (ie ||=
      typeof globalThis < `u` ? globalThis : typeof self < `u` ? self : typeof window < `u` ? window : typeof global < `u` ? global : {})
function oe(e) {
  if (d(e)) {
    let t = {}
    for (let n = 0; n < e.length; n++) {
      let r = e[n],
        i = g(r) ? ue(r) : oe(r)
      if (i) for (let e in i) t[e] = i[e]
    }
    return t
  } else if (g(e) || v(e)) return e
}
var se = /;(?![^(]*\))/g,
  ce = /:([^]+)/,
  le = /\/\*[^]*?\*\//g
function ue(e) {
  let t = {}
  return (
    e
      .replace(le, ``)
      .split(se)
      .forEach((e) => {
        if (e) {
          let n = e.split(ce)
          n.length > 1 && (t[n[0].trim()] = n[1].trim())
        }
      }),
    t
  )
}
function P(e) {
  let t = ``
  if (g(e)) t = e
  else if (d(e))
    for (let n = 0; n < e.length; n++) {
      let r = P(e[n])
      r && (t += r + ` `)
    }
  else if (v(e)) for (let n in e) e[n] && (t += n + ` `)
  return t.trim()
}
var de = `itemscope,allowfullscreen,formnovalidate,ismap,nomodule,novalidate,readonly`,
  fe = e(de)
de + ``
function pe(e) {
  return !!e || e === ``
}
function me(e, t) {
  if (e.length !== t.length) return !1
  let n = !0
  for (let r = 0; n && r < e.length; r++) n = he(e[r], t[r])
  return n
}
function he(e, t) {
  if (e === t) return !0
  let n = m(e),
    r = m(t)
  if (n || r) return n && r ? e.getTime() === t.getTime() : !1
  if (((n = _(e)), (r = _(t)), n || r)) return e === t
  if (((n = d(e)), (r = d(t)), n || r)) return n && r ? me(e, t) : !1
  if (((n = v(e)), (r = v(t)), n || r)) {
    if (!n || !r || Object.keys(e).length !== Object.keys(t).length) return !1
    for (let n in e) {
      let r = e.hasOwnProperty(n),
        i = t.hasOwnProperty(n)
      if ((r && !i) || (!r && i) || !he(e[n], t[n])) return !1
    }
  }
  return String(e) === String(t)
}
var ge = (e) => !!(e && e.__v_isRef === !0),
  F = (e) =>
    g(e)
      ? e
      : e == null
        ? ``
        : d(e) || (v(e) && (e.toString === b || !h(e.toString)))
          ? ge(e)
            ? F(e.value)
            : JSON.stringify(e, _e, 2)
          : String(e),
  _e = (e, t) =>
    ge(t)
      ? _e(e, t.value)
      : f(t)
        ? {
            [`Map(${t.size})`]: [...t.entries()].reduce((e, [t, n], r) => ((e[ve(t, r) + ` =>`] = n), e), {}),
          }
        : p(t)
          ? { [`Set(${t.size})`]: [...t.values()].map((e) => ve(e)) }
          : _(t)
            ? ve(t)
            : v(t) && !d(t) && !C(t)
              ? String(t)
              : t,
  ve = (e, t = ``) => (_(e) ? `Symbol(${e.description ?? t})` : e),
  ye,
  be = class {
    constructor(e = !1) {
      ;((this.detached = e),
        (this._active = !0),
        (this._on = 0),
        (this.effects = []),
        (this.cleanups = []),
        (this._isPaused = !1),
        (this.__v_skip = !0),
        (this.parent = ye),
        !e && ye && (this.index = (ye.scopes ||= []).push(this) - 1))
    }
    get active() {
      return this._active
    }
    pause() {
      if (this._active) {
        this._isPaused = !0
        let e, t
        if (this.scopes) for (e = 0, t = this.scopes.length; e < t; e++) this.scopes[e].pause()
        for (e = 0, t = this.effects.length; e < t; e++) this.effects[e].pause()
      }
    }
    resume() {
      if (this._active && this._isPaused) {
        this._isPaused = !1
        let e, t
        if (this.scopes) for (e = 0, t = this.scopes.length; e < t; e++) this.scopes[e].resume()
        for (e = 0, t = this.effects.length; e < t; e++) this.effects[e].resume()
      }
    }
    run(e) {
      if (this._active) {
        let t = ye
        try {
          return ((ye = this), e())
        } finally {
          ye = t
        }
      }
    }
    on() {
      ++this._on === 1 && ((this.prevScope = ye), (ye = this))
    }
    off() {
      if (this._on > 0 && --this._on === 0) {
        if (ye === this) ye = this.prevScope
        else {
          let e = ye
          for (; e; ) {
            if (e.prevScope === this) {
              e.prevScope = this.prevScope
              break
            }
            e = e.prevScope
          }
        }
        this.prevScope = void 0
      }
    }
    stop(e) {
      if (this._active) {
        this._active = !1
        let t, n
        for (t = 0, n = this.effects.length; t < n; t++) this.effects[t].stop()
        for (this.effects.length = 0, t = 0, n = this.cleanups.length; t < n; t++) this.cleanups[t]()
        if (((this.cleanups.length = 0), this.scopes)) {
          for (t = 0, n = this.scopes.length; t < n; t++) this.scopes[t].stop(!0)
          this.scopes.length = 0
        }
        if (!this.detached && this.parent && !e) {
          let e = this.parent.scopes.pop()
          e && e !== this && ((this.parent.scopes[this.index] = e), (e.index = this.index))
        }
        this.parent = void 0
      }
    }
  }
function xe(e) {
  return new be(e)
}
function Se() {
  return ye
}
function Ce(e, t = !1) {
  ye && ye.cleanups.push(e)
}
var I,
  we = new WeakSet(),
  Te = class {
    constructor(e) {
      ;((this.fn = e),
        (this.deps = void 0),
        (this.depsTail = void 0),
        (this.flags = 5),
        (this.next = void 0),
        (this.cleanup = void 0),
        (this.scheduler = void 0),
        ye && ye.active && ye.effects.push(this))
    }
    pause() {
      this.flags |= 64
    }
    resume() {
      this.flags & 64 && ((this.flags &= -65), we.has(this) && (we.delete(this), this.trigger()))
    }
    notify() {
      ;(this.flags & 2 && !(this.flags & 32)) || this.flags & 8 || ke(this)
    }
    run() {
      if (!(this.flags & 1)) return this.fn()
      ;((this.flags |= 2), He(this), Me(this))
      let e = I,
        t = Re
      ;((I = this), (Re = !0))
      try {
        return this.fn()
      } finally {
        ;(Ne(this), (I = e), (Re = t), (this.flags &= -3))
      }
    }
    stop() {
      if (this.flags & 1) {
        for (let e = this.deps; e; e = e.nextDep) Ie(e)
        ;((this.deps = this.depsTail = void 0), He(this), this.onStop && this.onStop(), (this.flags &= -2))
      }
    }
    trigger() {
      this.flags & 64 ? we.add(this) : this.scheduler ? this.scheduler() : this.runIfDirty()
    }
    runIfDirty() {
      Pe(this) && this.run()
    }
    get dirty() {
      return Pe(this)
    }
  },
  Ee = 0,
  De,
  Oe
function ke(e, t = !1) {
  if (((e.flags |= 8), t)) {
    ;((e.next = Oe), (Oe = e))
    return
  }
  ;((e.next = De), (De = e))
}
function Ae() {
  Ee++
}
function je() {
  if (--Ee > 0) return
  if (Oe) {
    let e = Oe
    for (Oe = void 0; e; ) {
      let t = e.next
      ;((e.next = void 0), (e.flags &= -9), (e = t))
    }
  }
  let e
  for (; De; ) {
    let t = De
    for (De = void 0; t; ) {
      let n = t.next
      if (((t.next = void 0), (t.flags &= -9), t.flags & 1))
        try {
          t.trigger()
        } catch (t) {
          e ||= t
        }
      t = n
    }
  }
  if (e) throw e
}
function Me(e) {
  for (let t = e.deps; t; t = t.nextDep) ((t.version = -1), (t.prevActiveLink = t.dep.activeLink), (t.dep.activeLink = t))
}
function Ne(e) {
  let t,
    n = e.depsTail,
    r = n
  for (; r; ) {
    let e = r.prevDep
    ;(r.version === -1 ? (r === n && (n = e), Ie(r), Le(r)) : (t = r),
      (r.dep.activeLink = r.prevActiveLink),
      (r.prevActiveLink = void 0),
      (r = e))
  }
  ;((e.deps = t), (e.depsTail = n))
}
function Pe(e) {
  for (let t = e.deps; t; t = t.nextDep)
    if (t.dep.version !== t.version || (t.dep.computed && (Fe(t.dep.computed) || t.dep.version !== t.version))) return !0
  return !!e._dirty
}
function Fe(e) {
  if (
    (e.flags & 4 && !(e.flags & 16)) ||
    ((e.flags &= -17), e.globalVersion === Ue) ||
    ((e.globalVersion = Ue), !e.isSSR && e.flags & 128 && ((!e.deps && !e._dirty) || !Pe(e)))
  )
    return
  e.flags |= 2
  let t = e.dep,
    n = I,
    r = Re
  ;((I = e), (Re = !0))
  try {
    Me(e)
    let n = e.fn(e._value)
    ;(t.version === 0 || M(n, e._value)) && ((e.flags |= 128), (e._value = n), t.version++)
  } catch (e) {
    throw (t.version++, e)
  } finally {
    ;((I = n), (Re = r), Ne(e), (e.flags &= -3))
  }
}
function Ie(e, t = !1) {
  let { dep: n, prevSub: r, nextSub: i } = e
  if (
    (r && ((r.nextSub = i), (e.prevSub = void 0)),
    i && ((i.prevSub = r), (e.nextSub = void 0)),
    n.subs === e && ((n.subs = r), !r && n.computed))
  ) {
    n.computed.flags &= -5
    for (let e = n.computed.deps; e; e = e.nextDep) Ie(e, !0)
  }
  !t && !--n.sc && n.map && n.map.delete(n.key)
}
function Le(e) {
  let { prevDep: t, nextDep: n } = e
  ;(t && ((t.nextDep = n), (e.prevDep = void 0)), n && ((n.prevDep = t), (e.nextDep = void 0)))
}
var Re = !0,
  ze = []
function Be() {
  ;(ze.push(Re), (Re = !1))
}
function Ve() {
  let e = ze.pop()
  Re = e === void 0 ? !0 : e
}
function He(e) {
  let { cleanup: t } = e
  if (((e.cleanup = void 0), t)) {
    let e = I
    I = void 0
    try {
      t()
    } finally {
      I = e
    }
  }
}
var Ue = 0,
  We = class {
    constructor(e, t) {
      ;((this.sub = e),
        (this.dep = t),
        (this.version = t.version),
        (this.nextDep = this.prevDep = this.nextSub = this.prevSub = this.prevActiveLink = void 0))
    }
  },
  Ge = class {
    constructor(e) {
      ;((this.computed = e),
        (this.version = 0),
        (this.activeLink = void 0),
        (this.subs = void 0),
        (this.map = void 0),
        (this.key = void 0),
        (this.sc = 0),
        (this.__v_skip = !0))
    }
    track(e) {
      if (!I || !Re || I === this.computed) return
      let t = this.activeLink
      if (t === void 0 || t.sub !== I)
        ((t = this.activeLink = new We(I, this)),
          I.deps ? ((t.prevDep = I.depsTail), (I.depsTail.nextDep = t), (I.depsTail = t)) : (I.deps = I.depsTail = t),
          Ke(t))
      else if (t.version === -1 && ((t.version = this.version), t.nextDep)) {
        let e = t.nextDep
        ;((e.prevDep = t.prevDep),
          t.prevDep && (t.prevDep.nextDep = e),
          (t.prevDep = I.depsTail),
          (t.nextDep = void 0),
          (I.depsTail.nextDep = t),
          (I.depsTail = t),
          I.deps === t && (I.deps = e))
      }
      return t
    }
    trigger(e) {
      ;(this.version++, Ue++, this.notify(e))
    }
    notify(e) {
      Ae()
      try {
        for (let e = this.subs; e; e = e.prevSub) e.sub.notify() && e.sub.dep.notify()
      } finally {
        je()
      }
    }
  }
function Ke(e) {
  if ((e.dep.sc++, e.sub.flags & 4)) {
    let t = e.dep.computed
    if (t && !e.dep.subs) {
      t.flags |= 20
      for (let e = t.deps; e; e = e.nextDep) Ke(e)
    }
    let n = e.dep.subs
    ;(n !== e && ((e.prevSub = n), n && (n.nextSub = e)), (e.dep.subs = e))
  }
}
var qe = new WeakMap(),
  Je = Symbol(``),
  Ye = Symbol(``),
  Xe = Symbol(``)
function Ze(e, t, n) {
  if (Re && I) {
    let t = qe.get(e)
    t || qe.set(e, (t = new Map()))
    let r = t.get(n)
    ;(r || (t.set(n, (r = new Ge())), (r.map = t), (r.key = n)), r.track())
  }
}
function Qe(e, t, n, r, i, a) {
  let o = qe.get(e)
  if (!o) {
    Ue++
    return
  }
  let s = (e) => {
    e && e.trigger()
  }
  if ((Ae(), t === `clear`)) o.forEach(s)
  else {
    let i = d(e),
      a = i && w(n)
    if (i && n === `length`) {
      let e = Number(r)
      o.forEach((t, n) => {
        ;(n === `length` || n === Xe || (!_(n) && n >= e)) && s(t)
      })
    } else
      switch (((n !== void 0 || o.has(void 0)) && s(o.get(n)), a && s(o.get(Xe)), t)) {
        case `add`:
          i ? a && s(o.get(`length`)) : (s(o.get(Je)), f(e) && s(o.get(Ye)))
          break
        case `delete`:
          i || (s(o.get(Je)), f(e) && s(o.get(Ye)))
          break
        case `set`:
          f(e) && s(o.get(Je))
          break
      }
  }
  je()
}
function $e(e, t) {
  let n = qe.get(e)
  return n && n.get(t)
}
function et(e) {
  let t = L(e)
  return t === e ? t : (Ze(t, `iterate`, Xe), Bt(e) ? t : t.map(Ut))
}
function tt(e) {
  return (Ze((e = L(e)), `iterate`, Xe), e)
}
function nt(e, t) {
  return zt(e) ? Wt(Rt(e) ? Ut(t) : t) : Ut(t)
}
var rt = {
  __proto__: null,
  [Symbol.iterator]() {
    return it(this, Symbol.iterator, (e) => nt(this, e))
  },
  concat(...e) {
    return et(this).concat(...e.map((e) => (d(e) ? et(e) : e)))
  },
  entries() {
    return it(this, `entries`, (e) => ((e[1] = nt(this, e[1])), e))
  },
  every(e, t) {
    return ot(this, `every`, e, t, void 0, arguments)
  },
  filter(e, t) {
    return ot(this, `filter`, e, t, (e) => e.map((e) => nt(this, e)), arguments)
  },
  find(e, t) {
    return ot(this, `find`, e, t, (e) => nt(this, e), arguments)
  },
  findIndex(e, t) {
    return ot(this, `findIndex`, e, t, void 0, arguments)
  },
  findLast(e, t) {
    return ot(this, `findLast`, e, t, (e) => nt(this, e), arguments)
  },
  findLastIndex(e, t) {
    return ot(this, `findLastIndex`, e, t, void 0, arguments)
  },
  forEach(e, t) {
    return ot(this, `forEach`, e, t, void 0, arguments)
  },
  includes(...e) {
    return ct(this, `includes`, e)
  },
  indexOf(...e) {
    return ct(this, `indexOf`, e)
  },
  join(e) {
    return et(this).join(e)
  },
  lastIndexOf(...e) {
    return ct(this, `lastIndexOf`, e)
  },
  map(e, t) {
    return ot(this, `map`, e, t, void 0, arguments)
  },
  pop() {
    return lt(this, `pop`)
  },
  push(...e) {
    return lt(this, `push`, e)
  },
  reduce(e, ...t) {
    return st(this, `reduce`, e, t)
  },
  reduceRight(e, ...t) {
    return st(this, `reduceRight`, e, t)
  },
  shift() {
    return lt(this, `shift`)
  },
  some(e, t) {
    return ot(this, `some`, e, t, void 0, arguments)
  },
  splice(...e) {
    return lt(this, `splice`, e)
  },
  toReversed() {
    return et(this).toReversed()
  },
  toSorted(e) {
    return et(this).toSorted(e)
  },
  toSpliced(...e) {
    return et(this).toSpliced(...e)
  },
  unshift(...e) {
    return lt(this, `unshift`, e)
  },
  values() {
    return it(this, `values`, (e) => nt(this, e))
  },
}
function it(e, t, n) {
  let r = tt(e),
    i = r[t]()
  return (
    r !== e &&
      !Bt(e) &&
      ((i._next = i.next),
      (i.next = () => {
        let e = i._next()
        return (e.done || (e.value = n(e.value)), e)
      })),
    i
  )
}
var at = Array.prototype
function ot(e, t, n, r, i, a) {
  let o = tt(e),
    s = o !== e && !Bt(e),
    c = o[t]
  if (c !== at[t]) {
    let t = c.apply(e, a)
    return s ? Ut(t) : t
  }
  let l = n
  o !== e &&
    (s
      ? (l = function (t, r) {
          return n.call(this, nt(e, t), r, e)
        })
      : n.length > 2 &&
        (l = function (t, r) {
          return n.call(this, t, r, e)
        }))
  let u = c.call(o, l, r)
  return s && i ? i(u) : u
}
function st(e, t, n, r) {
  let i = tt(e),
    a = i !== e && !Bt(e),
    o = n,
    s = !1
  i !== e &&
    (a
      ? ((s = r.length === 0),
        (o = function (t, r, i) {
          return (s && ((s = !1), (t = nt(e, t))), n.call(this, t, nt(e, r), i, e))
        }))
      : n.length > 3 &&
        (o = function (t, r, i) {
          return n.call(this, t, r, i, e)
        }))
  let c = i[t](o, ...r)
  return s ? nt(e, c) : c
}
function ct(e, t, n) {
  let r = L(e)
  Ze(r, `iterate`, Xe)
  let i = r[t](...n)
  return (i === -1 || i === !1) && Vt(n[0]) ? ((n[0] = L(n[0])), r[t](...n)) : i
}
function lt(e, t, n = []) {
  ;(Be(), Ae())
  let r = L(e)[t].apply(e, n)
  return (je(), Ve(), r)
}
var ut = e(`__proto__,__v_isRef,__isVue`),
  dt = new Set(
    Object.getOwnPropertyNames(Symbol)
      .filter((e) => e !== `arguments` && e !== `caller`)
      .map((e) => Symbol[e])
      .filter(_),
  )
function ft(e) {
  _(e) || (e = String(e))
  let t = L(this)
  return (Ze(t, `has`, e), t.hasOwnProperty(e))
}
var pt = class {
    constructor(e = !1, t = !1) {
      ;((this._isReadonly = e), (this._isShallow = t))
    }
    get(e, t, n) {
      if (t === `__v_skip`) return e.__v_skip
      let r = this._isReadonly,
        i = this._isShallow
      if (t === `__v_isReactive`) return !r
      if (t === `__v_isReadonly`) return r
      if (t === `__v_isShallow`) return i
      if (t === `__v_raw`)
        return n === (r ? (i ? jt : At) : i ? kt : Ot).get(e) || Object.getPrototypeOf(e) === Object.getPrototypeOf(n) ? e : void 0
      let a = d(e)
      if (!r) {
        let e
        if (a && (e = rt[t])) return e
        if (t === `hasOwnProperty`) return ft
      }
      let o = Reflect.get(e, t, R(e) ? e : n)
      if ((_(t) ? dt.has(t) : ut(t)) || (r || Ze(e, `get`, t), i)) return o
      if (R(o)) {
        let e = a && w(t) ? o : o.value
        return r && v(e) ? It(e) : e
      }
      return v(o) ? (r ? It(o) : Pt(o)) : o
    }
  },
  mt = class extends pt {
    constructor(e = !1) {
      super(!1, e)
    }
    set(e, t, n, r) {
      let i = e[t],
        a = d(e) && w(t)
      if (!this._isShallow) {
        let e = zt(i)
        if ((!Bt(n) && !zt(n) && ((i = L(i)), (n = L(n))), !a && R(i) && !R(n))) return (e || (i.value = n), !0)
      }
      let o = a ? Number(t) < e.length : u(e, t),
        s = Reflect.set(e, t, n, R(e) ? e : r)
      return (e === L(r) && (o ? M(n, i) && Qe(e, `set`, t, n, i) : Qe(e, `add`, t, n)), s)
    }
    deleteProperty(e, t) {
      let n = u(e, t),
        r = e[t],
        i = Reflect.deleteProperty(e, t)
      return (i && n && Qe(e, `delete`, t, void 0, r), i)
    }
    has(e, t) {
      let n = Reflect.has(e, t)
      return ((!_(t) || !dt.has(t)) && Ze(e, `has`, t), n)
    }
    ownKeys(e) {
      return (Ze(e, `iterate`, d(e) ? `length` : Je), Reflect.ownKeys(e))
    }
  },
  ht = class extends pt {
    constructor(e = !1) {
      super(!0, e)
    }
    set(e, t) {
      return !0
    }
    deleteProperty(e, t) {
      return !0
    }
  },
  gt = new mt(),
  _t = new ht(),
  vt = new mt(!0),
  yt = (e) => e,
  bt = (e) => Reflect.getPrototypeOf(e)
function xt(e, t, n) {
  return function (...r) {
    let i = this.__v_raw,
      a = L(i),
      o = f(a),
      c = e === `entries` || (e === Symbol.iterator && o),
      l = e === `keys` && o,
      u = i[e](...r),
      d = n ? yt : t ? Wt : Ut
    return (
      !t && Ze(a, `iterate`, l ? Ye : Je),
      s(Object.create(u), {
        next() {
          let { value: e, done: t } = u.next()
          return t ? { value: e, done: t } : { value: c ? [d(e[0]), d(e[1])] : d(e), done: t }
        },
      })
    )
  }
}
function St(e) {
  return function (...t) {
    return e === `delete` ? !1 : e === `clear` ? void 0 : this
  }
}
function Ct(e, t) {
  let n = {
    get(n) {
      let r = this.__v_raw,
        i = L(r),
        a = L(n)
      e || (M(n, a) && Ze(i, `get`, n), Ze(i, `get`, a))
      let { has: o } = bt(i),
        s = t ? yt : e ? Wt : Ut
      if (o.call(i, n)) return s(r.get(n))
      if (o.call(i, a)) return s(r.get(a))
      r !== i && r.get(n)
    },
    get size() {
      let t = this.__v_raw
      return (!e && Ze(L(t), `iterate`, Je), t.size)
    },
    has(t) {
      let n = this.__v_raw,
        r = L(n),
        i = L(t)
      return (e || (M(t, i) && Ze(r, `has`, t), Ze(r, `has`, i)), t === i ? n.has(t) : n.has(t) || n.has(i))
    },
    forEach(n, r) {
      let i = this,
        a = i.__v_raw,
        o = L(a),
        s = t ? yt : e ? Wt : Ut
      return (!e && Ze(o, `iterate`, Je), a.forEach((e, t) => n.call(r, s(e), s(t), i)))
    },
  }
  return (
    s(
      n,
      e
        ? { add: St(`add`), set: St(`set`), delete: St(`delete`), clear: St(`clear`) }
        : {
            add(e) {
              let n = L(this),
                r = bt(n),
                i = L(e),
                a = !t && !Bt(e) && !zt(e) ? i : e
              return (
                r.has.call(n, a) || (M(e, a) && r.has.call(n, e)) || (M(i, a) && r.has.call(n, i)) || (n.add(a), Qe(n, `add`, a, a)),
                this
              )
            },
            set(e, n) {
              !t && !Bt(n) && !zt(n) && (n = L(n))
              let r = L(this),
                { has: i, get: a } = bt(r),
                o = i.call(r, e)
              o ||= ((e = L(e)), i.call(r, e))
              let s = a.call(r, e)
              return (r.set(e, n), o ? M(n, s) && Qe(r, `set`, e, n, s) : Qe(r, `add`, e, n), this)
            },
            delete(e) {
              let t = L(this),
                { has: n, get: r } = bt(t),
                i = n.call(t, e)
              i ||= ((e = L(e)), n.call(t, e))
              let a = r ? r.call(t, e) : void 0,
                o = t.delete(e)
              return (i && Qe(t, `delete`, e, void 0, a), o)
            },
            clear() {
              let e = L(this),
                t = e.size !== 0,
                n = e.clear()
              return (t && Qe(e, `clear`, void 0, void 0, void 0), n)
            },
          },
    ),
    [`keys`, `values`, `entries`, Symbol.iterator].forEach((r) => {
      n[r] = xt(r, e, t)
    }),
    n
  )
}
function wt(e, t) {
  let n = Ct(e, t)
  return (t, r, i) =>
    r === `__v_isReactive` ? !e : r === `__v_isReadonly` ? e : r === `__v_raw` ? t : Reflect.get(u(n, r) && r in t ? n : t, r, i)
}
var Tt = { get: wt(!1, !1) },
  Et = { get: wt(!1, !0) },
  Dt = { get: wt(!0, !1) },
  Ot = new WeakMap(),
  kt = new WeakMap(),
  At = new WeakMap(),
  jt = new WeakMap()
function Mt(e) {
  switch (e) {
    case `Object`:
    case `Array`:
      return 1
    case `Map`:
    case `Set`:
    case `WeakMap`:
    case `WeakSet`:
      return 2
    default:
      return 0
  }
}
function Nt(e) {
  return e.__v_skip || !Object.isExtensible(e) ? 0 : Mt(S(e))
}
function Pt(e) {
  return zt(e) ? e : Lt(e, !1, gt, Tt, Ot)
}
function Ft(e) {
  return Lt(e, !1, vt, Et, kt)
}
function It(e) {
  return Lt(e, !0, _t, Dt, At)
}
function Lt(e, t, n, r, i) {
  if (!v(e) || (e.__v_raw && !(t && e.__v_isReactive))) return e
  let a = Nt(e)
  if (a === 0) return e
  let o = i.get(e)
  if (o) return o
  let s = new Proxy(e, a === 2 ? r : n)
  return (i.set(e, s), s)
}
function Rt(e) {
  return zt(e) ? Rt(e.__v_raw) : !!(e && e.__v_isReactive)
}
function zt(e) {
  return !!(e && e.__v_isReadonly)
}
function Bt(e) {
  return !!(e && e.__v_isShallow)
}
function Vt(e) {
  return e ? !!e.__v_raw : !1
}
function L(e) {
  let t = e && e.__v_raw
  return t ? L(t) : e
}
function Ht(e) {
  return (!u(e, `__v_skip`) && Object.isExtensible(e) && N(e, `__v_skip`, !0), e)
}
var Ut = (e) => (v(e) ? Pt(e) : e),
  Wt = (e) => (v(e) ? It(e) : e)
function R(e) {
  return e ? e.__v_isRef === !0 : !1
}
function z(e) {
  return Kt(e, !1)
}
function Gt(e) {
  return Kt(e, !0)
}
function Kt(e, t) {
  return R(e) ? e : new qt(e, t)
}
var qt = class {
  constructor(e, t) {
    ;((this.dep = new Ge()),
      (this.__v_isRef = !0),
      (this.__v_isShallow = !1),
      (this._rawValue = t ? e : L(e)),
      (this._value = t ? e : Ut(e)),
      (this.__v_isShallow = t))
  }
  get value() {
    return (this.dep.track(), this._value)
  }
  set value(e) {
    let t = this._rawValue,
      n = this.__v_isShallow || Bt(e) || zt(e)
    ;((e = n ? e : L(e)), M(e, t) && ((this._rawValue = e), (this._value = n ? e : Ut(e)), this.dep.trigger()))
  }
}
function B(e) {
  return R(e) ? e.value : e
}
var Jt = {
  get: (e, t, n) => (t === `__v_raw` ? e : B(Reflect.get(e, t, n))),
  set: (e, t, n, r) => {
    let i = e[t]
    return R(i) && !R(n) ? ((i.value = n), !0) : Reflect.set(e, t, n, r)
  },
}
function Yt(e) {
  return Rt(e) ? e : new Proxy(e, Jt)
}
function Xt(e) {
  let t = d(e) ? Array(e.length) : {}
  for (let n in e) t[n] = en(e, n)
  return t
}
var Zt = class {
    constructor(e, t, n) {
      ;((this._object = e),
        (this._defaultValue = n),
        (this.__v_isRef = !0),
        (this._value = void 0),
        (this._key = _(t) ? t : String(t)),
        (this._raw = L(e)))
      let r = !0,
        i = e
      if (!d(e) || _(this._key) || !w(this._key))
        do r = !Vt(i) || Bt(i)
        while (r && (i = i.__v_raw))
      this._shallow = r
    }
    get value() {
      let e = this._object[this._key]
      return (this._shallow && (e = B(e)), (this._value = e === void 0 ? this._defaultValue : e))
    }
    set value(e) {
      if (this._shallow && R(this._raw[this._key])) {
        let t = this._object[this._key]
        if (R(t)) {
          t.value = e
          return
        }
      }
      this._object[this._key] = e
    }
    get dep() {
      return $e(this._raw, this._key)
    }
  },
  Qt = class {
    constructor(e) {
      ;((this._getter = e), (this.__v_isRef = !0), (this.__v_isReadonly = !0), (this._value = void 0))
    }
    get value() {
      return (this._value = this._getter())
    }
  }
function $t(e, t, n) {
  return R(e) ? e : h(e) ? new Qt(e) : v(e) && arguments.length > 1 ? en(e, t, n) : z(e)
}
function en(e, t, n) {
  return new Zt(e, t, n)
}
var tn = class {
  constructor(e, t, n) {
    ;((this.fn = e),
      (this.setter = t),
      (this._value = void 0),
      (this.dep = new Ge(this)),
      (this.__v_isRef = !0),
      (this.deps = void 0),
      (this.depsTail = void 0),
      (this.flags = 16),
      (this.globalVersion = Ue - 1),
      (this.next = void 0),
      (this.effect = this),
      (this.__v_isReadonly = !t),
      (this.isSSR = n))
  }
  notify() {
    if (((this.flags |= 16), !(this.flags & 8) && I !== this)) return (ke(this, !0), !0)
  }
  get value() {
    let e = this.dep.track()
    return (Fe(this), e && (e.version = this.dep.version), this._value)
  }
  set value(e) {
    this.setter && this.setter(e)
  }
}
function nn(e, t, n = !1) {
  let r, i
  return (h(e) ? (r = e) : ((r = e.get), (i = e.set)), new tn(r, i, n))
}
var rn = {},
  an = new WeakMap(),
  on = void 0
function sn(e, t = !1, n = on) {
  if (n) {
    let t = an.get(n)
    ;(t || an.set(n, (t = [])), t.push(e))
  }
}
function cn(e, n, i = t) {
  let { immediate: a, deep: o, once: s, scheduler: l, augmentJob: u, call: f } = i,
    p = (e) => (o ? e : Bt(e) || o === !1 || o === 0 ? ln(e, 1) : ln(e)),
    m,
    g,
    _,
    v,
    y = !1,
    b = !1
  if (
    (R(e)
      ? ((g = () => e.value), (y = Bt(e)))
      : Rt(e)
        ? ((g = () => p(e)), (y = !0))
        : d(e)
          ? ((b = !0),
            (y = e.some((e) => Rt(e) || Bt(e))),
            (g = () =>
              e.map((e) => {
                if (R(e)) return e.value
                if (Rt(e)) return p(e)
                if (h(e)) return f ? f(e, 2) : e()
              })))
          : (g = h(e)
              ? n
                ? f
                  ? () => f(e, 2)
                  : e
                : () => {
                    if (_) {
                      Be()
                      try {
                        _()
                      } finally {
                        Ve()
                      }
                    }
                    let t = on
                    on = m
                    try {
                      return f ? f(e, 3, [v]) : e(v)
                    } finally {
                      on = t
                    }
                  }
              : r),
    n && o)
  ) {
    let e = g,
      t = o === !0 ? 1 / 0 : o
    g = () => ln(e(), t)
  }
  let x = Se(),
    S = () => {
      ;(m.stop(), x && x.active && c(x.effects, m))
    }
  if (s && n) {
    let e = n
    n = (...t) => {
      ;(e(...t), S())
    }
  }
  let C = b ? Array(e.length).fill(rn) : rn,
    w = (e) => {
      if (!(!(m.flags & 1) || (!m.dirty && !e)))
        if (n) {
          let e = m.run()
          if (o || y || (b ? e.some((e, t) => M(e, C[t])) : M(e, C))) {
            _ && _()
            let t = on
            on = m
            try {
              let t = [e, C === rn ? void 0 : b && C[0] === rn ? [] : C, v]
              ;((C = e), f ? f(n, 3, t) : n(...t))
            } finally {
              on = t
            }
          }
        } else m.run()
    }
  return (
    u && u(w),
    (m = new Te(g)),
    (m.scheduler = l ? () => l(w, !1) : w),
    (v = (e) => sn(e, !1, m)),
    (_ = m.onStop =
      () => {
        let e = an.get(m)
        if (e) {
          if (f) f(e, 4)
          else for (let t of e) t()
          an.delete(m)
        }
      }),
    n ? (a ? w(!0) : (C = m.run())) : l ? l(w.bind(null, !0), !0) : m.run(),
    (S.pause = m.pause.bind(m)),
    (S.resume = m.resume.bind(m)),
    (S.stop = S),
    S
  )
}
function ln(e, t = 1 / 0, n) {
  if (t <= 0 || !v(e) || e.__v_skip || ((n ||= new Map()), (n.get(e) || 0) >= t)) return e
  if ((n.set(e, t), t--, R(e))) ln(e.value, t, n)
  else if (d(e)) for (let r = 0; r < e.length; r++) ln(e[r], t, n)
  else if (p(e) || f(e))
    e.forEach((e) => {
      ln(e, t, n)
    })
  else if (C(e)) {
    for (let r in e) ln(e[r], t, n)
    for (let r of Object.getOwnPropertySymbols(e)) Object.prototype.propertyIsEnumerable.call(e, r) && ln(e[r], t, n)
  }
  return e
}
function un(e, t, n, r) {
  try {
    return r ? e(...r) : e()
  } catch (e) {
    fn(e, t, n)
  }
}
function dn(e, t, n, r) {
  if (h(e)) {
    let i = un(e, t, n, r)
    return (
      i &&
        y(i) &&
        i.catch((e) => {
          fn(e, t, n)
        }),
      i
    )
  }
  if (d(e)) {
    let i = []
    for (let a = 0; a < e.length; a++) i.push(dn(e[a], t, n, r))
    return i
  }
}
function fn(e, n, r, i = !0) {
  let a = n ? n.vnode : null,
    { errorHandler: o, throwUnhandledErrorInProduction: s } = (n && n.appContext.config) || t
  if (n) {
    let t = n.parent,
      i = n.proxy,
      a = `https://vuejs.org/error-reference/#runtime-${r}`
    for (; t; ) {
      let n = t.ec
      if (n) {
        for (let t = 0; t < n.length; t++) if (n[t](e, i, a) === !1) return
      }
      t = t.parent
    }
    if (o) {
      ;(Be(), un(o, null, 10, [e, i, a]), Ve())
      return
    }
  }
  pn(e, r, a, i, s)
}
function pn(e, t, n, r = !0, i = !1) {
  if (i) throw e
  console.error(e)
}
var mn = [],
  hn = -1,
  gn = [],
  _n = null,
  vn = 0,
  yn = Promise.resolve(),
  bn = null
function xn(e) {
  let t = bn || yn
  return e ? t.then(this ? e.bind(this) : e) : t
}
function Sn(e) {
  let t = hn + 1,
    n = mn.length
  for (; t < n; ) {
    let r = (t + n) >>> 1,
      i = mn[r],
      a = On(i)
    a < e || (a === e && i.flags & 2) ? (t = r + 1) : (n = r)
  }
  return t
}
function Cn(e) {
  if (!(e.flags & 1)) {
    let t = On(e),
      n = mn[mn.length - 1]
    ;(!n || (!(e.flags & 2) && t >= On(n)) ? mn.push(e) : mn.splice(Sn(t), 0, e), (e.flags |= 1), wn())
  }
}
function wn() {
  bn ||= yn.then(kn)
}
function Tn(e) {
  ;(d(e) ? gn.push(...e) : _n && e.id === -1 ? _n.splice(vn + 1, 0, e) : e.flags & 1 || (gn.push(e), (e.flags |= 1)), wn())
}
function En(e, t, n = hn + 1) {
  for (; n < mn.length; n++) {
    let t = mn[n]
    if (t && t.flags & 2) {
      if (e && t.id !== e.uid) continue
      ;(mn.splice(n, 1), n--, t.flags & 4 && (t.flags &= -2), t(), t.flags & 4 || (t.flags &= -2))
    }
  }
}
function Dn(e) {
  if (gn.length) {
    let e = [...new Set(gn)].sort((e, t) => On(e) - On(t))
    if (((gn.length = 0), _n)) {
      _n.push(...e)
      return
    }
    for (_n = e, vn = 0; vn < _n.length; vn++) {
      let e = _n[vn]
      ;(e.flags & 4 && (e.flags &= -2), e.flags & 8 || e(), (e.flags &= -2))
    }
    ;((_n = null), (vn = 0))
  }
}
var On = (e) => (e.id == null ? (e.flags & 2 ? -1 : 1 / 0) : e.id)
function kn(e) {
  try {
    for (hn = 0; hn < mn.length; hn++) {
      let e = mn[hn]
      e && !(e.flags & 8) && (e.flags & 4 && (e.flags &= -2), un(e, e.i, e.i ? 15 : 14), e.flags & 4 || (e.flags &= -2))
    }
  } finally {
    for (; hn < mn.length; hn++) {
      let e = mn[hn]
      e && (e.flags &= -2)
    }
    ;((hn = -1), (mn.length = 0), Dn(e), (bn = null), (mn.length || gn.length) && kn(e))
  }
}
var An = null,
  jn = null
function Mn(e) {
  let t = An
  return ((An = e), (jn = (e && e.type.__scopeId) || null), t)
}
function Nn(e, t = An, n) {
  if (!t || e._n) return e
  let r = (...n) => {
    r._d && fa(-1)
    let i = Mn(t),
      a
    try {
      a = e(...n)
    } finally {
      ;(Mn(i), r._d && fa(1))
    }
    return a
  }
  return ((r._n = !0), (r._c = !0), (r._d = !0), r)
}
function Pn(e, n) {
  if (An === null) return e
  let r = Ja(An),
    i = (e.dirs ||= [])
  for (let e = 0; e < n.length; e++) {
    let [a, o, s, c = t] = n[e]
    a &&
      (h(a) && (a = { mounted: a, updated: a }),
      a.deep && ln(o),
      i.push({ dir: a, instance: r, value: o, oldValue: void 0, arg: s, modifiers: c }))
  }
  return e
}
function Fn(e, t, n, r) {
  let i = e.dirs,
    a = t && t.dirs
  for (let o = 0; o < i.length; o++) {
    let s = i[o]
    a && (s.oldValue = a[o].value)
    let c = s.dir[r]
    c && (Be(), dn(c, n, 8, [e.el, s, e, t]), Ve())
  }
}
function In(e, t) {
  if (Ma) {
    let n = Ma.provides,
      r = Ma.parent && Ma.parent.provides
    ;(r === n && (n = Ma.provides = Object.create(r)), (n[e] = t))
  }
}
function Ln(e, t, n = !1) {
  let r = Na()
  if (r || hi) {
    let i = hi
      ? hi._context.provides
      : r
        ? r.parent == null || r.ce
          ? r.vnode.appContext && r.vnode.appContext.provides
          : r.parent.provides
        : void 0
    if (i && e in i) return i[e]
    if (arguments.length > 1) return n && h(t) ? t.call(r && r.proxy) : t
  }
}
function Rn() {
  return !!(Na() || hi)
}
var zn = Symbol.for(`v-scx`),
  Bn = () => Ln(zn)
function Vn(e, t, n) {
  return Hn(e, t, n)
}
function Hn(e, n, i = t) {
  let { immediate: a, deep: o, flush: c, once: l } = i,
    u = s({}, i),
    d = (n && a) || (!n && c !== `post`),
    f
  if (za) {
    if (c === `sync`) {
      let e = Bn()
      f = e.__watcherHandles ||= []
    } else if (!d) {
      let e = () => {}
      return ((e.stop = r), (e.resume = r), (e.pause = r), e)
    }
  }
  let p = Ma
  u.call = (e, t, n) => dn(e, p, t, n)
  let m = !1
  ;(c === `post`
    ? (u.scheduler = (e) => {
        Ki(e, p && p.suspense)
      })
    : c !== `sync` &&
      ((m = !0),
      (u.scheduler = (e, t) => {
        t ? e() : Cn(e)
      })),
    (u.augmentJob = (e) => {
      ;(n && (e.flags |= 4), m && ((e.flags |= 2), p && ((e.id = p.uid), (e.i = p))))
    }))
  let h = cn(e, n, u)
  return (za && (f ? f.push(h) : d && h()), h)
}
function Un(e, t, n) {
  let r = this.proxy,
    i = g(e) ? (e.includes(`.`) ? Wn(r, e) : () => r[e]) : e.bind(r, r),
    a
  h(t) ? (a = t) : ((a = t.handler), (n = t))
  let o = Ia(this),
    s = Hn(i, a.bind(r), n)
  return (o(), s)
}
function Wn(e, t) {
  let n = t.split(`.`)
  return () => {
    let t = e
    for (let e = 0; e < n.length && t; e++) t = t[n[e]]
    return t
  }
}
var Gn = new WeakMap(),
  Kn = Symbol(`_vte`),
  qn = (e) => e.__isTeleport,
  Jn = (e) => e && (e.disabled || e.disabled === ``),
  Yn = (e) => e && (e.defer || e.defer === ``),
  Xn = (e) => typeof SVGElement < `u` && e instanceof SVGElement,
  Zn = (e) => typeof MathMLElement == `function` && e instanceof MathMLElement,
  Qn = (e, t) => {
    let n = e && e.to
    return g(n) ? (t ? t(n) : null) : n
  },
  $n = {
    name: `Teleport`,
    __isTeleport: !0,
    process(e, t, n, r, i, a, o, s, c, l) {
      let {
          mc: u,
          pc: d,
          pbc: f,
          o: { insert: p, querySelector: m, createText: h, createComment: g, parentNode: _ },
        } = l,
        v = Jn(t.props),
        { dynamicChildren: y } = t,
        b = (e, t, n) => {
          e.shapeFlag & 16 && u(e.children, t, n, i, a, o, s, c)
        },
        x = (e = t) => {
          let n = Jn(e.props),
            r = (e.target = Qn(e.props, m)),
            a = ir(r, e, h, p)
          r &&
            (o !== `svg` && Xn(r) ? (o = `svg`) : o !== `mathml` && Zn(r) && (o = `mathml`),
            i && i.isCE && (i.ce._teleportTargets || (i.ce._teleportTargets = new Set())).add(r),
            n || (b(e, r, a), rr(e, !1)))
        },
        S = (e) => {
          let t = () => {
            Gn.get(e) === t && (Gn.delete(e), Jn(e.props) && (b(e, _(e.el) || n, e.anchor), rr(e, !0)), x(e))
          }
          ;(Gn.set(e, t), Ki(t, a))
        }
      if (e == null) {
        let e = (t.el = h(``)),
          i = (t.anchor = h(``))
        if ((p(e, n, r), p(i, n, r), Yn(t.props) || (a && a.pendingBranch))) {
          S(t)
          return
        }
        ;(v && (b(t, n, i), rr(t, !0)), x())
      } else {
        t.el = e.el
        let r = (t.anchor = e.anchor),
          u = Gn.get(e)
        if (u) {
          ;((u.flags |= 8), Gn.delete(e), S(t))
          return
        }
        t.targetStart = e.targetStart
        let p = (t.target = e.target),
          h = (t.targetAnchor = e.targetAnchor),
          g = Jn(e.props),
          _ = g ? n : p,
          b = g ? r : h
        if (
          (o === `svg` || Xn(p) ? (o = `svg`) : (o === `mathml` || Zn(p)) && (o = `mathml`),
          y ? (f(e.dynamicChildren, y, _, i, a, o, s), Qi(e, t, !0)) : c || d(e, t, _, b, i, a, o, s, !1),
          v)
        )
          g ? t.props && e.props && t.props.to !== e.props.to && (t.props.to = e.props.to) : er(t, n, r, l, 1)
        else if ((t.props && t.props.to) !== (e.props && e.props.to)) {
          let e = (t.target = Qn(t.props, m))
          e && er(t, e, null, l, 0)
        } else g && er(t, p, h, l, 1)
        rr(t, v)
      }
    },
    remove(e, t, n, { um: r, o: { remove: i } }, a) {
      let { shapeFlag: o, children: s, anchor: c, targetStart: l, targetAnchor: u, target: d, props: f } = e,
        p = a || !Jn(f),
        m = Gn.get(e)
      if ((m && ((m.flags |= 8), Gn.delete(e), (p = !1)), d && (i(l), i(u)), a && i(c), o & 16))
        for (let e = 0; e < s.length; e++) {
          let i = s[e]
          r(i, t, n, p, !!i.dynamicChildren)
        }
    },
    move: er,
    hydrate: tr,
  }
function er(e, t, n, { o: { insert: r }, m: i }, a = 2) {
  a === 0 && r(e.targetAnchor, t, n)
  let { el: o, anchor: s, shapeFlag: c, children: l, props: u } = e,
    d = a === 2
  if ((d && r(o, t, n), !Gn.has(e) && (!d || Jn(u)) && c & 16)) for (let e = 0; e < l.length; e++) i(l[e], t, n, 2)
  d && r(s, t, n)
}
function tr(e, t, n, r, i, a, { o: { nextSibling: o, parentNode: s, querySelector: c, insert: l, createText: u } }, d) {
  function f(e, n) {
    let r = n
    for (; r; ) {
      if (r && r.nodeType === 8) {
        if (r.data === `teleport start anchor`) t.targetStart = r
        else if (r.data === `teleport anchor`) {
          ;((t.targetAnchor = r), (e._lpa = t.targetAnchor && o(t.targetAnchor)))
          break
        }
      }
      r = o(r)
    }
  }
  function p(e, t) {
    t.anchor = d(o(e), t, s(e), n, r, i, a)
  }
  let m = (t.target = Qn(t.props, c)),
    h = Jn(t.props)
  if (m) {
    let c = m._lpa || m.firstChild
    ;(t.shapeFlag & 16 &&
      (h
        ? (p(e, t), f(m, c), t.targetAnchor || ir(m, t, u, l, s(e) === m ? e : null))
        : ((t.anchor = o(e)), f(m, c), t.targetAnchor || ir(m, t, u, l), d(c && o(c), t, m, n, r, i, a))),
      rr(t, h))
  } else h && t.shapeFlag & 16 && (p(e, t), (t.targetStart = e), (t.targetAnchor = o(e)))
  return t.anchor && o(t.anchor)
}
var nr = $n
function rr(e, t) {
  let n = e.ctx
  if (n && n.ut) {
    let r, i
    for (t ? ((r = e.el), (i = e.anchor)) : ((r = e.targetStart), (i = e.targetAnchor)); r && r !== i; )
      (r.nodeType === 1 && r.setAttribute(`data-v-owner`, n.uid), (r = r.nextSibling))
    n.ut()
  }
}
function ir(e, t, n, r, i = null) {
  let a = (t.targetStart = n(``)),
    o = (t.targetAnchor = n(``))
  return ((a[Kn] = o), e && (r(a, e, i), r(o, e, i)), o)
}
var ar = Symbol(`_leaveCb`),
  or = Symbol(`_enterCb`)
function sr() {
  let e = { isMounted: !1, isLeaving: !1, isUnmounting: !1, leavingVNodes: new Map() }
  return (
    Fr(() => {
      e.isMounted = !0
    }),
    Rr(() => {
      e.isUnmounting = !0
    }),
    e
  )
}
var cr = [Function, Array],
  lr = {
    mode: String,
    appear: Boolean,
    persisted: Boolean,
    onBeforeEnter: cr,
    onEnter: cr,
    onAfterEnter: cr,
    onEnterCancelled: cr,
    onBeforeLeave: cr,
    onLeave: cr,
    onAfterLeave: cr,
    onLeaveCancelled: cr,
    onBeforeAppear: cr,
    onAppear: cr,
    onAfterAppear: cr,
    onAppearCancelled: cr,
  },
  ur = (e) => {
    let t = e.subTree
    return t.component ? ur(t.component) : t
  },
  dr = {
    name: `BaseTransition`,
    props: lr,
    setup(e, { slots: t }) {
      let n = Na(),
        r = sr()
      return () => {
        let i = t.default && yr(t.default(), !0),
          a = i && i.length ? fr(i) : n.subTree ? K() : void 0
        if (!a) return
        let o = L(e),
          { mode: s } = o
        if (r.isLeaving) return gr(a)
        let c = _r(a)
        if (!c) return gr(a)
        let l = hr(c, o, r, n, (e) => (l = e))
        c.type !== oa && vr(c, l)
        let u = n.subTree && _r(n.subTree)
        if (u && u.type !== oa && !ga(u, c) && ur(n).type !== oa) {
          let e = hr(u, o, r, n)
          if ((vr(u, e), s === `out-in` && c.type !== oa))
            return (
              (r.isLeaving = !0),
              (e.afterLeave = () => {
                ;((r.isLeaving = !1), n.job.flags & 8 || n.update(), delete e.afterLeave, (u = void 0))
              }),
              gr(a)
            )
          s === `in-out` && c.type !== oa
            ? (e.delayLeave = (e, t, n) => {
                let i = mr(r, u)
                ;((i[String(u.key)] = u),
                  (e[ar] = () => {
                    ;(t(), (e[ar] = void 0), delete l.delayedLeave, (u = void 0))
                  }),
                  (l.delayedLeave = () => {
                    ;(n(), delete l.delayedLeave, (u = void 0))
                  }))
              })
            : (u = void 0)
        } else u &&= void 0
        return a
      }
    },
  }
function fr(e) {
  let t = e[0]
  if (e.length > 1) {
    for (let n of e)
      if (n.type !== oa) {
        t = n
        break
      }
  }
  return t
}
var pr = dr
function mr(e, t) {
  let { leavingVNodes: n } = e,
    r = n.get(t.type)
  return (r || ((r = Object.create(null)), n.set(t.type, r)), r)
}
function hr(e, t, n, r, i) {
  let {
      appear: a,
      mode: o,
      persisted: s = !1,
      onBeforeEnter: c,
      onEnter: l,
      onAfterEnter: u,
      onEnterCancelled: f,
      onBeforeLeave: p,
      onLeave: m,
      onAfterLeave: h,
      onLeaveCancelled: g,
      onBeforeAppear: _,
      onAppear: v,
      onAfterAppear: y,
      onAppearCancelled: b,
    } = t,
    x = String(e.key),
    S = mr(n, e),
    C = (e, t) => {
      e && dn(e, r, 9, t)
    },
    w = (e, t) => {
      let n = t[1]
      ;(C(e, t), d(e) ? e.every((e) => e.length <= 1) && n() : e.length <= 1 && n())
    },
    T = {
      mode: o,
      persisted: s,
      beforeEnter(t) {
        let r = c
        if (!n.isMounted)
          if (a) r = _ || c
          else return
        t[ar] && t[ar](!0)
        let i = S[x]
        ;(i && ga(e, i) && i.el[ar] && i.el[ar](), C(r, [t]))
      },
      enter(t) {
        if (S[x] === e) return
        let r = l,
          i = u,
          o = f
        if (!n.isMounted)
          if (a) ((r = v || l), (i = y || u), (o = b || f))
          else return
        let s = !1
        t[or] = (e) => {
          s || ((s = !0), C(e ? o : i, [t]), T.delayedLeave && T.delayedLeave(), (t[or] = void 0))
        }
        let c = t[or].bind(null, !1)
        r ? w(r, [t, c]) : c()
      },
      leave(t, r) {
        let i = String(e.key)
        if ((t[or] && t[or](!0), n.isUnmounting)) return r()
        C(p, [t])
        let a = !1
        t[ar] = (n) => {
          a || ((a = !0), r(), C(n ? g : h, [t]), (t[ar] = void 0), S[i] === e && delete S[i])
        }
        let o = t[ar].bind(null, !1)
        ;((S[i] = e), m ? w(m, [t, o]) : o())
      },
      clone(e) {
        let a = hr(e, t, n, r, i)
        return (i && i(a), a)
      },
    }
  return T
}
function gr(e) {
  if (Dr(e)) return ((e = xa(e)), (e.children = null), e)
}
function _r(e) {
  if (!Dr(e)) return qn(e.type) && e.children ? fr(e.children) : e
  if (e.component) return e.component.subTree
  let { shapeFlag: t, children: n } = e
  if (n) {
    if (t & 16) return n[0]
    if (t & 32 && h(n.default)) return n.default()
  }
}
function vr(e, t) {
  e.shapeFlag & 6 && e.component
    ? ((e.transition = t), vr(e.component.subTree, t))
    : e.shapeFlag & 128
      ? ((e.ssContent.transition = t.clone(e.ssContent)), (e.ssFallback.transition = t.clone(e.ssFallback)))
      : (e.transition = t)
}
function yr(e, t = !1, n) {
  let r = [],
    i = 0
  for (let a = 0; a < e.length; a++) {
    let o = e[a],
      s = n == null ? o.key : String(n) + String(o.key == null ? a : o.key)
    o.type === V
      ? (o.patchFlag & 128 && i++, (r = r.concat(yr(o.children, t, s))))
      : (t || o.type !== oa) && r.push(s == null ? o : xa(o, { key: s }))
  }
  if (i > 1) for (let e = 0; e < r.length; e++) r[e].patchFlag = -2
  return r
}
function br(e, t) {
  return h(e) ? s({ name: e.name }, t, { setup: e }) : e
}
function xr(e) {
  e.ids = [e.ids[0] + e.ids[2]++ + `-`, 0, 0]
}
function Sr(e, t) {
  let n
  return !!((n = Object.getOwnPropertyDescriptor(e, t)) && !n.configurable)
}
var Cr = new WeakMap()
function wr(e, n, r, a, o = !1) {
  if (d(e)) {
    e.forEach((e, t) => wr(e, n && (d(n) ? n[t] : n), r, a, o))
    return
  }
  if (Er(a) && !o) {
    a.shapeFlag & 512 && a.type.__asyncResolved && a.component.subTree.component && wr(e, n, r, a.component.subTree)
    return
  }
  let s = a.shapeFlag & 4 ? Ja(a.component) : a.el,
    l = o ? null : s,
    { i: f, r: p } = e,
    m = n && n.r,
    _ = f.refs === t ? (f.refs = {}) : f.refs,
    v = f.setupState,
    y = L(v),
    b = v === t ? i : (e) => (Sr(_, e) ? !1 : u(y, e)),
    x = (e, t) => !(t && Sr(_, t))
  if (m != null && m !== p) {
    if ((Tr(n), g(m))) ((_[m] = null), b(m) && (v[m] = null))
    else if (R(m)) {
      let e = n
      ;(x(m, e.k) && (m.value = null), e.k && (_[e.k] = null))
    }
  }
  if (h(p)) un(p, f, 12, [l, _])
  else {
    let t = g(p),
      n = R(p)
    if (t || n) {
      let i = () => {
        if (e.f) {
          let n = t ? (b(p) ? v[p] : _[p]) : x(p) || !e.k ? p.value : _[e.k]
          if (o) d(n) && c(n, s)
          else if (d(n)) n.includes(s) || n.push(s)
          else if (t) ((_[p] = [s]), b(p) && (v[p] = _[p]))
          else {
            let t = [s]
            ;(x(p, e.k) && (p.value = t), e.k && (_[e.k] = t))
          }
        } else t ? ((_[p] = l), b(p) && (v[p] = l)) : n && (x(p, e.k) && (p.value = l), e.k && (_[e.k] = l))
      }
      if (l) {
        let t = () => {
          ;(i(), Cr.delete(e))
        }
        ;((t.id = -1), Cr.set(e, t), Ki(t, r))
      } else (Tr(e), i())
    }
  }
}
function Tr(e) {
  let t = Cr.get(e)
  t && ((t.flags |= 8), Cr.delete(e))
}
;(ae().requestIdleCallback, ae().cancelIdleCallback)
var Er = (e) => !!e.type.__asyncLoader,
  Dr = (e) => e.type.__isKeepAlive
function Or(e, t) {
  Ar(e, `a`, t)
}
function kr(e, t) {
  Ar(e, `da`, t)
}
function Ar(e, t, n = Ma) {
  let r = (e.__wdc ||= () => {
    let t = n
    for (; t; ) {
      if (t.isDeactivated) return
      t = t.parent
    }
    return e()
  })
  if ((Mr(t, r, n), n)) {
    let e = n.parent
    for (; e && e.parent; ) (Dr(e.parent.vnode) && jr(r, t, n, e), (e = e.parent))
  }
}
function jr(e, t, n, r) {
  let i = Mr(t, e, r, !0)
  zr(() => {
    c(r[t], i)
  }, n)
}
function Mr(e, t, n = Ma, r = !1) {
  if (n) {
    let i = n[e] || (n[e] = []),
      a = (t.__weh ||= (...r) => {
        Be()
        let i = Ia(n),
          a = dn(t, n, e, r)
        return (i(), Ve(), a)
      })
    return (r ? i.unshift(a) : i.push(a), a)
  }
}
var Nr =
    (e) =>
    (t, n = Ma) => {
      ;(!za || e === `sp`) && Mr(e, (...e) => t(...e), n)
    },
  Pr = Nr(`bm`),
  Fr = Nr(`m`),
  Ir = Nr(`bu`),
  Lr = Nr(`u`),
  Rr = Nr(`bum`),
  zr = Nr(`um`),
  Br = Nr(`sp`),
  Vr = Nr(`rtg`),
  Hr = Nr(`rtc`)
function Ur(e, t = Ma) {
  Mr(`ec`, e, t)
}
var Wr = Symbol.for(`v-ndc`)
function Gr(e, t, n, r) {
  let i,
    a = n && n[r],
    o = d(e)
  if (o || g(e)) {
    let n = o && Rt(e),
      r = !1,
      s = !1
    ;(n && ((r = !Bt(e)), (s = zt(e)), (e = tt(e))), (i = Array(e.length)))
    for (let n = 0, o = e.length; n < o; n++) i[n] = t(r ? (s ? Wt(Ut(e[n])) : Ut(e[n])) : e[n], n, void 0, a && a[n])
  } else if (typeof e == `number`) {
    i = Array(e)
    for (let n = 0; n < e; n++) i[n] = t(n + 1, n, void 0, a && a[n])
  } else if (v(e))
    if (e[Symbol.iterator]) i = Array.from(e, (e, n) => t(e, n, void 0, a && a[n]))
    else {
      let n = Object.keys(e)
      i = Array(n.length)
      for (let r = 0, o = n.length; r < o; r++) {
        let o = n[r]
        i[r] = t(e[o], o, r, a && a[r])
      }
    }
  else i = []
  return (n && (n[r] = i), i)
}
var Kr = (e) => (e ? (Ra(e) ? Ja(e) : Kr(e.parent)) : null),
  qr = s(Object.create(null), {
    $: (e) => e,
    $el: (e) => e.vnode.el,
    $data: (e) => e.data,
    $props: (e) => e.props,
    $attrs: (e) => e.attrs,
    $slots: (e) => e.slots,
    $refs: (e) => e.refs,
    $parent: (e) => Kr(e.parent),
    $root: (e) => Kr(e.root),
    $host: (e) => e.ce,
    $emit: (e) => e.emit,
    $options: (e) => ni(e),
    $forceUpdate: (e) =>
      (e.f ||= () => {
        Cn(e.update)
      }),
    $nextTick: (e) => (e.n ||= xn.bind(e.proxy)),
    $watch: (e) => Un.bind(e),
  }),
  Jr = (e, n) => e !== t && !e.__isScriptSetup && u(e, n),
  Yr = {
    get({ _: e }, n) {
      if (n === `__v_skip`) return !0
      let { ctx: r, setupState: i, data: a, props: o, accessCache: s, type: c, appContext: l } = e
      if (n[0] !== `$`) {
        let e = s[n]
        if (e !== void 0)
          switch (e) {
            case 1:
              return i[n]
            case 2:
              return a[n]
            case 4:
              return r[n]
            case 3:
              return o[n]
          }
        else if (Jr(i, n)) return ((s[n] = 1), i[n])
        else if (a !== t && u(a, n)) return ((s[n] = 2), a[n])
        else if (u(o, n)) return ((s[n] = 3), o[n])
        else if (r !== t && u(r, n)) return ((s[n] = 4), r[n])
        else Zr && (s[n] = 0)
      }
      let d = qr[n],
        f,
        p
      if (d) return (n === `$attrs` && Ze(e.attrs, `get`, ``), d(e))
      if ((f = c.__cssModules) && (f = f[n])) return f
      if (r !== t && u(r, n)) return ((s[n] = 4), r[n])
      if (((p = l.config.globalProperties), u(p, n))) return p[n]
    },
    set({ _: e }, n, r) {
      let { data: i, setupState: a, ctx: o } = e
      return Jr(a, n)
        ? ((a[n] = r), !0)
        : i !== t && u(i, n)
          ? ((i[n] = r), !0)
          : u(e.props, n) || (n[0] === `$` && n.slice(1) in e)
            ? !1
            : ((o[n] = r), !0)
    },
    has({ _: { data: e, setupState: n, accessCache: r, ctx: i, appContext: a, props: o, type: s } }, c) {
      let l
      return !!(
        r[c] ||
        (e !== t && c[0] !== `$` && u(e, c)) ||
        Jr(n, c) ||
        u(o, c) ||
        u(i, c) ||
        u(qr, c) ||
        u(a.config.globalProperties, c) ||
        ((l = s.__cssModules) && l[c])
      )
    },
    defineProperty(e, t, n) {
      return (n.get == null ? u(n, `value`) && this.set(e, t, n.value, null) : (e._.accessCache[t] = 0), Reflect.defineProperty(e, t, n))
    },
  }
function Xr(e) {
  return d(e) ? e.reduce((e, t) => ((e[t] = null), e), {}) : e
}
var Zr = !0
function Qr(e) {
  let t = ni(e),
    n = e.proxy,
    i = e.ctx
  ;((Zr = !1), t.beforeCreate && ei(t.beforeCreate, e, `bc`))
  let {
    data: a,
    computed: o,
    methods: s,
    watch: c,
    provide: l,
    inject: u,
    created: f,
    beforeMount: p,
    mounted: m,
    beforeUpdate: g,
    updated: _,
    activated: y,
    deactivated: b,
    beforeDestroy: x,
    beforeUnmount: S,
    destroyed: C,
    unmounted: w,
    render: T,
    renderTracked: E,
    renderTriggered: D,
    errorCaptured: O,
    serverPrefetch: k,
    expose: A,
    inheritAttrs: j,
    components: ee,
    directives: M,
    filters: te,
  } = t
  if ((u && $r(u, i, null), s))
    for (let e in s) {
      let t = s[e]
      h(t) && (i[e] = t.bind(n))
    }
  if (a) {
    let t = a.call(n, n)
    v(t) && (e.data = Pt(t))
  }
  if (((Zr = !0), o))
    for (let e in o) {
      let t = o[e],
        a = q({
          get: h(t) ? t.bind(n, n) : h(t.get) ? t.get.bind(n, n) : r,
          set: !h(t) && h(t.set) ? t.set.bind(n) : r,
        })
      Object.defineProperty(i, e, {
        enumerable: !0,
        configurable: !0,
        get: () => a.value,
        set: (e) => (a.value = e),
      })
    }
  if (c) for (let e in c) ti(c[e], i, n, e)
  if (l) {
    let e = h(l) ? l.call(n) : l
    Reflect.ownKeys(e).forEach((t) => {
      In(t, e[t])
    })
  }
  f && ei(f, e, `c`)
  function N(e, t) {
    d(t) ? t.forEach((t) => e(t.bind(n))) : t && e(t.bind(n))
  }
  if ((N(Pr, p), N(Fr, m), N(Ir, g), N(Lr, _), N(Or, y), N(kr, b), N(Ur, O), N(Hr, E), N(Vr, D), N(Rr, S), N(zr, w), N(Br, k), d(A)))
    if (A.length) {
      let t = (e.exposed ||= {})
      A.forEach((e) => {
        Object.defineProperty(t, e, { get: () => n[e], set: (t) => (n[e] = t), enumerable: !0 })
      })
    } else e.exposed ||= {}
  ;(T && e.render === r && (e.render = T),
    j != null && (e.inheritAttrs = j),
    ee && (e.components = ee),
    M && (e.directives = M),
    k && xr(e))
}
function $r(e, t, n = r) {
  d(e) && (e = si(e))
  for (let n in e) {
    let r = e[n],
      i
    ;((i = v(r) ? (`default` in r ? Ln(r.from || n, r.default, !0) : Ln(r.from || n)) : Ln(r)),
      R(i)
        ? Object.defineProperty(t, n, {
            enumerable: !0,
            configurable: !0,
            get: () => i.value,
            set: (e) => (i.value = e),
          })
        : (t[n] = i))
  }
}
function ei(e, t, n) {
  dn(d(e) ? e.map((e) => e.bind(t.proxy)) : e.bind(t.proxy), t, n)
}
function ti(e, t, n, r) {
  let i = r.includes(`.`) ? Wn(n, r) : () => n[r]
  if (g(e)) {
    let n = t[e]
    h(n) && Vn(i, n)
  } else if (h(e)) Vn(i, e.bind(n))
  else if (v(e))
    if (d(e)) e.forEach((e) => ti(e, t, n, r))
    else {
      let r = h(e.handler) ? e.handler.bind(n) : t[e.handler]
      h(r) && Vn(i, r, e)
    }
}
function ni(e) {
  let t = e.type,
    { mixins: n, extends: r } = t,
    {
      mixins: i,
      optionsCache: a,
      config: { optionMergeStrategies: o },
    } = e.appContext,
    s = a.get(t),
    c
  return (
    s ? (c = s) : !i.length && !n && !r ? (c = t) : ((c = {}), i.length && i.forEach((e) => ri(c, e, o, !0)), ri(c, t, o)),
    v(t) && a.set(t, c),
    c
  )
}
function ri(e, t, n, r = !1) {
  let { mixins: i, extends: a } = t
  ;(a && ri(e, a, n, !0), i && i.forEach((t) => ri(e, t, n, !0)))
  for (let i in t)
    if (!(r && i === `expose`)) {
      let r = ii[i] || (n && n[i])
      e[i] = r ? r(e[i], t[i]) : t[i]
    }
  return e
}
var ii = {
  data: ai,
  props: ui,
  emits: ui,
  methods: li,
  computed: li,
  beforeCreate: ci,
  created: ci,
  beforeMount: ci,
  mounted: ci,
  beforeUpdate: ci,
  updated: ci,
  beforeDestroy: ci,
  beforeUnmount: ci,
  destroyed: ci,
  unmounted: ci,
  activated: ci,
  deactivated: ci,
  errorCaptured: ci,
  serverPrefetch: ci,
  components: li,
  directives: li,
  watch: di,
  provide: ai,
  inject: oi,
}
function ai(e, t) {
  return t
    ? e
      ? function () {
          return s(h(e) ? e.call(this, this) : e, h(t) ? t.call(this, this) : t)
        }
      : t
    : e
}
function oi(e, t) {
  return li(si(e), si(t))
}
function si(e) {
  if (d(e)) {
    let t = {}
    for (let n = 0; n < e.length; n++) t[e[n]] = e[n]
    return t
  }
  return e
}
function ci(e, t) {
  return e ? [...new Set([].concat(e, t))] : t
}
function li(e, t) {
  return e ? s(Object.create(null), e, t) : t
}
function ui(e, t) {
  return e ? (d(e) && d(t) ? [...new Set([...e, ...t])] : s(Object.create(null), Xr(e), Xr(t ?? {}))) : t
}
function di(e, t) {
  if (!e) return t
  if (!t) return e
  let n = s(Object.create(null), e)
  for (let r in t) n[r] = ci(e[r], t[r])
  return n
}
function fi() {
  return {
    app: null,
    config: {
      isNativeTag: i,
      performance: !1,
      globalProperties: {},
      optionMergeStrategies: {},
      errorHandler: void 0,
      warnHandler: void 0,
      compilerOptions: {},
    },
    mixins: [],
    components: {},
    directives: {},
    provides: Object.create(null),
    optionsCache: new WeakMap(),
    propsCache: new WeakMap(),
    emitsCache: new WeakMap(),
  }
}
var pi = 0
function mi(e, t) {
  return function (n, r = null) {
    ;(h(n) || (n = s({}, n)), r != null && !v(r) && (r = null))
    let i = fi(),
      a = new WeakSet(),
      o = [],
      c = !1,
      l = (i.app = {
        _uid: pi++,
        _component: n,
        _props: r,
        _container: null,
        _context: i,
        _instance: null,
        version: Za,
        get config() {
          return i.config
        },
        set config(e) {},
        use(e, ...t) {
          return (a.has(e) || (e && h(e.install) ? (a.add(e), e.install(l, ...t)) : h(e) && (a.add(e), e(l, ...t))), l)
        },
        mixin(e) {
          return (i.mixins.includes(e) || i.mixins.push(e), l)
        },
        component(e, t) {
          return t ? ((i.components[e] = t), l) : i.components[e]
        },
        directive(e, t) {
          return t ? ((i.directives[e] = t), l) : i.directives[e]
        },
        mount(a, o, s) {
          if (!c) {
            let u = l._ceVNode || G(n, r)
            return (
              (u.appContext = i),
              s === !0 ? (s = `svg`) : s === !1 && (s = void 0),
              o && t ? t(u, a) : e(u, a, s),
              (c = !0),
              (l._container = a),
              (a.__vue_app__ = l),
              Ja(u.component)
            )
          }
        },
        onUnmount(e) {
          o.push(e)
        },
        unmount() {
          c && (dn(o, l._instance, 16), e(null, l._container), delete l._container.__vue_app__)
        },
        provide(e, t) {
          return ((i.provides[e] = t), l)
        },
        runWithContext(e) {
          let t = hi
          hi = l
          try {
            return e()
          } finally {
            hi = t
          }
        },
      })
    return l
  }
}
var hi = null,
  gi = (e, t) =>
    t === `modelValue` || t === `model-value` ? e.modelModifiers : e[`${t}Modifiers`] || e[`${O(t)}Modifiers`] || e[`${A(t)}Modifiers`]
function _i(e, n, ...r) {
  if (e.isUnmounted) return
  let i = e.vnode.props || t,
    a = r,
    o = n.startsWith(`update:`),
    s = o && gi(i, n.slice(7))
  s && (s.trim && (a = r.map((e) => (g(e) ? e.trim() : e))), s.number && (a = r.map(ne)))
  let c,
    l = i[(c = ee(n))] || i[(c = ee(O(n)))]
  ;(!l && o && (l = i[(c = ee(A(n)))]), l && dn(l, e, 6, a))
  let u = i[c + `Once`]
  if (u) {
    if (!e.emitted) e.emitted = {}
    else if (e.emitted[c]) return
    ;((e.emitted[c] = !0), dn(u, e, 6, a))
  }
}
var vi = new WeakMap()
function yi(e, t, n = !1) {
  let r = n ? vi : t.emitsCache,
    i = r.get(e)
  if (i !== void 0) return i
  let a = e.emits,
    o = {},
    c = !1
  if (!h(e)) {
    let r = (e) => {
      let n = yi(e, t, !0)
      n && ((c = !0), s(o, n))
    }
    ;(!n && t.mixins.length && t.mixins.forEach(r), e.extends && r(e.extends), e.mixins && e.mixins.forEach(r))
  }
  return !a && !c ? (v(e) && r.set(e, null), null) : (d(a) ? a.forEach((e) => (o[e] = null)) : s(o, a), v(e) && r.set(e, o), o)
}
function bi(e, t) {
  return !e || !a(t) ? !1 : ((t = t.slice(2).replace(/Once$/, ``)), u(e, t[0].toLowerCase() + t.slice(1)) || u(e, A(t)) || u(e, t))
}
function xi(e) {
  let {
      type: t,
      vnode: n,
      proxy: r,
      withProxy: i,
      propsOptions: [a],
      slots: s,
      attrs: c,
      emit: l,
      render: u,
      renderCache: d,
      props: f,
      data: p,
      setupState: m,
      ctx: h,
      inheritAttrs: g,
    } = e,
    _ = Mn(e),
    v,
    y
  try {
    if (n.shapeFlag & 4) {
      let e = i || r,
        t = e
      ;((v = wa(u.call(t, e, d, f, m, p, h))), (y = c))
    } else {
      let e = t
      ;((v = wa(e.length > 1 ? e(f, { attrs: c, slots: s, emit: l }) : e(f, null))), (y = t.props ? c : Si(c)))
    }
  } catch (t) {
    ;((ca.length = 0), fn(t, e, 1), (v = G(oa)))
  }
  let b = v
  if (y && g !== !1) {
    let e = Object.keys(y),
      { shapeFlag: t } = b
    e.length && t & 7 && (a && e.some(o) && (y = Ci(y, a)), (b = xa(b, y, !1, !0)))
  }
  return (
    n.dirs && ((b = xa(b, null, !1, !0)), (b.dirs = b.dirs ? b.dirs.concat(n.dirs) : n.dirs)),
    n.transition && vr(b, n.transition),
    (v = b),
    Mn(_),
    v
  )
}
var Si = (e) => {
    let t
    for (let n in e) (n === `class` || n === `style` || a(n)) && ((t ||= {})[n] = e[n])
    return t
  },
  Ci = (e, t) => {
    let n = {}
    for (let r in e) (!o(r) || !(r.slice(9) in t)) && (n[r] = e[r])
    return n
  }
function wi(e, t, n) {
  let { props: r, children: i, component: a } = e,
    { props: o, children: s, patchFlag: c } = t,
    l = a.emitsOptions
  if (t.dirs || t.transition) return !0
  if (n && c >= 0) {
    if (c & 1024) return !0
    if (c & 16) return r ? Ti(r, o, l) : !!o
    if (c & 8) {
      let e = t.dynamicProps
      for (let t = 0; t < e.length; t++) {
        let n = e[t]
        if (Ei(o, r, n) && !bi(l, n)) return !0
      }
    }
  } else return (i || s) && (!s || !s.$stable) ? !0 : r === o ? !1 : r ? (o ? Ti(r, o, l) : !0) : !!o
  return !1
}
function Ti(e, t, n) {
  let r = Object.keys(t)
  if (r.length !== Object.keys(e).length) return !0
  for (let i = 0; i < r.length; i++) {
    let a = r[i]
    if (Ei(t, e, a) && !bi(n, a)) return !0
  }
  return !1
}
function Ei(e, t, n) {
  let r = e[n],
    i = t[n]
  return n === `style` && v(r) && v(i) ? !he(r, i) : r !== i
}
function Di({ vnode: e, parent: t, suspense: n }, r) {
  for (; t; ) {
    let n = t.subTree
    if ((n.suspense && n.suspense.activeBranch === e && ((n.suspense.vnode.el = n.el = r), (e = n)), n === e))
      (((e = t.vnode).el = r), (t = t.parent))
    else break
  }
  n && n.activeBranch === e && (n.vnode.el = r)
}
var Oi = {},
  ki = () => Object.create(Oi),
  Ai = (e) => Object.getPrototypeOf(e) === Oi
function ji(e, t, n, r = !1) {
  let i = {},
    a = ki()
  ;((e.propsDefaults = Object.create(null)), Ni(e, t, i, a))
  for (let t in e.propsOptions[0]) t in i || (i[t] = void 0)
  ;(n ? (e.props = r ? i : Ft(i)) : e.type.props ? (e.props = i) : (e.props = a), (e.attrs = a))
}
function Mi(e, t, n, r) {
  let {
      props: i,
      attrs: a,
      vnode: { patchFlag: o },
    } = e,
    s = L(i),
    [c] = e.propsOptions,
    l = !1
  if ((r || o > 0) && !(o & 16)) {
    if (o & 8) {
      let n = e.vnode.dynamicProps
      for (let r = 0; r < n.length; r++) {
        let o = n[r]
        if (bi(e.emitsOptions, o)) continue
        let d = t[o]
        if (c)
          if (u(a, o)) d !== a[o] && ((a[o] = d), (l = !0))
          else {
            let t = O(o)
            i[t] = Pi(c, s, t, d, e, !1)
          }
        else d !== a[o] && ((a[o] = d), (l = !0))
      }
    }
  } else {
    Ni(e, t, i, a) && (l = !0)
    let r
    for (let a in s)
      (!t || (!u(t, a) && ((r = A(a)) === a || !u(t, r)))) &&
        (c ? n && (n[a] !== void 0 || n[r] !== void 0) && (i[a] = Pi(c, s, a, void 0, e, !0)) : delete i[a])
    if (a !== s) for (let e in a) (!t || !u(t, e)) && (delete a[e], (l = !0))
  }
  l && Qe(e.attrs, `set`, ``)
}
function Ni(e, n, r, i) {
  let [a, o] = e.propsOptions,
    s = !1,
    c
  if (n)
    for (let t in n) {
      if (T(t)) continue
      let l = n[t],
        d
      a && u(a, (d = O(t)))
        ? !o || !o.includes(d)
          ? (r[d] = l)
          : ((c ||= {})[d] = l)
        : bi(e.emitsOptions, t) || ((!(t in i) || l !== i[t]) && ((i[t] = l), (s = !0)))
    }
  if (o) {
    let n = L(r),
      i = c || t
    for (let t = 0; t < o.length; t++) {
      let s = o[t]
      r[s] = Pi(a, n, s, i[s], e, !u(i, s))
    }
  }
  return s
}
function Pi(e, t, n, r, i, a) {
  let o = e[n]
  if (o != null) {
    let e = u(o, `default`)
    if (e && r === void 0) {
      let e = o.default
      if (o.type !== Function && !o.skipFactory && h(e)) {
        let { propsDefaults: a } = i
        if (n in a) r = a[n]
        else {
          let o = Ia(i)
          ;((r = a[n] = e.call(null, t)), o())
        }
      } else r = e
      i.ce && i.ce._setProp(n, r)
    }
    o[0] && (a && !e ? (r = !1) : o[1] && (r === `` || r === A(n)) && (r = !0))
  }
  return r
}
var Fi = new WeakMap()
function Ii(e, r, i = !1) {
  let a = i ? Fi : r.propsCache,
    o = a.get(e)
  if (o) return o
  let c = e.props,
    l = {},
    f = [],
    p = !1
  if (!h(e)) {
    let t = (e) => {
      p = !0
      let [t, n] = Ii(e, r, !0)
      ;(s(l, t), n && f.push(...n))
    }
    ;(!i && r.mixins.length && r.mixins.forEach(t), e.extends && t(e.extends), e.mixins && e.mixins.forEach(t))
  }
  if (!c && !p) return (v(e) && a.set(e, n), n)
  if (d(c))
    for (let e = 0; e < c.length; e++) {
      let n = O(c[e])
      Li(n) && (l[n] = t)
    }
  else if (c)
    for (let e in c) {
      let t = O(e)
      if (Li(t)) {
        let n = c[e],
          r = (l[t] = d(n) || h(n) ? { type: n } : s({}, n)),
          i = r.type,
          a = !1,
          o = !0
        if (d(i))
          for (let e = 0; e < i.length; ++e) {
            let t = i[e],
              n = h(t) && t.name
            if (n === `Boolean`) {
              a = !0
              break
            } else n === `String` && (o = !1)
          }
        else a = h(i) && i.name === `Boolean`
        ;((r[0] = a), (r[1] = o), (a || u(r, `default`)) && f.push(t))
      }
    }
  let m = [l, f]
  return (v(e) && a.set(e, m), m)
}
function Li(e) {
  return e[0] !== `$` && !T(e)
}
var Ri = (e) => e === `_` || e === `_ctx` || e === `$stable`,
  zi = (e) => (d(e) ? e.map(wa) : [wa(e)]),
  Bi = (e, t, n) => {
    if (t._n) return t
    let r = Nn((...e) => zi(t(...e)), n)
    return ((r._c = !1), r)
  },
  Vi = (e, t, n) => {
    let r = e._ctx
    for (let n in e) {
      if (Ri(n)) continue
      let i = e[n]
      if (h(i)) t[n] = Bi(n, i, r)
      else if (i != null) {
        let e = zi(i)
        t[n] = () => e
      }
    }
  },
  Hi = (e, t) => {
    let n = zi(t)
    e.slots.default = () => n
  },
  Ui = (e, t, n) => {
    for (let r in t) (n || !Ri(r)) && (e[r] = t[r])
  },
  Wi = (e, t, n) => {
    let r = (e.slots = ki())
    if (e.vnode.shapeFlag & 32) {
      let e = t._
      e ? (Ui(r, t, n), n && N(r, `_`, e, !0)) : Vi(t, r)
    } else t && Hi(e, t)
  },
  Gi = (e, n, r) => {
    let { vnode: i, slots: a } = e,
      o = !0,
      s = t
    if (i.shapeFlag & 32) {
      let e = n._
      ;(e ? (r && e === 1 ? (o = !1) : Ui(a, n, r)) : ((o = !n.$stable), Vi(n, a)), (s = n))
    } else n && (Hi(e, n), (s = { default: 1 }))
    if (o) for (let e in a) !Ri(e) && s[e] == null && delete a[e]
  },
  Ki = ia
function qi(e) {
  return Ji(e)
}
function Ji(e, i) {
  let a = ae()
  a.__VUE__ = !0
  let {
      insert: o,
      remove: s,
      patchProp: c,
      createElement: l,
      createText: u,
      createComment: d,
      setText: f,
      setElementText: p,
      parentNode: m,
      nextSibling: h,
      setScopeId: g = r,
      insertStaticContent: _,
    } = e,
    v = (e, t, n, r = null, i = null, a = null, o = void 0, s = null, c = !!t.dynamicChildren) => {
      if (e === t) return
      ;(e && !ga(e, t) && ((r = me(e)), ue(e, i, a, !0), (e = null)), t.patchFlag === -2 && ((c = !1), (t.dynamicChildren = null)))
      let { type: l, ref: u, shapeFlag: d } = t
      switch (l) {
        case aa:
          y(e, t, n, r)
          break
        case oa:
          b(e, t, n, r)
          break
        case sa:
          e ?? x(t, n, r, o)
          break
        case V:
          ee(e, t, n, r, i, a, o, s, c)
          break
        default:
          d & 1
            ? w(e, t, n, r, i, a, o, s, c)
            : d & 6
              ? M(e, t, n, r, i, a, o, s, c)
              : (d & 64 || d & 128) && l.process(e, t, n, r, i, a, o, s, c, F)
      }
      u != null && i ? wr(u, e && e.ref, a, t || e, !t) : u == null && e && e.ref != null && wr(e.ref, null, a, e, !0)
    },
    y = (e, t, n, r) => {
      if (e == null) o((t.el = u(t.children)), n, r)
      else {
        let n = (t.el = e.el)
        t.children !== e.children && f(n, t.children)
      }
    },
    b = (e, t, n, r) => {
      e == null ? o((t.el = d(t.children || ``)), n, r) : (t.el = e.el)
    },
    x = (e, t, n, r) => {
      ;[e.el, e.anchor] = _(e.children, t, n, r, e.el, e.anchor)
    },
    S = ({ el: e, anchor: t }, n, r) => {
      let i
      for (; e && e !== t; ) ((i = h(e)), o(e, n, r), (e = i))
      o(t, n, r)
    },
    C = ({ el: e, anchor: t }) => {
      let n
      for (; e && e !== t; ) ((n = h(e)), s(e), (e = n))
      s(t)
    },
    w = (e, t, n, r, i, a, o, s, c) => {
      if ((t.type === `svg` ? (o = `svg`) : t.type === `math` && (o = `mathml`), e == null)) E(t, n, r, i, a, o, s, c)
      else {
        let n = e.el && e.el._isVueCE ? e.el : null
        try {
          ;(n && n._beginPatch(), k(e, t, i, a, o, s, c))
        } finally {
          n && n._endPatch()
        }
      }
    },
    E = (e, t, n, r, i, a, s, u) => {
      let d,
        f,
        { props: m, shapeFlag: h, transition: g, dirs: _ } = e
      if (
        ((d = e.el = l(e.type, a, m && m.is, m)),
        h & 8 ? p(d, e.children) : h & 16 && O(e.children, d, null, r, i, Yi(e, a), s, u),
        _ && Fn(e, null, r, `created`),
        D(d, e, e.scopeId, s, r),
        m)
      ) {
        for (let e in m) e !== `value` && !T(e) && c(d, e, null, m[e], a, r)
        ;(`value` in m && c(d, `value`, null, m.value, a), (f = m.onVnodeBeforeMount) && Oa(f, r, e))
      }
      _ && Fn(e, null, r, `beforeMount`)
      let v = Zi(i, g)
      ;(v && g.beforeEnter(d),
        o(d, t, n),
        ((f = m && m.onVnodeMounted) || v || _) &&
          Ki(() => {
            try {
              ;(f && Oa(f, r, e), v && g.enter(d), _ && Fn(e, null, r, `mounted`))
            } finally {
            }
          }, i))
    },
    D = (e, t, n, r, i) => {
      if ((n && g(e, n), r)) for (let t = 0; t < r.length; t++) g(e, r[t])
      if (i) {
        let n = i.subTree
        if (t === n || (ra(n.type) && (n.ssContent === t || n.ssFallback === t))) {
          let t = i.vnode
          D(e, t, t.scopeId, t.slotScopeIds, i.parent)
        }
      }
    },
    O = (e, t, n, r, i, a, o, s, c = 0) => {
      for (let l = c; l < e.length; l++) v(null, (e[l] = s ? Ta(e[l]) : wa(e[l])), t, n, r, i, a, o, s)
    },
    k = (e, n, r, i, a, o, s) => {
      let l = (n.el = e.el),
        { patchFlag: u, dynamicChildren: d, dirs: f } = n
      u |= e.patchFlag & 16
      let m = e.props || t,
        h = n.props || t,
        g
      if (
        (r && Xi(r, !1),
        (g = h.onVnodeBeforeUpdate) && Oa(g, r, n, e),
        f && Fn(n, e, r, `beforeUpdate`),
        r && Xi(r, !0),
        ((m.innerHTML && h.innerHTML == null) || (m.textContent && h.textContent == null)) && p(l, ``),
        d ? A(e.dynamicChildren, d, l, r, i, Yi(n, a), o) : s || oe(e, n, l, null, r, i, Yi(n, a), o, !1),
        u > 0)
      ) {
        if (u & 16) j(l, m, h, r, a)
        else if ((u & 2 && m.class !== h.class && c(l, `class`, null, h.class, a), u & 4 && c(l, `style`, m.style, h.style, a), u & 8)) {
          let e = n.dynamicProps
          for (let t = 0; t < e.length; t++) {
            let n = e[t],
              i = m[n],
              o = h[n]
            ;(o !== i || n === `value`) && c(l, n, i, o, a, r)
          }
        }
        u & 1 && e.children !== n.children && p(l, n.children)
      } else !s && d == null && j(l, m, h, r, a)
      ;((g = h.onVnodeUpdated) || f) &&
        Ki(() => {
          ;(g && Oa(g, r, n, e), f && Fn(n, e, r, `updated`))
        }, i)
    },
    A = (e, t, n, r, i, a, o) => {
      for (let s = 0; s < t.length; s++) {
        let c = e[s],
          l = t[s]
        v(c, l, c.el && (c.type === V || !ga(c, l) || c.shapeFlag & 198) ? m(c.el) : n, null, r, i, a, o, !0)
      }
    },
    j = (e, n, r, i, a) => {
      if (n !== r) {
        if (n !== t) for (let t in n) !T(t) && !(t in r) && c(e, t, n[t], null, a, i)
        for (let t in r) {
          if (T(t)) continue
          let o = r[t],
            s = n[t]
          o !== s && t !== `value` && c(e, t, s, o, a, i)
        }
        ;`value` in r && c(e, `value`, n.value, r.value, a)
      }
    },
    ee = (e, t, n, r, i, a, s, c, l) => {
      let d = (t.el = e ? e.el : u(``)),
        f = (t.anchor = e ? e.anchor : u(``)),
        { patchFlag: p, dynamicChildren: m, slotScopeIds: h } = t
      ;(h && (c = c ? c.concat(h) : h),
        e == null
          ? (o(d, n, r), o(f, n, r), O(t.children || [], n, f, i, a, s, c, l))
          : p > 0 && p & 64 && m && e.dynamicChildren && e.dynamicChildren.length === m.length
            ? (A(e.dynamicChildren, m, n, i, a, s, c), (t.key != null || (i && t === i.subTree)) && Qi(e, t, !0))
            : oe(e, t, n, f, i, a, s, c, l))
    },
    M = (e, t, n, r, i, a, o, s, c) => {
      ;((t.slotScopeIds = s), e == null ? (t.shapeFlag & 512 ? i.ctx.activate(t, n, r, o, c) : N(t, n, r, i, a, o, c)) : ne(e, t, c))
    },
    N = (e, t, n, r, i, a, o) => {
      let s = (e.component = ja(e, r, i))
      if ((Dr(e) && (s.ctx.renderer = F), Ba(s, !1, o), s.asyncDep)) {
        if ((i && i.registerDep(s, re, o), !e.el)) {
          let r = (s.subTree = G(oa))
          ;(b(null, r, t, n), (e.placeholder = r.el))
        }
      } else re(s, e, t, n, i, a, o)
    },
    ne = (e, t, n) => {
      let r = (t.component = e.component)
      if (wi(e, t, n))
        if (r.asyncDep && !r.asyncResolved) {
          ie(r, t, n)
          return
        } else ((r.next = t), r.update())
      else ((t.el = e.el), (r.vnode = t))
    },
    re = (e, t, n, r, i, a, o) => {
      let s = () => {
        if (e.isMounted) {
          let { next: t, bu: n, u: r, parent: s, vnode: c } = e
          {
            let n = ea(e)
            if (n) {
              ;(t && ((t.el = c.el), ie(e, t, o)),
                n.asyncDep.then(() => {
                  Ki(() => {
                    e.isUnmounted || l()
                  }, i)
                }))
              return
            }
          }
          let u = t,
            d
          ;(Xi(e, !1),
            t ? ((t.el = c.el), ie(e, t, o)) : (t = c),
            n && te(n),
            (d = t.props && t.props.onVnodeBeforeUpdate) && Oa(d, s, t, c),
            Xi(e, !0))
          let f = xi(e),
            p = e.subTree
          ;((e.subTree = f),
            v(p, f, m(p.el), me(p), e, i, a),
            (t.el = f.el),
            u === null && Di(e, f.el),
            r && Ki(r, i),
            (d = t.props && t.props.onVnodeUpdated) && Ki(() => Oa(d, s, t, c), i))
        } else {
          let o,
            { el: s, props: c } = t,
            { bm: l, m: u, parent: d, root: f, type: p } = e,
            m = Er(t)
          if ((Xi(e, !1), l && te(l), !m && (o = c && c.onVnodeBeforeMount) && Oa(o, d, t), Xi(e, !0), s && ve)) {
            let t = () => {
              ;((e.subTree = xi(e)), ve(s, e.subTree, e, i, null))
            }
            m && p.__asyncHydrate ? p.__asyncHydrate(s, e, t) : t()
          } else {
            f.ce && f.ce._hasShadowRoot() && f.ce._injectChildStyle(p, e.parent ? e.parent.type : void 0)
            let o = (e.subTree = xi(e))
            ;(v(null, o, n, r, e, i, a), (t.el = o.el))
          }
          if ((u && Ki(u, i), !m && (o = c && c.onVnodeMounted))) {
            let e = t
            Ki(() => Oa(o, d, e), i)
          }
          ;((t.shapeFlag & 256 || (d && Er(d.vnode) && d.vnode.shapeFlag & 256)) && e.a && Ki(e.a, i),
            (e.isMounted = !0),
            (t = n = r = null))
        }
      }
      e.scope.on()
      let c = (e.effect = new Te(s))
      e.scope.off()
      let l = (e.update = c.run.bind(c)),
        u = (e.job = c.runIfDirty.bind(c))
      ;((u.i = e), (u.id = e.uid), (c.scheduler = () => Cn(u)), Xi(e, !0), l())
    },
    ie = (e, t, n) => {
      t.component = e
      let r = e.vnode.props
      ;((e.vnode = t), (e.next = null), Mi(e, t.props, r, n), Gi(e, t.children, n), Be(), En(e), Ve())
    },
    oe = (e, t, n, r, i, a, o, s, c = !1) => {
      let l = e && e.children,
        u = e ? e.shapeFlag : 0,
        d = t.children,
        { patchFlag: f, shapeFlag: m } = t
      if (f > 0) {
        if (f & 128) {
          ce(l, d, n, r, i, a, o, s, c)
          return
        } else if (f & 256) {
          se(l, d, n, r, i, a, o, s, c)
          return
        }
      }
      m & 8
        ? (u & 16 && pe(l, i, a), d !== l && p(n, d))
        : u & 16
          ? m & 16
            ? ce(l, d, n, r, i, a, o, s, c)
            : pe(l, i, a, !0)
          : (u & 8 && p(n, ``), m & 16 && O(d, n, r, i, a, o, s, c))
    },
    se = (e, t, r, i, a, o, s, c, l) => {
      ;((e ||= n), (t ||= n))
      let u = e.length,
        d = t.length,
        f = Math.min(u, d),
        p
      for (p = 0; p < f; p++) {
        let n = (t[p] = l ? Ta(t[p]) : wa(t[p]))
        v(e[p], n, r, null, a, o, s, c, l)
      }
      u > d ? pe(e, a, o, !0, !1, f) : O(t, r, i, a, o, s, c, l, f)
    },
    ce = (e, t, r, i, a, o, s, c, l) => {
      let u = 0,
        d = t.length,
        f = e.length - 1,
        p = d - 1
      for (; u <= f && u <= p; ) {
        let n = e[u],
          i = (t[u] = l ? Ta(t[u]) : wa(t[u]))
        if (ga(n, i)) v(n, i, r, null, a, o, s, c, l)
        else break
        u++
      }
      for (; u <= f && u <= p; ) {
        let n = e[f],
          i = (t[p] = l ? Ta(t[p]) : wa(t[p]))
        if (ga(n, i)) v(n, i, r, null, a, o, s, c, l)
        else break
        ;(f--, p--)
      }
      if (u > f) {
        if (u <= p) {
          let e = p + 1,
            n = e < d ? t[e].el : i
          for (; u <= p; ) (v(null, (t[u] = l ? Ta(t[u]) : wa(t[u])), r, n, a, o, s, c, l), u++)
        }
      } else if (u > p) for (; u <= f; ) (ue(e[u], a, o, !0), u++)
      else {
        let m = u,
          h = u,
          g = new Map()
        for (u = h; u <= p; u++) {
          let e = (t[u] = l ? Ta(t[u]) : wa(t[u]))
          e.key != null && g.set(e.key, u)
        }
        let _,
          y = 0,
          b = p - h + 1,
          x = !1,
          S = 0,
          C = Array(b)
        for (u = 0; u < b; u++) C[u] = 0
        for (u = m; u <= f; u++) {
          let n = e[u]
          if (y >= b) {
            ue(n, a, o, !0)
            continue
          }
          let i
          if (n.key != null) i = g.get(n.key)
          else
            for (_ = h; _ <= p; _++)
              if (C[_ - h] === 0 && ga(n, t[_])) {
                i = _
                break
              }
          i === void 0 ? ue(n, a, o, !0) : ((C[i - h] = u + 1), i >= S ? (S = i) : (x = !0), v(n, t[i], r, null, a, o, s, c, l), y++)
        }
        let w = x ? $i(C) : n
        for (_ = w.length - 1, u = b - 1; u >= 0; u--) {
          let e = h + u,
            n = t[e],
            f = t[e + 1],
            p = e + 1 < d ? f.el || na(f) : i
          C[u] === 0 ? v(null, n, r, p, a, o, s, c, l) : x && (_ < 0 || u !== w[_] ? le(n, r, p, 2) : _--)
        }
      }
    },
    le = (e, t, n, r, i = null) => {
      let { el: a, type: c, transition: l, children: u, shapeFlag: d } = e
      if (d & 6) {
        le(e.component.subTree, t, n, r)
        return
      }
      if (d & 128) {
        e.suspense.move(t, n, r)
        return
      }
      if (d & 64) {
        c.move(e, t, n, F)
        return
      }
      if (c === V) {
        o(a, t, n)
        for (let e = 0; e < u.length; e++) le(u[e], t, n, r)
        o(e.anchor, t, n)
        return
      }
      if (c === sa) {
        S(e, t, n)
        return
      }
      if (r !== 2 && d & 1 && l)
        if (r === 0) (l.beforeEnter(a), o(a, t, n), Ki(() => l.enter(a), i))
        else {
          let { leave: r, delayLeave: i, afterLeave: c } = l,
            u = () => {
              e.ctx.isUnmounted ? s(a) : o(a, t, n)
            },
            d = () => {
              ;(a._isLeaving && a[ar](!0),
                r(a, () => {
                  ;(u(), c && c())
                }))
            }
          i ? i(a, u, d) : d()
        }
      else o(a, t, n)
    },
    ue = (e, t, n, r = !1, i = !1) => {
      let { type: a, props: o, ref: s, children: c, dynamicChildren: l, shapeFlag: u, patchFlag: d, dirs: f, cacheIndex: p, memo: m } = e
      if ((d === -2 && (i = !1), s != null && (Be(), wr(s, null, n, e, !0), Ve()), p != null && (t.renderCache[p] = void 0), u & 256)) {
        t.ctx.deactivate(e)
        return
      }
      let h = u & 1 && f,
        g = !Er(e),
        _
      if ((g && (_ = o && o.onVnodeBeforeUnmount) && Oa(_, t, e), u & 6)) fe(e.component, n, r)
      else {
        if (u & 128) {
          e.suspense.unmount(n, r)
          return
        }
        ;(h && Fn(e, null, t, `beforeUnmount`),
          u & 64
            ? e.type.remove(e, t, n, F, r)
            : l && !l.hasOnce && (a !== V || (d > 0 && d & 64))
              ? pe(l, t, n, !1, !0)
              : ((a === V && d & 384) || (!i && u & 16)) && pe(c, t, n),
          r && P(e))
      }
      let v = m != null && p == null
      ;((g && (_ = o && o.onVnodeUnmounted)) || h || v) &&
        Ki(() => {
          ;(_ && Oa(_, t, e), h && Fn(e, null, t, `unmounted`), v && (e.el = null))
        }, n)
    },
    P = (e) => {
      let { type: t, el: n, anchor: r, transition: i } = e
      if (t === V) {
        de(n, r)
        return
      }
      if (t === sa) {
        C(e)
        return
      }
      let a = () => {
        ;(s(n), i && !i.persisted && i.afterLeave && i.afterLeave())
      }
      if (e.shapeFlag & 1 && i && !i.persisted) {
        let { leave: t, delayLeave: r } = i,
          o = () => t(n, a)
        r ? r(e.el, a, o) : o()
      } else a()
    },
    de = (e, t) => {
      let n
      for (; e !== t; ) ((n = h(e)), s(e), (e = n))
      s(t)
    },
    fe = (e, t, n) => {
      let { bum: r, scope: i, job: a, subTree: o, um: s, m: c, a: l } = e
      ;(ta(c),
        ta(l),
        r && te(r),
        i.stop(),
        a && ((a.flags |= 8), ue(o, e, t, n)),
        s && Ki(s, t),
        Ki(() => {
          e.isUnmounted = !0
        }, t))
    },
    pe = (e, t, n, r = !1, i = !1, a = 0) => {
      for (let o = a; o < e.length; o++) ue(e[o], t, n, r, i)
    },
    me = (e) => {
      if (e.shapeFlag & 6) return me(e.component.subTree)
      if (e.shapeFlag & 128) return e.suspense.next()
      let t = h(e.anchor || e.el),
        n = t && t[Kn]
      return n ? h(n) : t
    },
    he = !1,
    ge = (e, t, n) => {
      let r
      ;(e == null ? t._vnode && (ue(t._vnode, null, null, !0), (r = t._vnode.component)) : v(t._vnode || null, e, t, null, null, null, n),
        (t._vnode = e),
        (he ||= ((he = !0), En(r), Dn(), !1)))
    },
    F = { p: v, um: ue, m: le, r: P, mt: N, mc: O, pc: oe, pbc: A, n: me, o: e },
    _e,
    ve
  return (i && ([_e, ve] = i(F)), { render: ge, hydrate: _e, createApp: mi(ge, _e) })
}
function Yi({ type: e, props: t }, n) {
  return (n === `svg` && e === `foreignObject`) ||
    (n === `mathml` && e === `annotation-xml` && t && t.encoding && t.encoding.includes(`html`))
    ? void 0
    : n
}
function Xi({ effect: e, job: t }, n) {
  n ? ((e.flags |= 32), (t.flags |= 4)) : ((e.flags &= -33), (t.flags &= -5))
}
function Zi(e, t) {
  return (!e || (e && !e.pendingBranch)) && t && !t.persisted
}
function Qi(e, t, n = !1) {
  let r = e.children,
    i = t.children
  if (d(r) && d(i))
    for (let e = 0; e < r.length; e++) {
      let t = r[e],
        a = i[e]
      ;(a.shapeFlag & 1 &&
        !a.dynamicChildren &&
        ((a.patchFlag <= 0 || a.patchFlag === 32) && ((a = i[e] = Ta(i[e])), (a.el = t.el)), !n && a.patchFlag !== -2 && Qi(t, a)),
        a.type === aa && (a.patchFlag === -1 && (a = i[e] = Ta(a)), (a.el = t.el)),
        a.type === oa && !a.el && (a.el = t.el))
    }
}
function $i(e) {
  let t = e.slice(),
    n = [0],
    r,
    i,
    a,
    o,
    s,
    c = e.length
  for (r = 0; r < c; r++) {
    let c = e[r]
    if (c !== 0) {
      if (((i = n[n.length - 1]), e[i] < c)) {
        ;((t[r] = i), n.push(r))
        continue
      }
      for (a = 0, o = n.length - 1; a < o; ) ((s = (a + o) >> 1), e[n[s]] < c ? (a = s + 1) : (o = s))
      c < e[n[a]] && (a > 0 && (t[r] = n[a - 1]), (n[a] = r))
    }
  }
  for (a = n.length, o = n[a - 1]; a-- > 0; ) ((n[a] = o), (o = t[o]))
  return n
}
function ea(e) {
  let t = e.subTree.component
  if (t) return t.asyncDep && !t.asyncResolved ? t : ea(t)
}
function ta(e) {
  if (e) for (let t = 0; t < e.length; t++) e[t].flags |= 8
}
function na(e) {
  if (e.placeholder) return e.placeholder
  let t = e.component
  return t ? na(t.subTree) : null
}
var ra = (e) => e.__isSuspense
function ia(e, t) {
  t && t.pendingBranch ? (d(e) ? t.effects.push(...e) : t.effects.push(e)) : Tn(e)
}
var V = Symbol.for(`v-fgt`),
  aa = Symbol.for(`v-txt`),
  oa = Symbol.for(`v-cmt`),
  sa = Symbol.for(`v-stc`),
  ca = [],
  la = null
function H(e = !1) {
  ca.push((la = e ? null : []))
}
function ua() {
  ;(ca.pop(), (la = ca[ca.length - 1] || null))
}
var da = 1
function fa(e, t = !1) {
  ;((da += e), e < 0 && la && t && (la.hasOnce = !0))
}
function pa(e) {
  return ((e.dynamicChildren = da > 0 ? la || n : null), ua(), da > 0 && la && la.push(e), e)
}
function U(e, t, n, r, i, a) {
  return pa(W(e, t, n, r, i, a, !0))
}
function ma(e, t, n, r, i) {
  return pa(G(e, t, n, r, i, !0))
}
function ha(e) {
  return e ? e.__v_isVNode === !0 : !1
}
function ga(e, t) {
  return e.type === t.type && e.key === t.key
}
var _a = ({ key: e }) => e ?? null,
  va = ({ ref: e, ref_key: t, ref_for: n }) => (
    typeof e == `number` && (e = `` + e),
    e == null ? null : g(e) || R(e) || h(e) ? { i: An, r: e, k: t, f: !!n } : e
  )
function W(e, t = null, n = null, r = 0, i = null, a = e === V ? 0 : 1, o = !1, s = !1) {
  let c = {
    __v_isVNode: !0,
    __v_skip: !0,
    type: e,
    props: t,
    key: t && _a(t),
    ref: t && va(t),
    scopeId: jn,
    slotScopeIds: null,
    children: n,
    component: null,
    suspense: null,
    ssContent: null,
    ssFallback: null,
    dirs: null,
    transition: null,
    el: null,
    anchor: null,
    target: null,
    targetStart: null,
    targetAnchor: null,
    staticCount: 0,
    shapeFlag: a,
    patchFlag: r,
    dynamicProps: i,
    dynamicChildren: null,
    appContext: null,
    ctx: An,
  }
  return (
    s ? (Ea(c, n), a & 128 && e.normalize(c)) : n && (c.shapeFlag |= g(n) ? 8 : 16),
    da > 0 && !o && la && (c.patchFlag > 0 || a & 6) && c.patchFlag !== 32 && la.push(c),
    c
  )
}
var G = ya
function ya(e, t = null, n = null, r = 0, i = null, a = !1) {
  if (((!e || e === Wr) && (e = oa), ha(e))) {
    let r = xa(e, t, !0)
    return (n && Ea(r, n), da > 0 && !a && la && (r.shapeFlag & 6 ? (la[la.indexOf(e)] = r) : la.push(r)), (r.patchFlag = -2), r)
  }
  if ((Ya(e) && (e = e.__vccOpts), t)) {
    t = ba(t)
    let { class: e, style: n } = t
    ;(e && !g(e) && (t.class = P(e)), v(n) && (Vt(n) && !d(n) && (n = s({}, n)), (t.style = oe(n))))
  }
  let o = g(e) ? 1 : ra(e) ? 128 : qn(e) ? 64 : v(e) ? 4 : h(e) ? 2 : 0
  return W(e, t, n, r, i, o, a, !0)
}
function ba(e) {
  return e ? (Vt(e) || Ai(e) ? s({}, e) : e) : null
}
function xa(e, t, n = !1, r = !1) {
  let { props: i, ref: a, patchFlag: o, children: s, transition: c } = e,
    l = t ? Da(i || {}, t) : i,
    u = {
      __v_isVNode: !0,
      __v_skip: !0,
      type: e.type,
      props: l,
      key: l && _a(l),
      ref: t && t.ref ? (n && a ? (d(a) ? a.concat(va(t)) : [a, va(t)]) : va(t)) : a,
      scopeId: e.scopeId,
      slotScopeIds: e.slotScopeIds,
      children: s,
      target: e.target,
      targetStart: e.targetStart,
      targetAnchor: e.targetAnchor,
      staticCount: e.staticCount,
      shapeFlag: e.shapeFlag,
      patchFlag: t && e.type !== V ? (o === -1 ? 16 : o | 16) : o,
      dynamicProps: e.dynamicProps,
      dynamicChildren: e.dynamicChildren,
      appContext: e.appContext,
      dirs: e.dirs,
      transition: c,
      component: e.component,
      suspense: e.suspense,
      ssContent: e.ssContent && xa(e.ssContent),
      ssFallback: e.ssFallback && xa(e.ssFallback),
      placeholder: e.placeholder,
      el: e.el,
      anchor: e.anchor,
      ctx: e.ctx,
      ce: e.ce,
    }
  return (c && r && vr(u, c.clone(u)), u)
}
function Sa(e = ` `, t = 0) {
  return G(aa, null, e, t)
}
function Ca(e, t) {
  let n = G(sa, null, e)
  return ((n.staticCount = t), n)
}
function K(e = ``, t = !1) {
  return t ? (H(), ma(oa, null, e)) : G(oa, null, e)
}
function wa(e) {
  return e == null || typeof e == `boolean` ? G(oa) : d(e) ? G(V, null, e.slice()) : ha(e) ? Ta(e) : G(aa, null, String(e))
}
function Ta(e) {
  return (e.el === null && e.patchFlag !== -1) || e.memo ? e : xa(e)
}
function Ea(e, t) {
  let n = 0,
    { shapeFlag: r } = e
  if (t == null) t = null
  else if (d(t)) n = 16
  else if (typeof t == `object`)
    if (r & 65) {
      let n = t.default
      n && (n._c && (n._d = !1), Ea(e, n()), n._c && (n._d = !0))
      return
    } else {
      n = 32
      let r = t._
      !r && !Ai(t) ? (t._ctx = An) : r === 3 && An && (An.slots._ === 1 ? (t._ = 1) : ((t._ = 2), (e.patchFlag |= 1024)))
    }
  else h(t) ? ((t = { default: t, _ctx: An }), (n = 32)) : ((t = String(t)), r & 64 ? ((n = 16), (t = [Sa(t)])) : (n = 8))
  ;((e.children = t), (e.shapeFlag |= n))
}
function Da(...e) {
  let t = {}
  for (let n = 0; n < e.length; n++) {
    let r = e[n]
    for (let e in r)
      if (e === `class`) t.class !== r.class && (t.class = P([t.class, r.class]))
      else if (e === `style`) t.style = oe([t.style, r.style])
      else if (a(e)) {
        let n = t[e],
          i = r[e]
        i && n !== i && !(d(n) && n.includes(i)) ? (t[e] = n ? [].concat(n, i) : i) : i == null && n == null && !o(e) && (t[e] = i)
      } else e !== `` && (t[e] = r[e])
  }
  return t
}
function Oa(e, t, n, r = null) {
  dn(e, t, 7, [n, r])
}
var ka = fi(),
  Aa = 0
function ja(e, n, r) {
  let i = e.type,
    a = (n ? n.appContext : e.appContext) || ka,
    o = {
      uid: Aa++,
      vnode: e,
      type: i,
      parent: n,
      appContext: a,
      root: null,
      next: null,
      subTree: null,
      effect: null,
      update: null,
      job: null,
      scope: new be(!0),
      render: null,
      proxy: null,
      exposed: null,
      exposeProxy: null,
      withProxy: null,
      provides: n ? n.provides : Object.create(a.provides),
      ids: n ? n.ids : [``, 0, 0],
      accessCache: null,
      renderCache: [],
      components: null,
      directives: null,
      propsOptions: Ii(i, a),
      emitsOptions: yi(i, a),
      emit: null,
      emitted: null,
      propsDefaults: t,
      inheritAttrs: i.inheritAttrs,
      ctx: t,
      data: t,
      props: t,
      attrs: t,
      slots: t,
      refs: t,
      setupState: t,
      setupContext: null,
      suspense: r,
      suspenseId: r ? r.pendingId : 0,
      asyncDep: null,
      asyncResolved: !1,
      isMounted: !1,
      isUnmounted: !1,
      isDeactivated: !1,
      bc: null,
      c: null,
      bm: null,
      m: null,
      bu: null,
      u: null,
      um: null,
      bum: null,
      da: null,
      a: null,
      rtg: null,
      rtc: null,
      ec: null,
      sp: null,
    }
  return ((o.ctx = { _: o }), (o.root = n ? n.root : o), (o.emit = _i.bind(null, o)), e.ce && e.ce(o), o)
}
var Ma = null,
  Na = () => Ma || An,
  Pa,
  Fa
{
  let e = ae(),
    t = (t, n) => {
      let r
      return (
        (r = e[t]) || (r = e[t] = []),
        r.push(n),
        (e) => {
          r.length > 1 ? r.forEach((t) => t(e)) : r[0](e)
        }
      )
    }
  ;((Pa = t(`__VUE_INSTANCE_SETTERS__`, (e) => (Ma = e))), (Fa = t(`__VUE_SSR_SETTERS__`, (e) => (za = e))))
}
var Ia = (e) => {
    let t = Ma
    return (
      Pa(e),
      e.scope.on(),
      () => {
        ;(e.scope.off(), Pa(t))
      }
    )
  },
  La = () => {
    ;(Ma && Ma.scope.off(), Pa(null))
  }
function Ra(e) {
  return e.vnode.shapeFlag & 4
}
var za = !1
function Ba(e, t = !1, n = !1) {
  t && Fa(t)
  let { props: r, children: i } = e.vnode,
    a = Ra(e)
  ;(ji(e, r, a, t), Wi(e, i, n || t))
  let o = a ? Va(e, t) : void 0
  return (t && Fa(!1), o)
}
function Va(e, t) {
  let n = e.type
  ;((e.accessCache = Object.create(null)), (e.proxy = new Proxy(e.ctx, Yr)))
  let { setup: r } = n
  if (r) {
    Be()
    let n = (e.setupContext = r.length > 1 ? qa(e) : null),
      i = Ia(e),
      a = un(r, e, 0, [e.props, n]),
      o = y(a)
    if ((Ve(), i(), (o || e.sp) && !Er(e) && xr(e), o)) {
      if ((a.then(La, La), t))
        return a
          .then((n) => {
            Ha(e, n, t)
          })
          .catch((t) => {
            fn(t, e, 0)
          })
      e.asyncDep = a
    } else Ha(e, a, t)
  } else Ga(e, t)
}
function Ha(e, t, n) {
  ;(h(t) ? (e.type.__ssrInlineRender ? (e.ssrRender = t) : (e.render = t)) : v(t) && (e.setupState = Yt(t)), Ga(e, n))
}
var Ua, Wa
function Ga(e, t, n) {
  let i = e.type
  if (!e.render) {
    if (!t && Ua && !i.render) {
      let t = i.template || ni(e).template
      if (t) {
        let { isCustomElement: n, compilerOptions: r } = e.appContext.config,
          { delimiters: a, compilerOptions: o } = i
        i.render = Ua(t, s(s({ isCustomElement: n, delimiters: a }, r), o))
      }
    }
    ;((e.render = i.render || r), Wa && Wa(e))
  }
  {
    let t = Ia(e)
    Be()
    try {
      Qr(e)
    } finally {
      ;(Ve(), t())
    }
  }
}
var Ka = {
  get(e, t) {
    return (Ze(e, `get`, ``), e[t])
  },
}
function qa(e) {
  return {
    attrs: new Proxy(e.attrs, Ka),
    slots: e.slots,
    emit: e.emit,
    expose: (t) => {
      e.exposed = t || {}
    },
  }
}
function Ja(e) {
  return e.exposed
    ? (e.exposeProxy ||= new Proxy(Yt(Ht(e.exposed)), {
        get(t, n) {
          if (n in t) return t[n]
          if (n in qr) return qr[n](e)
        },
        has(e, t) {
          return t in e || t in qr
        },
      }))
    : e.proxy
}
function Ya(e) {
  return h(e) && `__vccOpts` in e
}
var q = (e, t) => nn(e, t, za)
function Xa(e, t, n) {
  try {
    fa(-1)
    let r = arguments.length
    return r === 2
      ? v(t) && !d(t)
        ? ha(t)
          ? G(e, null, [t])
          : G(e, t)
        : G(e, null, t)
      : (r > 3 ? (n = Array.prototype.slice.call(arguments, 2)) : r === 3 && ha(n) && (n = [n]), G(e, t, n))
  } finally {
    fa(1)
  }
}
var Za = `3.5.33`,
  Qa = void 0,
  $a = typeof window < `u` && window.trustedTypes
if ($a)
  try {
    Qa = $a.createPolicy(`vue`, { createHTML: (e) => e })
  } catch {}
var eo = Qa ? (e) => Qa.createHTML(e) : (e) => e,
  to = `http://www.w3.org/2000/svg`,
  no = `http://www.w3.org/1998/Math/MathML`,
  ro = typeof document < `u` ? document : null,
  io = ro && ro.createElement(`template`),
  ao = {
    insert: (e, t, n) => {
      t.insertBefore(e, n || null)
    },
    remove: (e) => {
      let t = e.parentNode
      t && t.removeChild(e)
    },
    createElement: (e, t, n, r) => {
      let i =
        t === `svg`
          ? ro.createElementNS(to, e)
          : t === `mathml`
            ? ro.createElementNS(no, e)
            : n
              ? ro.createElement(e, { is: n })
              : ro.createElement(e)
      return (e === `select` && r && r.multiple != null && i.setAttribute(`multiple`, r.multiple), i)
    },
    createText: (e) => ro.createTextNode(e),
    createComment: (e) => ro.createComment(e),
    setText: (e, t) => {
      e.nodeValue = t
    },
    setElementText: (e, t) => {
      e.textContent = t
    },
    parentNode: (e) => e.parentNode,
    nextSibling: (e) => e.nextSibling,
    querySelector: (e) => ro.querySelector(e),
    setScopeId(e, t) {
      e.setAttribute(t, ``)
    },
    insertStaticContent(e, t, n, r, i, a) {
      let o = n ? n.previousSibling : t.lastChild
      if (i && (i === a || i.nextSibling)) for (; t.insertBefore(i.cloneNode(!0), n), !(i === a || !(i = i.nextSibling)); );
      else {
        io.innerHTML = eo(r === `svg` ? `<svg>${e}</svg>` : r === `mathml` ? `<math>${e}</math>` : e)
        let i = io.content
        if (r === `svg` || r === `mathml`) {
          let e = i.firstChild
          for (; e.firstChild; ) i.appendChild(e.firstChild)
          i.removeChild(e)
        }
        t.insertBefore(i, n)
      }
      return [o ? o.nextSibling : t.firstChild, n ? n.previousSibling : t.lastChild]
    },
  },
  oo = `transition`,
  so = `animation`,
  co = Symbol(`_vtc`),
  lo = {
    name: String,
    type: String,
    css: { type: Boolean, default: !0 },
    duration: [String, Number, Object],
    enterFromClass: String,
    enterActiveClass: String,
    enterToClass: String,
    appearFromClass: String,
    appearActiveClass: String,
    appearToClass: String,
    leaveFromClass: String,
    leaveActiveClass: String,
    leaveToClass: String,
  },
  uo = s({}, lr, lo),
  fo = ((e) => ((e.displayName = `Transition`), (e.props = uo), e))((e, { slots: t }) => Xa(pr, ho(e), t)),
  po = (e, t = []) => {
    d(e) ? e.forEach((e) => e(...t)) : e && e(...t)
  },
  mo = (e) => (e ? (d(e) ? e.some((e) => e.length > 1) : e.length > 1) : !1)
function ho(e) {
  let t = {}
  for (let n in e) n in lo || (t[n] = e[n])
  if (e.css === !1) return t
  let {
      name: n = `v`,
      type: r,
      duration: i,
      enterFromClass: a = `${n}-enter-from`,
      enterActiveClass: o = `${n}-enter-active`,
      enterToClass: c = `${n}-enter-to`,
      appearFromClass: l = a,
      appearActiveClass: u = o,
      appearToClass: d = c,
      leaveFromClass: f = `${n}-leave-from`,
      leaveActiveClass: p = `${n}-leave-active`,
      leaveToClass: m = `${n}-leave-to`,
    } = e,
    h = go(i),
    g = h && h[0],
    _ = h && h[1],
    {
      onBeforeEnter: v,
      onEnter: y,
      onEnterCancelled: b,
      onLeave: x,
      onLeaveCancelled: S,
      onBeforeAppear: C = v,
      onAppear: w = y,
      onAppearCancelled: T = b,
    } = t,
    E = (e, t, n, r) => {
      ;((e._enterCancelled = r), yo(e, t ? d : c), yo(e, t ? u : o), n && n())
    },
    D = (e, t) => {
      ;((e._isLeaving = !1), yo(e, f), yo(e, m), yo(e, p), t && t())
    },
    O = (e) => (t, n) => {
      let i = e ? w : y,
        o = () => E(t, e, n)
      ;(po(i, [t, o]),
        bo(() => {
          ;(yo(t, e ? l : a), vo(t, e ? d : c), mo(i) || So(t, r, g, o))
        }))
    }
  return s(t, {
    onBeforeEnter(e) {
      ;(po(v, [e]), vo(e, a), vo(e, o))
    },
    onBeforeAppear(e) {
      ;(po(C, [e]), vo(e, l), vo(e, u))
    },
    onEnter: O(!1),
    onAppear: O(!0),
    onLeave(e, t) {
      e._isLeaving = !0
      let n = () => D(e, t)
      ;(vo(e, f),
        e._enterCancelled ? (vo(e, p), Eo(e)) : (Eo(e), vo(e, p)),
        bo(() => {
          e._isLeaving && (yo(e, f), vo(e, m), mo(x) || So(e, r, _, n))
        }),
        po(x, [e, n]))
    },
    onEnterCancelled(e) {
      ;(E(e, !1, void 0, !0), po(b, [e]))
    },
    onAppearCancelled(e) {
      ;(E(e, !0, void 0, !0), po(T, [e]))
    },
    onLeaveCancelled(e) {
      ;(D(e), po(S, [e]))
    },
  })
}
function go(e) {
  if (e == null) return null
  if (v(e)) return [_o(e.enter), _o(e.leave)]
  {
    let t = _o(e)
    return [t, t]
  }
}
function _o(e) {
  return re(e)
}
function vo(e, t) {
  ;(t.split(/\s+/).forEach((t) => t && e.classList.add(t)), (e[co] || (e[co] = new Set())).add(t))
}
function yo(e, t) {
  t.split(/\s+/).forEach((t) => t && e.classList.remove(t))
  let n = e[co]
  n && (n.delete(t), n.size || (e[co] = void 0))
}
function bo(e) {
  requestAnimationFrame(() => {
    requestAnimationFrame(e)
  })
}
var xo = 0
function So(e, t, n, r) {
  let i = (e._endId = ++xo),
    a = () => {
      i === e._endId && r()
    }
  if (n != null) return setTimeout(a, n)
  let { type: o, timeout: s, propCount: c } = Co(e, t)
  if (!o) return r()
  let l = o + `end`,
    u = 0,
    d = () => {
      ;(e.removeEventListener(l, f), a())
    },
    f = (t) => {
      t.target === e && ++u >= c && d()
    }
  ;(setTimeout(() => {
    u < c && d()
  }, s + 1),
    e.addEventListener(l, f))
}
function Co(e, t) {
  let n = window.getComputedStyle(e),
    r = (e) => (n[e] || ``).split(`, `),
    i = r(`${oo}Delay`),
    a = r(`${oo}Duration`),
    o = wo(i, a),
    s = r(`${so}Delay`),
    c = r(`${so}Duration`),
    l = wo(s, c),
    u = null,
    d = 0,
    f = 0
  t === oo
    ? o > 0 && ((u = oo), (d = o), (f = a.length))
    : t === so
      ? l > 0 && ((u = so), (d = l), (f = c.length))
      : ((d = Math.max(o, l)), (u = d > 0 ? (o > l ? oo : so) : null), (f = u ? (u === oo ? a.length : c.length) : 0))
  let p = u === oo && /\b(?:transform|all)(?:,|$)/.test(r(`${oo}Property`).toString())
  return { type: u, timeout: d, propCount: f, hasTransform: p }
}
function wo(e, t) {
  for (; e.length < t.length; ) e = e.concat(e)
  return Math.max(...t.map((t, n) => To(t) + To(e[n])))
}
function To(e) {
  return e === `auto` ? 0 : Number(e.slice(0, -1).replace(`,`, `.`)) * 1e3
}
function Eo(e) {
  return (e ? e.ownerDocument : document).body.offsetHeight
}
function Do(e, t, n) {
  let r = e[co]
  ;(r && (t = (t ? [t, ...r] : [...r]).join(` `)),
    t == null ? e.removeAttribute(`class`) : n ? e.setAttribute(`class`, t) : (e.className = t))
}
var Oo = Symbol(`_vod`),
  ko = Symbol(`_vsh`),
  Ao = Symbol(``),
  jo = /(?:^|;)\s*display\s*:/
function Mo(e, t, n) {
  let r = e.style,
    i = g(n),
    a = !1
  if (n && !i) {
    if (t)
      if (g(t))
        for (let e of t.split(`;`)) {
          let t = e.slice(0, e.indexOf(`:`)).trim()
          n[t] ?? Po(r, t, ``)
        }
      else for (let e in t) n[e] ?? Po(r, e, ``)
    for (let i in n) {
      i === `display` && (a = !0)
      let o = n[i]
      o == null ? Po(r, i, ``) : Ro(e, i, !g(t) && t ? t[i] : void 0, o) || Po(r, i, o)
    }
  } else if (i) {
    if (t !== n) {
      let e = r[Ao]
      ;(e && (n += `;` + e), (r.cssText = n), (a = jo.test(n)))
    }
  } else t && e.removeAttribute(`style`)
  Oo in e && ((e[Oo] = a ? r.display : ``), e[ko] && (r.display = `none`))
}
var No = /\s*!important$/
function Po(e, t, n) {
  if (d(n)) n.forEach((n) => Po(e, t, n))
  else if (((n ??= ``), t.startsWith(`--`))) e.setProperty(t, n)
  else {
    let r = Lo(e, t)
    No.test(n) ? e.setProperty(A(r), n.replace(No, ``), `important`) : (e[r] = n)
  }
}
var Fo = [`Webkit`, `Moz`, `ms`],
  Io = {}
function Lo(e, t) {
  let n = Io[t]
  if (n) return n
  let r = O(t)
  if (r !== `filter` && r in e) return (Io[t] = r)
  r = j(r)
  for (let n = 0; n < Fo.length; n++) {
    let i = Fo[n] + r
    if (i in e) return (Io[t] = i)
  }
  return t
}
function Ro(e, t, n, r) {
  return e.tagName === `TEXTAREA` && (t === `width` || t === `height`) && g(r) && n === r
}
var zo = `http://www.w3.org/1999/xlink`
function Bo(e, t, n, r, i, a = fe(t)) {
  r && t.startsWith(`xlink:`)
    ? n == null
      ? e.removeAttributeNS(zo, t.slice(6, t.length))
      : e.setAttributeNS(zo, t, n)
    : n == null || (a && !pe(n))
      ? e.removeAttribute(t)
      : e.setAttribute(t, a ? `` : _(n) ? String(n) : n)
}
function Vo(e, t, n, r, i) {
  if (t === `innerHTML` || t === `textContent`) {
    n != null && (e[t] = t === `innerHTML` ? eo(n) : n)
    return
  }
  let a = e.tagName
  if (t === `value` && a !== `PROGRESS` && !a.includes(`-`)) {
    let r = a === `OPTION` ? e.getAttribute(`value`) || `` : e.value,
      i = n == null ? (e.type === `checkbox` ? `on` : ``) : String(n)
    ;((r !== i || !(`_value` in e)) && (e.value = i), n ?? e.removeAttribute(t), (e._value = n))
    return
  }
  let o = !1
  if (n === `` || n == null) {
    let r = typeof e[t]
    r === `boolean` ? (n = pe(n)) : n == null && r === `string` ? ((n = ``), (o = !0)) : r === `number` && ((n = 0), (o = !0))
  }
  try {
    e[t] = n
  } catch {}
  o && e.removeAttribute(i || t)
}
function Ho(e, t, n, r) {
  e.addEventListener(t, n, r)
}
function Uo(e, t, n, r) {
  e.removeEventListener(t, n, r)
}
var Wo = Symbol(`_vei`)
function Go(e, t, n, r, i = null) {
  let a = e[Wo] || (e[Wo] = {}),
    o = a[t]
  if (r && o) o.value = r
  else {
    let [n, s] = qo(t)
    r ? Ho(e, n, (a[t] = Zo(r, i)), s) : o && (Uo(e, n, o, s), (a[t] = void 0))
  }
}
var Ko = /(?:Once|Passive|Capture)$/
function qo(e) {
  let t
  if (Ko.test(e)) {
    t = {}
    let n
    for (; (n = e.match(Ko)); ) ((e = e.slice(0, e.length - n[0].length)), (t[n[0].toLowerCase()] = !0))
  }
  return [e[2] === `:` ? e.slice(3) : A(e.slice(2)), t]
}
var Jo = 0,
  Yo = Promise.resolve(),
  Xo = () => (Jo ||= (Yo.then(() => (Jo = 0)), Date.now()))
function Zo(e, t) {
  let n = (e) => {
    if (!e._vts) e._vts = Date.now()
    else if (e._vts <= n.attached) return
    dn(Qo(e, n.value), t, 5, [e])
  }
  return ((n.value = e), (n.attached = Xo()), n)
}
function Qo(e, t) {
  if (d(t)) {
    let n = e.stopImmediatePropagation
    return (
      (e.stopImmediatePropagation = () => {
        ;(n.call(e), (e._stopped = !0))
      }),
      t.map((e) => (t) => !t._stopped && e && e(t))
    )
  } else return t
}
var $o = (e) => e.charCodeAt(0) === 111 && e.charCodeAt(1) === 110 && e.charCodeAt(2) > 96 && e.charCodeAt(2) < 123,
  es = (e, t, n, r, i, s) => {
    let c = i === `svg`
    t === `class`
      ? Do(e, r, c)
      : t === `style`
        ? Mo(e, n, r)
        : a(t)
          ? o(t) || Go(e, t, n, r, s)
          : (t[0] === `.` ? ((t = t.slice(1)), !0) : t[0] === `^` ? ((t = t.slice(1)), !1) : ts(e, t, r, c))
            ? (Vo(e, t, r),
              !e.tagName.includes(`-`) && (t === `value` || t === `checked` || t === `selected`) && Bo(e, t, r, c, s, t !== `value`))
            : e._isVueCE && (ns(e, t) || (e._def.__asyncLoader && (/[A-Z]/.test(t) || !g(r))))
              ? Vo(e, O(t), r, s, t)
              : (t === `true-value` ? (e._trueValue = r) : t === `false-value` && (e._falseValue = r), Bo(e, t, r, c))
  }
function ts(e, t, n, r) {
  if (r) return !!(t === `innerHTML` || t === `textContent` || (t in e && $o(t) && h(n)))
  if (
    t === `spellcheck` ||
    t === `draggable` ||
    t === `translate` ||
    t === `autocorrect` ||
    (t === `sandbox` && e.tagName === `IFRAME`) ||
    t === `form` ||
    (t === `list` && e.tagName === `INPUT`) ||
    (t === `type` && e.tagName === `TEXTAREA`)
  )
    return !1
  if (t === `width` || t === `height`) {
    let t = e.tagName
    if (t === `IMG` || t === `VIDEO` || t === `CANVAS` || t === `SOURCE`) return !1
  }
  return $o(t) && g(n) ? !1 : t in e
}
function ns(e, t) {
  let n = e._def.props
  if (!n) return !1
  let r = O(t)
  return Array.isArray(n) ? n.some((e) => O(e) === r) : Object.keys(n).some((e) => O(e) === r)
}
var rs = (e) => {
  let t = e.props[`onUpdate:modelValue`] || !1
  return d(t) ? (e) => te(t, e) : t
}
function is(e) {
  e.target.composing = !0
}
function as(e) {
  let t = e.target
  t.composing && ((t.composing = !1), t.dispatchEvent(new Event(`input`)))
}
var os = Symbol(`_assign`)
function ss(e, t, n) {
  return (t && (e = e.trim()), n && (e = ne(e)), e)
}
var cs = {
    created(e, { modifiers: { lazy: t, trim: n, number: r } }, i) {
      e[os] = rs(i)
      let a = r || (i.props && i.props.type === `number`)
      ;(Ho(e, t ? `change` : `input`, (t) => {
        t.target.composing || e[os](ss(e.value, n, a))
      }),
        (n || a) &&
          Ho(e, `change`, () => {
            e.value = ss(e.value, n, a)
          }),
        t || (Ho(e, `compositionstart`, is), Ho(e, `compositionend`, as), Ho(e, `change`, as)))
    },
    mounted(e, { value: t }) {
      e.value = t ?? ``
    },
    beforeUpdate(e, { value: t, oldValue: n, modifiers: { lazy: r, trim: i, number: a } }, o) {
      if (((e[os] = rs(o)), e.composing)) return
      let s = (a || e.type === `number`) && !/^0\d/.test(e.value) ? ne(e.value) : e.value,
        c = t ?? ``
      if (s === c) return
      let l = e.getRootNode()
      ;((l instanceof Document || l instanceof ShadowRoot) &&
        l.activeElement === e &&
        e.type !== `range` &&
        ((r && t === n) || (i && e.value.trim() === c))) ||
        (e.value = c)
    },
  },
  ls = [`ctrl`, `shift`, `alt`, `meta`],
  us = {
    stop: (e) => e.stopPropagation(),
    prevent: (e) => e.preventDefault(),
    self: (e) => e.target !== e.currentTarget,
    ctrl: (e) => !e.ctrlKey,
    shift: (e) => !e.shiftKey,
    alt: (e) => !e.altKey,
    meta: (e) => !e.metaKey,
    left: (e) => `button` in e && e.button !== 0,
    middle: (e) => `button` in e && e.button !== 1,
    right: (e) => `button` in e && e.button !== 2,
    exact: (e, t) => ls.some((n) => e[`${n}Key`] && !t.includes(n)),
  },
  ds = (e, t) => {
    if (!e) return e
    let n = (e._withMods ||= {}),
      r = t.join(`.`)
    return (
      n[r] ||
      (n[r] = (n, ...r) => {
        for (let e = 0; e < t.length; e++) {
          let r = us[t[e]]
          if (r && r(n, t)) return
        }
        return e(n, ...r)
      })
    )
  },
  fs = {
    esc: `escape`,
    space: ` `,
    up: `arrow-up`,
    left: `arrow-left`,
    right: `arrow-right`,
    down: `arrow-down`,
    delete: `backspace`,
  },
  ps = (e, t) => {
    let n = (e._withKeys ||= {}),
      r = t.join(`.`)
    return (
      n[r] ||
      (n[r] = (n) => {
        if (!(`key` in n)) return
        let r = A(n.key)
        if (t.some((e) => e === r || fs[e] === r)) return e(n)
      })
    )
  },
  ms = s({ patchProp: es }, ao),
  hs
function gs() {
  return (hs ||= qi(ms))
}
var _s = (...e) => {
  let t = gs().createApp(...e),
    { mount: n } = t
  return (
    (t.mount = (e) => {
      let r = ys(e)
      if (!r) return
      let i = t._component
      ;(!h(i) && !i.render && !i.template && (i.template = r.innerHTML), r.nodeType === 1 && (r.textContent = ``))
      let a = n(r, !1, vs(r))
      return (r instanceof Element && (r.removeAttribute(`v-cloak`), r.setAttribute(`data-v-app`, ``)), a)
    }),
    t
  )
}
function vs(e) {
  if (e instanceof SVGElement) return `svg`
  if (typeof MathMLElement == `function` && e instanceof MathMLElement) return `mathml`
}
function ys(e) {
  return g(e) ? document.querySelector(e) : e
}
var bs = typeof window < `u`,
  xs,
  Ss = (e) => (xs = e),
  Cs = Symbol()
function ws(e) {
  return e && typeof e == `object` && Object.prototype.toString.call(e) === `[object Object]` && typeof e.toJSON != `function`
}
var Ts
;(function (e) {
  ;((e.direct = `direct`), (e.patchObject = `patch object`), (e.patchFunction = `patch function`))
})((Ts ||= {}))
var Es =
  typeof window == `object` && window.window === window
    ? window
    : typeof self == `object` && self.self === self
      ? self
      : typeof global == `object` && global.global === global
        ? global
        : typeof globalThis == `object`
          ? globalThis
          : { HTMLElement: null }
function Ds(e, { autoBom: t = !1 } = {}) {
  return t && /^\s*(?:text\/\S*|application\/xml|\S*\/\S*\+xml)\s*;.*charset\s*=\s*utf-8/i.test(e.type)
    ? new Blob([`﻿`, e], { type: e.type })
    : e
}
function Os(e, t, n) {
  let r = new XMLHttpRequest()
  ;(r.open(`GET`, e),
    (r.responseType = `blob`),
    (r.onload = function () {
      Ns(r.response, t, n)
    }),
    (r.onerror = function () {
      console.error(`could not download file`)
    }),
    r.send())
}
function ks(e) {
  let t = new XMLHttpRequest()
  t.open(`HEAD`, e, !1)
  try {
    t.send()
  } catch {}
  return t.status >= 200 && t.status <= 299
}
function As(e) {
  try {
    e.dispatchEvent(new MouseEvent(`click`))
  } catch {
    let t = new MouseEvent(`click`, {
      bubbles: !0,
      cancelable: !0,
      view: window,
      detail: 0,
      screenX: 80,
      screenY: 20,
      clientX: 80,
      clientY: 20,
      ctrlKey: !1,
      altKey: !1,
      shiftKey: !1,
      metaKey: !1,
      button: 0,
      relatedTarget: null,
    })
    e.dispatchEvent(t)
  }
}
var js = typeof navigator == `object` ? navigator : { userAgent: `` },
  Ms = /Macintosh/.test(js.userAgent) && /AppleWebKit/.test(js.userAgent) && !/Safari/.test(js.userAgent),
  Ns = bs
    ? typeof HTMLAnchorElement < `u` && `download` in HTMLAnchorElement.prototype && !Ms
      ? Ps
      : `msSaveOrOpenBlob` in js
        ? Fs
        : Is
    : () => {}
function Ps(e, t = `download`, n) {
  let r = document.createElement(`a`)
  ;((r.download = t),
    (r.rel = `noopener`),
    typeof e == `string`
      ? ((r.href = e), r.origin === location.origin ? As(r) : ks(r.href) ? Os(e, t, n) : ((r.target = `_blank`), As(r)))
      : ((r.href = URL.createObjectURL(e)),
        setTimeout(function () {
          URL.revokeObjectURL(r.href)
        }, 4e4),
        setTimeout(function () {
          As(r)
        }, 0)))
}
function Fs(e, t = `download`, n) {
  if (typeof e == `string`)
    if (ks(e)) Os(e, t, n)
    else {
      let t = document.createElement(`a`)
      ;((t.href = e),
        (t.target = `_blank`),
        setTimeout(function () {
          As(t)
        }))
    }
  else navigator.msSaveOrOpenBlob(Ds(e, n), t)
}
function Is(e, t, n, r) {
  if (((r ||= open(``, `_blank`)), r && (r.document.title = r.document.body.innerText = `downloading...`), typeof e == `string`))
    return Os(e, t, n)
  let i = e.type === `application/octet-stream`,
    a = /constructor/i.test(String(Es.HTMLElement)) || `safari` in Es,
    o = /CriOS\/[\d]+/.test(navigator.userAgent)
  if ((o || (i && a) || Ms) && typeof FileReader < `u`) {
    let t = new FileReader()
    ;((t.onloadend = function () {
      let e = t.result
      if (typeof e != `string`) throw ((r = null), Error(`Wrong reader.result type`))
      ;((e = o ? e : e.replace(/^data:[^;]*;/, `data:attachment/file;`)), r ? (r.location.href = e) : location.assign(e), (r = null))
    }),
      t.readAsDataURL(e))
  } else {
    let t = URL.createObjectURL(e)
    ;(r ? r.location.assign(t) : (location.href = t),
      (r = null),
      setTimeout(function () {
        URL.revokeObjectURL(t)
      }, 4e4))
  }
}
var { assign: Ls } = Object
function Rs() {
  let e = xe(!0),
    t = e.run(() => z({})),
    n = [],
    r = [],
    i = Ht({
      install(e) {
        ;(Ss(i), (i._a = e), e.provide(Cs, i), (e.config.globalProperties.$pinia = i), r.forEach((e) => n.push(e)), (r = []))
      },
      use(e) {
        return (this._a ? n.push(e) : r.push(e), this)
      },
      _p: n,
      _a: null,
      _e: e,
      _s: new Map(),
      state: t,
    })
  return i
}
var zs = () => {}
function Bs(e, t, n, r = zs) {
  e.add(t)
  let i = () => {
    e.delete(t) && r()
  }
  return (!n && Se() && Ce(i), i)
}
function Vs(e, ...t) {
  e.forEach((e) => {
    e(...t)
  })
}
var Hs = (e) => e(),
  Us = Symbol(),
  Ws = Symbol()
function Gs(e, t) {
  e instanceof Map && t instanceof Map ? t.forEach((t, n) => e.set(n, t)) : e instanceof Set && t instanceof Set && t.forEach(e.add, e)
  for (let n in t) {
    if (!t.hasOwnProperty(n)) continue
    let r = t[n],
      i = e[n]
    ws(i) && ws(r) && e.hasOwnProperty(n) && !R(r) && !Rt(r) ? (e[n] = Gs(i, r)) : (e[n] = r)
  }
  return e
}
var Ks = Symbol()
function qs(e) {
  return !ws(e) || !Object.prototype.hasOwnProperty.call(e, Ks)
}
var { assign: Js } = Object
function Ys(e) {
  return !!(R(e) && e.effect)
}
function Xs(e, t, n, r) {
  let { state: i, actions: a, getters: o } = t,
    s = n.state.value[e],
    c
  function l() {
    return (
      s || (n.state.value[e] = i ? i() : {}),
      Js(
        Xt(n.state.value[e]),
        a,
        Object.keys(o || {}).reduce(
          (t, r) => (
            (t[r] = Ht(
              q(() => {
                Ss(n)
                let t = n._s.get(e)
                return o[r].call(t, t)
              }),
            )),
            t
          ),
          {},
        ),
      )
    )
  }
  return ((c = Zs(e, l, t, n, r, !0)), c)
}
function Zs(e, t, n = {}, r, i, a) {
  let o,
    s = Js({ actions: {} }, n),
    c = { deep: !0 },
    l,
    u,
    d = new Set(),
    f = new Set(),
    p = r.state.value[e]
  !a && !p && (r.state.value[e] = {})
  let m
  function h(t) {
    let n
    ;((l = u = !1),
      typeof t == `function`
        ? (t(r.state.value[e]), (n = { type: Ts.patchFunction, storeId: e, events: void 0 }))
        : (Gs(r.state.value[e], t), (n = { type: Ts.patchObject, payload: t, storeId: e, events: void 0 })))
    let i = (m = Symbol())
    ;(xn().then(() => {
      m === i && (l = !0)
    }),
      (u = !0),
      Vs(d, n, r.state.value[e]))
  }
  let g = a
    ? function () {
        let { state: e } = n,
          t = e ? e() : {}
        this.$patch((e) => {
          Js(e, t)
        })
      }
    : zs
  function _() {
    ;(o.stop(), d.clear(), f.clear(), r._s.delete(e))
  }
  let v = (t, n = ``) => {
      if (Us in t) return ((t[Ws] = n), t)
      let i = function () {
        Ss(r)
        let n = Array.from(arguments),
          a = new Set(),
          o = new Set()
        function s(e) {
          a.add(e)
        }
        function c(e) {
          o.add(e)
        }
        Vs(f, { args: n, name: i[Ws], store: y, after: s, onError: c })
        let l
        try {
          l = t.apply(this && this.$id === e ? this : y, n)
        } catch (e) {
          throw (Vs(o, e), e)
        }
        return l instanceof Promise ? l.then((e) => (Vs(a, e), e)).catch((e) => (Vs(o, e), Promise.reject(e))) : (Vs(a, l), l)
      }
      return ((i[Us] = !0), (i[Ws] = n), i)
    },
    y = Pt({
      _p: r,
      $id: e,
      $onAction: Bs.bind(null, f),
      $patch: h,
      $reset: g,
      $subscribe(t, n = {}) {
        let i = Bs(d, t, n.detached, () => a()),
          a = o.run(() =>
            Vn(
              () => r.state.value[e],
              (r) => {
                ;(n.flush === `sync` ? u : l) && t({ storeId: e, type: Ts.direct, events: void 0 }, r)
              },
              Js({}, c, n),
            ),
          )
        return i
      },
      $dispose: _,
    })
  r._s.set(e, y)
  let b = ((r._a && r._a.runWithContext) || Hs)(() => r._e.run(() => (o = xe()).run(() => t({ action: v }))))
  for (let t in b) {
    let n = b[t]
    ;(R(n) && !Ys(n)) || Rt(n)
      ? a || (p && qs(n) && (R(n) ? (n.value = p[t]) : Gs(n, p[t])), (r.state.value[e][t] = n))
      : typeof n == `function` && ((b[t] = v(n, t)), (s.actions[t] = n))
  }
  return (
    Js(y, b),
    Js(L(y), b),
    Object.defineProperty(y, '$state', {
      get: () => r.state.value[e],
      set: (e) => {
        h((t) => {
          Js(t, e)
        })
      },
    }),
    r._p.forEach((e) => {
      Js(
        y,
        o.run(() => e({ store: y, app: r._a, pinia: r, options: s })),
      )
    }),
    p && a && n.hydrate && n.hydrate(y.$state, p),
    (l = !0),
    (u = !0),
    y
  )
}
function Qs(e, t, n) {
  let r,
    i = typeof t == `function`
  r = i ? n : t
  function a(n, a) {
    let o = Rn()
    return ((n ||= o ? Ln(Cs, null) : null), n && Ss(n), (n = xs), n._s.has(e) || (i ? Zs(e, t, r, n) : Xs(e, r, n)), n._s.get(e))
  }
  return ((a.$id = e), a)
}
function $s(e) {
  let t = L(e),
    n = {}
  for (let r in t) {
    let i = t[r]
    i.effect
      ? (n[r] = q({
          get: () => e[r],
          set(t) {
            e[r] = t
          },
        }))
      : (R(i) || Rt(i)) && (n[r] = $t(e, r))
  }
  return n
}
var ec = typeof document < `u`
function tc(e) {
  return typeof e == `object` || `displayName` in e || `props` in e || `__vccOpts` in e
}
function nc(e) {
  return e.__esModule || e[Symbol.toStringTag] === `Module` || (e.default && tc(e.default))
}
var J = Object.assign
function rc(e, t) {
  let n = {}
  for (let r in t) {
    let i = t[r]
    n[r] = ac(i) ? i.map(e) : e(i)
  }
  return n
}
var ic = () => {},
  ac = Array.isArray
function oc(e, t) {
  let n = {}
  for (let r in e) n[r] = r in t ? t[r] : e[r]
  return n
}
var sc = /#/g,
  cc = /&/g,
  lc = /\//g,
  uc = /=/g,
  dc = /\?/g,
  fc = /\+/g,
  pc = /%5B/g,
  mc = /%5D/g,
  hc = /%5E/g,
  gc = /%60/g,
  _c = /%7B/g,
  vc = /%7C/g,
  yc = /%7D/g,
  bc = /%20/g
function xc(e) {
  return e == null
    ? ``
    : encodeURI(`` + e)
        .replace(vc, `|`)
        .replace(pc, `[`)
        .replace(mc, `]`)
}
function Sc(e) {
  return xc(e).replace(_c, `{`).replace(yc, `}`).replace(hc, `^`)
}
function Cc(e) {
  return xc(e)
    .replace(fc, `%2B`)
    .replace(bc, `+`)
    .replace(sc, `%23`)
    .replace(cc, `%26`)
    .replace(gc, '`')
    .replace(_c, `{`)
    .replace(yc, `}`)
    .replace(hc, `^`)
}
function wc(e) {
  return Cc(e).replace(uc, `%3D`)
}
function Tc(e) {
  return xc(e).replace(sc, `%23`).replace(dc, `%3F`)
}
function Ec(e) {
  return Tc(e).replace(lc, `%2F`)
}
function Dc(e) {
  if (e == null) return null
  try {
    return decodeURIComponent(`` + e)
  } catch {}
  return `` + e
}
var Oc = /\/$/,
  kc = (e) => e.replace(Oc, ``)
function Ac(e, t, n = `/`) {
  let r,
    i = {},
    a = ``,
    o = ``,
    s = t.indexOf(`#`),
    c = t.indexOf(`?`)
  return (
    (c = s >= 0 && c > s ? -1 : c),
    c >= 0 && ((r = t.slice(0, c)), (a = t.slice(c, s > 0 ? s : t.length)), (i = e(a.slice(1)))),
    s >= 0 && ((r ||= t.slice(0, s)), (o = t.slice(s, t.length))),
    (r = Lc(r ?? t, n)),
    { fullPath: r + a + o, path: r, query: i, hash: Dc(o) }
  )
}
function jc(e, t) {
  let n = t.query ? e(t.query) : ``
  return t.path + (n && `?`) + n + (t.hash || ``)
}
function Mc(e, t, n) {
  let r = t.matched.length - 1,
    i = n.matched.length - 1
  return r > -1 && r === i && Nc(t.matched[r], n.matched[i]) && Pc(t.params, n.params) && e(t.query) === e(n.query) && t.hash === n.hash
}
function Nc(e, t) {
  return (e.aliasOf || e) === (t.aliasOf || t)
}
function Pc(e, t) {
  if (Object.keys(e).length !== Object.keys(t).length) return !1
  for (var n in e) if (!Fc(e[n], t[n])) return !1
  return !0
}
function Fc(e, t) {
  return ac(e) ? Ic(e, t) : ac(t) ? Ic(t, e) : e?.valueOf() === t?.valueOf()
}
function Ic(e, t) {
  return ac(t) ? e.length === t.length && e.every((e, n) => e === t[n]) : e.length === 1 && e[0] === t
}
function Lc(e, t) {
  if (e.startsWith(`/`)) return e
  if (!e) return t
  let n = t.split(`/`),
    r = e.split(`/`),
    i = r[r.length - 1]
  ;(i === `..` || i === `.`) && r.push(``)
  let a = n.length - 1,
    o,
    s
  for (o = 0; o < r.length; o++)
    if (((s = r[o]), s !== `.`))
      if (s === `..`) a > 1 && a--
      else break
  return n.slice(0, a).join(`/`) + `/` + r.slice(o).join(`/`)
}
var Rc = {
    path: `/`,
    name: void 0,
    params: {},
    query: {},
    hash: ``,
    fullPath: `/`,
    matched: [],
    meta: {},
    redirectedFrom: void 0,
  },
  zc = (function (e) {
    return ((e.pop = `pop`), (e.push = `push`), e)
  })({}),
  Bc = (function (e) {
    return ((e.back = `back`), (e.forward = `forward`), (e.unknown = ``), e)
  })({})
function Vc(e) {
  if (!e)
    if (ec) {
      let t = document.querySelector(`base`)
      ;((e = (t && t.getAttribute(`href`)) || `/`), (e = e.replace(/^\w+:\/\/[^\/]+/, ``)))
    } else e = `/`
  return (e[0] !== `/` && e[0] !== `#` && (e = `/` + e), kc(e))
}
var Hc = /^[^#]+#/
function Uc(e, t) {
  return e.replace(Hc, `#`) + t
}
function Wc(e, t) {
  let n = document.documentElement.getBoundingClientRect(),
    r = e.getBoundingClientRect()
  return {
    behavior: t.behavior,
    left: r.left - n.left - (t.left || 0),
    top: r.top - n.top - (t.top || 0),
  }
}
var Gc = () => ({ left: window.scrollX, top: window.scrollY })
function Kc(e) {
  let t
  if (`el` in e) {
    let n = e.el,
      r = typeof n == `string` && n.startsWith(`#`),
      i = typeof n == `string` ? (r ? document.getElementById(n.slice(1)) : document.querySelector(n)) : n
    if (!i) return
    t = Wc(i, e)
  } else t = e
  ;`scrollBehavior` in document.documentElement.style
    ? window.scrollTo(t)
    : window.scrollTo(t.left == null ? window.scrollX : t.left, t.top == null ? window.scrollY : t.top)
}
function qc(e, t) {
  return (history.state ? history.state.position - t : -1) + e
}
var Jc = new Map()
function Yc(e, t) {
  Jc.set(e, t)
}
function Xc(e) {
  let t = Jc.get(e)
  return (Jc.delete(e), t)
}
function Zc(e) {
  return typeof e == `string` || (e && typeof e == `object`)
}
function Qc(e) {
  return typeof e == `string` || typeof e == `symbol`
}
var Y = (function (e) {
    return (
      (e[(e.MATCHER_NOT_FOUND = 1)] = `MATCHER_NOT_FOUND`),
      (e[(e.NAVIGATION_GUARD_REDIRECT = 2)] = `NAVIGATION_GUARD_REDIRECT`),
      (e[(e.NAVIGATION_ABORTED = 4)] = `NAVIGATION_ABORTED`),
      (e[(e.NAVIGATION_CANCELLED = 8)] = `NAVIGATION_CANCELLED`),
      (e[(e.NAVIGATION_DUPLICATED = 16)] = `NAVIGATION_DUPLICATED`),
      e
    )
  })({}),
  $c = Symbol(``)
;(Y.MATCHER_NOT_FOUND, Y.NAVIGATION_GUARD_REDIRECT, Y.NAVIGATION_ABORTED, Y.NAVIGATION_CANCELLED, Y.NAVIGATION_DUPLICATED)
function el(e, t) {
  return J(Error(), { type: e, [$c]: !0 }, t)
}
function tl(e, t) {
  return e instanceof Error && $c in e && (t == null || !!(e.type & t))
}
function nl(e) {
  let t = {}
  if (e === `` || e === `?`) return t
  let n = (e[0] === `?` ? e.slice(1) : e).split(`&`)
  for (let e = 0; e < n.length; ++e) {
    let r = n[e].replace(fc, ` `),
      i = r.indexOf(`=`),
      a = Dc(i < 0 ? r : r.slice(0, i)),
      o = i < 0 ? null : Dc(r.slice(i + 1))
    if (a in t) {
      let e = t[a]
      ;(ac(e) || (e = t[a] = [e]), e.push(o))
    } else t[a] = o
  }
  return t
}
function rl(e) {
  let t = ``
  for (let n in e) {
    let r = e[n]
    if (((n = wc(n)), r == null)) {
      r !== void 0 && (t += (t.length ? `&` : ``) + n)
      continue
    }
    ;(ac(r) ? r.map((e) => e && Cc(e)) : [r && Cc(r)]).forEach((e) => {
      e !== void 0 && ((t += (t.length ? `&` : ``) + n), e != null && (t += `=` + e))
    })
  }
  return t
}
function il(e) {
  let t = {}
  for (let n in e) {
    let r = e[n]
    r !== void 0 && (t[n] = ac(r) ? r.map((e) => (e == null ? null : `` + e)) : r == null ? r : `` + r)
  }
  return t
}
var al = Symbol(``),
  ol = Symbol(``),
  sl = Symbol(``),
  cl = Symbol(``),
  ll = Symbol(``)
function ul() {
  let e = []
  function t(t) {
    return (
      e.push(t),
      () => {
        let n = e.indexOf(t)
        n > -1 && e.splice(n, 1)
      }
    )
  }
  function n() {
    e = []
  }
  return { add: t, list: () => e.slice(), reset: n }
}
function dl(e, t, n, r, i, a = (e) => e()) {
  let o = r && (r.enterCallbacks[i] = r.enterCallbacks[i] || [])
  return () =>
    new Promise((s, c) => {
      let l = (e) => {
          e === !1
            ? c(el(Y.NAVIGATION_ABORTED, { from: n, to: t }))
            : e instanceof Error
              ? c(e)
              : Zc(e)
                ? c(el(Y.NAVIGATION_GUARD_REDIRECT, { from: t, to: e }))
                : (o && r.enterCallbacks[i] === o && typeof e == `function` && o.push(e), s())
        },
        u = a(() => e.call(r && r.instances[i], t, n, l)),
        d = Promise.resolve(u)
      ;(e.length < 3 && (d = d.then(l)), d.catch((e) => c(e)))
    })
}
function fl(e, t, n, r, i = (e) => e()) {
  let a = []
  for (let o of e)
    for (let e in o.components) {
      let s = o.components[e]
      if (!(t !== `beforeRouteEnter` && !o.instances[e]))
        if (tc(s)) {
          let c = (s.__vccOpts || s)[t]
          c && a.push(dl(c, n, r, o, e, i))
        } else {
          let c = s()
          a.push(() =>
            c.then((a) => {
              if (!a) throw Error(`Couldn't resolve component "${e}" at "${o.path}"`)
              let s = nc(a) ? a.default : a
              ;((o.mods[e] = a), (o.components[e] = s))
              let c = (s.__vccOpts || s)[t]
              return c && dl(c, n, r, o, e, i)()
            }),
          )
        }
    }
  return a
}
function pl(e, t) {
  let n = [],
    r = [],
    i = [],
    a = Math.max(t.matched.length, e.matched.length)
  for (let o = 0; o < a; o++) {
    let a = t.matched[o]
    a && (e.matched.find((e) => Nc(e, a)) ? r.push(a) : n.push(a))
    let s = e.matched[o]
    s && (t.matched.find((e) => Nc(e, s)) || i.push(s))
  }
  return [n, r, i]
}
function ml(e = ``) {
  let t = [],
    n = [[``, {}]],
    r = 0
  e = Vc(e)
  function i(e, t = {}) {
    ;(r++, r !== n.length && n.splice(r), n.push([e, t]))
  }
  function a(e, n, { direction: r, delta: i }) {
    let a = { direction: r, delta: i, type: zc.pop }
    for (let r of t) r(e, n, a)
  }
  let o = {
    location: ``,
    state: {},
    base: e,
    createHref: Uc.bind(null, e),
    replace(e, t) {
      ;(n.splice(r--, 1), i(e, t))
    },
    push(e, t) {
      i(e, t)
    },
    listen(e) {
      return (
        t.push(e),
        () => {
          let n = t.indexOf(e)
          n > -1 && t.splice(n, 1)
        }
      )
    },
    destroy() {
      ;((t = []), (n = [[``, {}]]), (r = 0))
    },
    go(e, t = !0) {
      let i = this.location,
        o = e < 0 ? Bc.back : Bc.forward
      ;((r = Math.max(0, Math.min(r + e, n.length - 1))), t && a(this.location, i, { direction: o, delta: e }))
    },
  }
  return (
    Object.defineProperty(o, 'location', { enumerable: !0, get: () => n[r][0] }),
    Object.defineProperty(o, 'state', { enumerable: !0, get: () => n[r][1] }),
    o
  )
}
var hl = (function (e) {
    return ((e[(e.Static = 0)] = `Static`), (e[(e.Param = 1)] = `Param`), (e[(e.Group = 2)] = `Group`), e)
  })({}),
  X = (function (e) {
    return (
      (e[(e.Static = 0)] = `Static`),
      (e[(e.Param = 1)] = `Param`),
      (e[(e.ParamRegExp = 2)] = `ParamRegExp`),
      (e[(e.ParamRegExpEnd = 3)] = `ParamRegExpEnd`),
      (e[(e.EscapeNext = 4)] = `EscapeNext`),
      e
    )
  })(X || {}),
  gl = { type: hl.Static, value: `` },
  _l = /[a-zA-Z0-9_]/
function vl(e) {
  if (!e) return [[]]
  if (e === `/`) return [[gl]]
  if (!e.startsWith(`/`)) throw Error(`Invalid path "${e}"`)
  function t(e) {
    throw Error(`ERR (${n})/"${l}": ${e}`)
  }
  let n = X.Static,
    r = n,
    i = [],
    a
  function o() {
    ;(a && i.push(a), (a = []))
  }
  let s = 0,
    c,
    l = ``,
    u = ``
  function d() {
    l &&=
      (n === X.Static
        ? a.push({ type: hl.Static, value: l })
        : n === X.Param || n === X.ParamRegExp || n === X.ParamRegExpEnd
          ? (a.length > 1 && (c === `*` || c === `+`) && t(`A repeatable param (${l}) must be alone in its segment. eg: '/:ids+.`),
            a.push({
              type: hl.Param,
              value: l,
              regexp: u,
              repeatable: c === `*` || c === `+`,
              optional: c === `*` || c === `?`,
            }))
          : t(`Invalid state to consume buffer`),
      ``)
  }
  function f() {
    l += c
  }
  for (; s < e.length; ) {
    if (((c = e[s++]), c === `\\` && n !== X.ParamRegExp)) {
      ;((r = n), (n = X.EscapeNext))
      continue
    }
    switch (n) {
      case X.Static:
        c === `/` ? (l && d(), o()) : c === `:` ? (d(), (n = X.Param)) : f()
        break
      case X.EscapeNext:
        ;(f(), (n = r))
        break
      case X.Param:
        c === `(` ? (n = X.ParamRegExp) : _l.test(c) ? f() : (d(), (n = X.Static), c !== `*` && c !== `?` && c !== `+` && s--)
        break
      case X.ParamRegExp:
        c === `)` ? (u[u.length - 1] == `\\` ? (u = u.slice(0, -1) + c) : (n = X.ParamRegExpEnd)) : (u += c)
        break
      case X.ParamRegExpEnd:
        ;(d(), (n = X.Static), c !== `*` && c !== `?` && c !== `+` && s--, (u = ``))
        break
      default:
        t(`Unknown state`)
        break
    }
  }
  return (n === X.ParamRegExp && t(`Unfinished custom RegExp for param "${l}"`), d(), o(), i)
}
var yl = `[^/]+?`,
  bl = { sensitive: !1, strict: !1, start: !0, end: !0 },
  xl = (function (e) {
    return (
      (e[(e._multiplier = 10)] = `_multiplier`),
      (e[(e.Root = 90)] = `Root`),
      (e[(e.Segment = 40)] = `Segment`),
      (e[(e.SubSegment = 30)] = `SubSegment`),
      (e[(e.Static = 40)] = `Static`),
      (e[(e.Dynamic = 20)] = `Dynamic`),
      (e[(e.BonusCustomRegExp = 10)] = `BonusCustomRegExp`),
      (e[(e.BonusWildcard = -50)] = `BonusWildcard`),
      (e[(e.BonusRepeatable = -20)] = `BonusRepeatable`),
      (e[(e.BonusOptional = -8)] = `BonusOptional`),
      (e[(e.BonusStrict = 0.7000000000000001)] = `BonusStrict`),
      (e[(e.BonusCaseSensitive = 0.25)] = `BonusCaseSensitive`),
      e
    )
  })(xl || {}),
  Sl = /[.+*?^${}()[\]/\\]/g
function Cl(e, t) {
  let n = J({}, bl, t),
    r = [],
    i = n.start ? `^` : ``,
    a = []
  for (let t of e) {
    let e = t.length ? [] : [xl.Root]
    n.strict && !t.length && (i += `/`)
    for (let r = 0; r < t.length; r++) {
      let o = t[r],
        s = xl.Segment + (n.sensitive ? xl.BonusCaseSensitive : 0)
      if (o.type === hl.Static) (r || (i += `/`), (i += o.value.replace(Sl, `\\$&`)), (s += xl.Static))
      else if (o.type === hl.Param) {
        let { value: e, repeatable: n, optional: c, regexp: l } = o
        a.push({ name: e, repeatable: n, optional: c })
        let u = l || yl
        if (u !== yl) {
          s += xl.BonusCustomRegExp
          try {
            ;`${u}`
          } catch (t) {
            throw Error(`Invalid custom RegExp for param "${e}" (${u}): ` + t.message)
          }
        }
        let d = n ? `((?:${u})(?:/(?:${u}))*)` : `(${u})`
        ;(r || (d = c && t.length < 2 ? `(?:/${d})` : `/` + d),
          c && (d += `?`),
          (i += d),
          (s += xl.Dynamic),
          c && (s += xl.BonusOptional),
          n && (s += xl.BonusRepeatable),
          u === `.*` && (s += xl.BonusWildcard))
      }
      e.push(s)
    }
    r.push(e)
  }
  if (n.strict && n.end) {
    let e = r.length - 1
    r[e][r[e].length - 1] += xl.BonusStrict
  }
  ;(n.strict || (i += `/?`), n.end ? (i += `$`) : n.strict && !i.endsWith(`/`) && (i += `(?:/|$)`))
  let o = new RegExp(i, n.sensitive ? `` : `i`)
  function s(e) {
    let t = e.match(o),
      n = {}
    if (!t) return null
    for (let e = 1; e < t.length; e++) {
      let r = t[e] || ``,
        i = a[e - 1]
      n[i.name] = r && i.repeatable ? r.split(`/`) : r
    }
    return n
  }
  function c(t) {
    let n = ``,
      r = !1
    for (let i of e) {
      ;((!r || !n.endsWith(`/`)) && (n += `/`), (r = !1))
      for (let e of i)
        if (e.type === hl.Static) n += e.value
        else if (e.type === hl.Param) {
          let { value: a, repeatable: o, optional: s } = e,
            c = a in t ? t[a] : ``
          if (ac(c) && !o) throw Error(`Provided param "${a}" is an array but it is not repeatable (* or + modifiers)`)
          let l = ac(c) ? c.join(`/`) : c
          if (!l)
            if (s) i.length < 2 && (n.endsWith(`/`) ? (n = n.slice(0, -1)) : (r = !0))
            else throw Error(`Missing required param "${a}"`)
          n += l
        }
    }
    return n || `/`
  }
  return { re: o, score: r, keys: a, parse: s, stringify: c }
}
function wl(e, t) {
  let n = 0
  for (; n < e.length && n < t.length; ) {
    let r = t[n] - e[n]
    if (r) return r
    n++
  }
  return e.length < t.length
    ? e.length === 1 && e[0] === xl.Static + xl.Segment
      ? -1
      : 1
    : e.length > t.length
      ? t.length === 1 && t[0] === xl.Static + xl.Segment
        ? 1
        : -1
      : 0
}
function Tl(e, t) {
  let n = 0,
    r = e.score,
    i = t.score
  for (; n < r.length && n < i.length; ) {
    let e = wl(r[n], i[n])
    if (e) return e
    n++
  }
  if (Math.abs(i.length - r.length) === 1) {
    if (El(r)) return 1
    if (El(i)) return -1
  }
  return i.length - r.length
}
function El(e) {
  let t = e[e.length - 1]
  return e.length > 0 && t[t.length - 1] < 0
}
var Dl = { strict: !1, end: !0, sensitive: !1 }
function Ol(e, t, n) {
  let r = J(Cl(vl(e.path), n), { record: e, parent: t, children: [], alias: [] })
  return (t && !r.record.aliasOf == !t.record.aliasOf && t.children.push(r), r)
}
function kl(e, t) {
  let n = [],
    r = new Map()
  t = oc(Dl, t)
  function i(e) {
    return r.get(e)
  }
  function a(e, n, r) {
    let i = !r,
      s = jl(e)
    s.aliasOf = r && r.record
    let l = oc(t, e),
      u = [s]
    if (`alias` in e) {
      let t = typeof e.alias == `string` ? [e.alias] : e.alias
      for (let e of t)
        u.push(
          jl(
            J({}, s, {
              components: r ? r.record.components : s.components,
              path: e,
              aliasOf: r ? r.record : s,
            }),
          ),
        )
    }
    let d, f
    for (let t of u) {
      let { path: u } = t
      if (n && u[0] !== `/`) {
        let e = n.record.path,
          r = e[e.length - 1] === `/` ? `` : `/`
        t.path = n.record.path + (u && r + u)
      }
      if (
        ((d = Ol(t, n, l)),
        r ? r.alias.push(d) : ((f ||= d), f !== d && f.alias.push(d), i && e.name && !Nl(d) && o(e.name)),
        Ll(d) && c(d),
        s.children)
      ) {
        let e = s.children
        for (let t = 0; t < e.length; t++) a(e[t], d, r && r.children[t])
      }
      r ||= d
    }
    return f
      ? () => {
          o(f)
        }
      : ic
  }
  function o(e) {
    if (Qc(e)) {
      let t = r.get(e)
      t && (r.delete(e), n.splice(n.indexOf(t), 1), t.children.forEach(o), t.alias.forEach(o))
    } else {
      let t = n.indexOf(e)
      t > -1 && (n.splice(t, 1), e.record.name && r.delete(e.record.name), e.children.forEach(o), e.alias.forEach(o))
    }
  }
  function s() {
    return n
  }
  function c(e) {
    let t = Fl(e, n)
    ;(n.splice(t, 0, e), e.record.name && !Nl(e) && r.set(e.record.name, e))
  }
  function l(e, t) {
    let i,
      a = {},
      o,
      s
    if (`name` in e && e.name) {
      if (((i = r.get(e.name)), !i)) throw el(Y.MATCHER_NOT_FOUND, { location: e })
      ;((s = i.record.name),
        (a = J(
          Al(
            t.params,
            i.keys
              .filter((e) => !e.optional)
              .concat(i.parent ? i.parent.keys.filter((e) => e.optional) : [])
              .map((e) => e.name),
          ),
          e.params &&
            Al(
              e.params,
              i.keys.map((e) => e.name),
            ),
        )),
        (o = i.stringify(a)))
    } else if (e.path != null) ((o = e.path), (i = n.find((e) => e.re.test(o))), i && ((a = i.parse(o)), (s = i.record.name)))
    else {
      if (((i = t.name ? r.get(t.name) : n.find((e) => e.re.test(t.path))), !i))
        throw el(Y.MATCHER_NOT_FOUND, { location: e, currentLocation: t })
      ;((s = i.record.name), (a = J({}, t.params, e.params)), (o = i.stringify(a)))
    }
    let c = [],
      l = i
    for (; l; ) (c.unshift(l.record), (l = l.parent))
    return { name: s, path: o, params: a, matched: c, meta: Pl(c) }
  }
  e.forEach((e) => a(e))
  function u() {
    ;((n.length = 0), r.clear())
  }
  return {
    addRoute: a,
    resolve: l,
    removeRoute: o,
    clearRoutes: u,
    getRoutes: s,
    getRecordMatcher: i,
  }
}
function Al(e, t) {
  let n = {}
  for (let r of t) r in e && (n[r] = e[r])
  return n
}
function jl(e) {
  let t = {
    path: e.path,
    redirect: e.redirect,
    name: e.name,
    meta: e.meta || {},
    aliasOf: e.aliasOf,
    beforeEnter: e.beforeEnter,
    props: Ml(e),
    children: e.children || [],
    instances: {},
    leaveGuards: new Set(),
    updateGuards: new Set(),
    enterCallbacks: {},
    components: `components` in e ? e.components || null : e.component && { default: e.component },
  }
  return (Object.defineProperty(t, 'mods', { value: {} }), t)
}
function Ml(e) {
  let t = {},
    n = e.props || !1
  if (`component` in e) t.default = n
  else for (let r in e.components) t[r] = typeof n == `object` ? n[r] : n
  return t
}
function Nl(e) {
  for (; e; ) {
    if (e.record.aliasOf) return !0
    e = e.parent
  }
  return !1
}
function Pl(e) {
  return e.reduce((e, t) => J(e, t.meta), {})
}
function Fl(e, t) {
  let n = 0,
    r = t.length
  for (; n !== r; ) {
    let i = (n + r) >> 1
    Tl(e, t[i]) < 0 ? (r = i) : (n = i + 1)
  }
  let i = Il(e)
  return (i && (r = t.lastIndexOf(i, r - 1)), r)
}
function Il(e) {
  let t = e
  for (; (t = t.parent); ) if (Ll(t) && Tl(e, t) === 0) return t
}
function Ll({ record: e }) {
  return !!(e.name || (e.components && Object.keys(e.components).length) || e.redirect)
}
function Rl(e) {
  let t = Ln(sl),
    n = Ln(cl),
    r = q(() => {
      let n = B(e.to)
      return t.resolve(n)
    }),
    i = q(() => {
      let { matched: e } = r.value,
        { length: t } = e,
        i = e[t - 1],
        a = n.matched
      if (!i || !a.length) return -1
      let o = a.findIndex(Nc.bind(null, i))
      if (o > -1) return o
      let s = Ul(e[t - 2])
      return t > 1 && Ul(i) === s && a[a.length - 1].path !== s ? a.findIndex(Nc.bind(null, e[t - 2])) : o
    }),
    a = q(() => i.value > -1 && Hl(n.params, r.value.params)),
    o = q(() => i.value > -1 && i.value === n.matched.length - 1 && Pc(n.params, r.value.params))
  function s(n = {}) {
    if (Vl(n)) {
      let n = t[B(e.replace) ? `replace` : `push`](B(e.to)).catch(ic)
      return (e.viewTransition && typeof document < `u` && `startViewTransition` in document && document.startViewTransition(() => n), n)
    }
    return Promise.resolve()
  }
  return { route: r, href: q(() => r.value.href), isActive: a, isExactActive: o, navigate: s }
}
function zl(e) {
  return e.length === 1 ? e[0] : e
}
var Bl = br({
  name: `RouterLink`,
  compatConfig: { MODE: 3 },
  props: {
    to: { type: [String, Object], required: !0 },
    replace: Boolean,
    activeClass: String,
    exactActiveClass: String,
    custom: Boolean,
    ariaCurrentValue: { type: String, default: `page` },
    viewTransition: Boolean,
  },
  useLink: Rl,
  setup(e, { slots: t }) {
    let n = Pt(Rl(e)),
      { options: r } = Ln(sl),
      i = q(() => ({
        [Wl(e.activeClass, r.linkActiveClass, `router-link-active`)]: n.isActive,
        [Wl(e.exactActiveClass, r.linkExactActiveClass, `router-link-exact-active`)]: n.isExactActive,
      }))
    return () => {
      let r = t.default && zl(t.default(n))
      return e.custom
        ? r
        : Xa(
            `a`,
            {
              'aria-current': n.isExactActive ? e.ariaCurrentValue : null,
              href: n.href,
              onClick: n.navigate,
              class: i.value,
            },
            r,
          )
    }
  },
})
function Vl(e) {
  if (!(e.metaKey || e.altKey || e.ctrlKey || e.shiftKey) && !e.defaultPrevented && !(e.button !== void 0 && e.button !== 0)) {
    if (e.currentTarget && e.currentTarget.getAttribute) {
      let t = e.currentTarget.getAttribute(`target`)
      if (/\b_blank\b/i.test(t)) return
    }
    return (e.preventDefault && e.preventDefault(), !0)
  }
}
function Hl(e, t) {
  for (let n in t) {
    let r = t[n],
      i = e[n]
    if (typeof r == `string`) {
      if (r !== i) return !1
    } else if (!ac(i) || i.length !== r.length || r.some((e, t) => e.valueOf() !== i[t].valueOf())) return !1
  }
  return !0
}
function Ul(e) {
  return e ? (e.aliasOf ? e.aliasOf.path : e.path) : ``
}
var Wl = (e, t, n) => e ?? t ?? n,
  Gl = br({
    name: `RouterView`,
    inheritAttrs: !1,
    props: { name: { type: String, default: `default` }, route: Object },
    compatConfig: { MODE: 3 },
    setup(e, { attrs: t, slots: n }) {
      let r = Ln(ll),
        i = q(() => e.route || r.value),
        a = Ln(ol, 0),
        o = q(() => {
          let e = B(a),
            { matched: t } = i.value,
            n
          for (; (n = t[e]) && !n.components; ) e++
          return e
        }),
        s = q(() => i.value.matched[o.value])
      ;(In(
        ol,
        q(() => o.value + 1),
      ),
        In(al, s),
        In(ll, i))
      let c = z()
      return (
        Vn(
          () => [c.value, s.value, e.name],
          ([e, t, n], [r, i, a]) => {
            ;(t &&
              ((t.instances[n] = e),
              i &&
                i !== t &&
                e &&
                e === r &&
                (t.leaveGuards.size || (t.leaveGuards = i.leaveGuards), t.updateGuards.size || (t.updateGuards = i.updateGuards))),
              e && t && (!i || !Nc(t, i) || !r) && (t.enterCallbacks[n] || []).forEach((t) => t(e)))
          },
          { flush: `post` },
        ),
        () => {
          let r = i.value,
            a = e.name,
            o = s.value,
            l = o && o.components[a]
          if (!l) return Kl(n.default, { Component: l, route: r })
          let u = o.props[a],
            d = Xa(
              l,
              J({}, u ? (u === !0 ? r.params : typeof u == `function` ? u(r) : u) : null, t, {
                onVnodeUnmounted: (e) => {
                  e.component.isUnmounted && (o.instances[a] = null)
                },
                ref: c,
              }),
            )
          return Kl(n.default, { Component: d, route: r }) || d
        }
      )
    },
  })
function Kl(e, t) {
  if (!e) return null
  let n = e(t)
  return n.length === 1 ? n[0] : n
}
var ql = Gl
function Jl(e) {
  let t = kl(e.routes, e),
    n = e.parseQuery || nl,
    r = e.stringifyQuery || rl,
    i = e.history,
    a = ul(),
    o = ul(),
    s = ul(),
    c = Gt(Rc),
    l = Rc
  ec && e.scrollBehavior && `scrollRestoration` in history && (history.scrollRestoration = `manual`)
  let u = rc.bind(null, (e) => `` + e),
    d = rc.bind(null, Ec),
    f = rc.bind(null, Dc)
  function p(e, n) {
    let r, i
    return (Qc(e) ? ((r = t.getRecordMatcher(e)), (i = n)) : (i = e), t.addRoute(i, r))
  }
  function m(e) {
    let n = t.getRecordMatcher(e)
    n && t.removeRoute(n)
  }
  function h() {
    return t.getRoutes().map((e) => e.record)
  }
  function g(e) {
    return !!t.getRecordMatcher(e)
  }
  function _(e, a) {
    if (((a = J({}, a || c.value)), typeof e == `string`)) {
      let r = Ac(n, e, a.path),
        o = t.resolve({ path: r.path }, a),
        s = i.createHref(r.fullPath)
      return J(r, o, { params: f(o.params), hash: Dc(r.hash), redirectedFrom: void 0, href: s })
    }
    let o
    if (e.path != null) o = J({}, e, { path: Ac(n, e.path, a.path).path })
    else {
      let t = J({}, e.params)
      for (let e in t) t[e] ?? delete t[e]
      ;((o = J({}, e, { params: d(t) })), (a.params = d(a.params)))
    }
    let s = t.resolve(o, a),
      l = e.hash || ``
    s.params = u(f(s.params))
    let p = jc(r, J({}, e, { hash: Sc(l), path: s.path })),
      m = i.createHref(p)
    return J({ fullPath: p, hash: l, query: r === rl ? il(e.query) : e.query || {} }, s, {
      redirectedFrom: void 0,
      href: m,
    })
  }
  function v(e) {
    return typeof e == `string` ? Ac(n, e, c.value.path) : J({}, e)
  }
  function y(e, t) {
    if (l !== e) return el(Y.NAVIGATION_CANCELLED, { from: t, to: e })
  }
  function b(e) {
    return C(e)
  }
  function x(e) {
    return b(J(v(e), { replace: !0 }))
  }
  function S(e, t) {
    let n = e.matched[e.matched.length - 1]
    if (n && n.redirect) {
      let { redirect: r } = n,
        i = typeof r == `function` ? r(e, t) : r
      return (
        typeof i == `string` && ((i = i.includes(`?`) || i.includes(`#`) ? (i = v(i)) : { path: i }), (i.params = {})),
        J({ query: e.query, hash: e.hash, params: i.path == null ? e.params : {} }, i)
      )
    }
  }
  function C(e, t) {
    let n = (l = _(e)),
      i = c.value,
      a = e.state,
      o = e.force,
      s = e.replace === !0,
      u = S(n, i)
    if (u) return C(J(v(u), { state: typeof u == `object` ? J({}, a, u.state) : a, force: o, replace: s }), t || n)
    let d = n
    d.redirectedFrom = t
    let f
    return (
      !o && Mc(r, i, n) && ((f = el(Y.NAVIGATION_DUPLICATED, { to: d, from: i })), re(i, i, !0, !1)),
      (f ? Promise.resolve(f) : E(d, i))
        .catch((e) => (tl(e) ? (tl(e, Y.NAVIGATION_GUARD_REDIRECT) ? e : ne(e)) : te(e, d, i)))
        .then((e) => {
          if (e) {
            if (tl(e, Y.NAVIGATION_GUARD_REDIRECT))
              return C(
                J({ replace: s }, v(e.to), {
                  state: typeof e.to == `object` ? J({}, a, e.to.state) : a,
                  force: o,
                }),
                t || d,
              )
          } else e = O(d, i, !0, s, a)
          return (D(d, i, e), e)
        })
    )
  }
  function w(e, t) {
    let n = y(e, t)
    return n ? Promise.reject(n) : Promise.resolve()
  }
  function T(e) {
    let t = oe.values().next().value
    return t && typeof t.runWithContext == `function` ? t.runWithContext(e) : e()
  }
  function E(e, t) {
    let n,
      [r, i, s] = pl(e, t)
    n = fl(r.reverse(), `beforeRouteLeave`, e, t)
    for (let i of r)
      i.leaveGuards.forEach((r) => {
        n.push(dl(r, e, t))
      })
    let c = w.bind(null, e, t)
    return (
      n.push(c),
      ce(n)
        .then(() => {
          n = []
          for (let r of a.list()) n.push(dl(r, e, t))
          return (n.push(c), ce(n))
        })
        .then(() => {
          n = fl(i, `beforeRouteUpdate`, e, t)
          for (let r of i)
            r.updateGuards.forEach((r) => {
              n.push(dl(r, e, t))
            })
          return (n.push(c), ce(n))
        })
        .then(() => {
          n = []
          for (let r of s)
            if (r.beforeEnter)
              if (ac(r.beforeEnter)) for (let i of r.beforeEnter) n.push(dl(i, e, t))
              else n.push(dl(r.beforeEnter, e, t))
          return (n.push(c), ce(n))
        })
        .then(() => (e.matched.forEach((e) => (e.enterCallbacks = {})), (n = fl(s, `beforeRouteEnter`, e, t, T)), n.push(c), ce(n)))
        .then(() => {
          n = []
          for (let r of o.list()) n.push(dl(r, e, t))
          return (n.push(c), ce(n))
        })
        .catch((e) => (tl(e, Y.NAVIGATION_CANCELLED) ? e : Promise.reject(e)))
    )
  }
  function D(e, t, n) {
    s.list().forEach((r) => T(() => r(e, t, n)))
  }
  function O(e, t, n, r, a) {
    let o = y(e, t)
    if (o) return o
    let s = t === Rc,
      l = ec ? history.state : {}
    ;(n && (r || s ? i.replace(e.fullPath, J({ scroll: s && l && l.scroll }, a)) : i.push(e.fullPath, a)),
      (c.value = e),
      re(e, t, n, s),
      ne())
  }
  let k
  function A() {
    k ||= i.listen((e, t, n) => {
      if (!se.listening) return
      let r = _(e),
        a = S(r, se.currentRoute.value)
      if (a) {
        C(J(a, { replace: !0, force: !0 }), r).catch(ic)
        return
      }
      l = r
      let o = c.value
      ;(ec && Yc(qc(o.fullPath, n.delta), Gc()),
        E(r, o)
          .catch((e) =>
            tl(e, Y.NAVIGATION_ABORTED | Y.NAVIGATION_CANCELLED)
              ? e
              : tl(e, Y.NAVIGATION_GUARD_REDIRECT)
                ? (C(J(v(e.to), { force: !0 }), r)
                    .then((e) => {
                      tl(e, Y.NAVIGATION_ABORTED | Y.NAVIGATION_DUPLICATED) && !n.delta && n.type === zc.pop && i.go(-1, !1)
                    })
                    .catch(ic),
                  Promise.reject())
                : (n.delta && i.go(-n.delta, !1), te(e, r, o)),
          )
          .then((e) => {
            ;((e ||= O(r, o, !1)),
              e &&
                (n.delta && !tl(e, Y.NAVIGATION_CANCELLED)
                  ? i.go(-n.delta, !1)
                  : n.type === zc.pop && tl(e, Y.NAVIGATION_ABORTED | Y.NAVIGATION_DUPLICATED) && i.go(-1, !1)),
              D(r, o, e))
          })
          .catch(ic))
    })
  }
  let j = ul(),
    ee = ul(),
    M
  function te(e, t, n) {
    ne(e)
    let r = ee.list()
    return (r.length ? r.forEach((r) => r(e, t, n)) : console.error(e), Promise.reject(e))
  }
  function N() {
    return M && c.value !== Rc
      ? Promise.resolve()
      : new Promise((e, t) => {
          j.add([e, t])
        })
  }
  function ne(e) {
    return (M || ((M = !e), A(), j.list().forEach(([t, n]) => (e ? n(e) : t())), j.reset()), e)
  }
  function re(t, n, r, i) {
    let { scrollBehavior: a } = e
    if (!ec || !a) return Promise.resolve()
    let o = (!r && Xc(qc(t.fullPath, 0))) || ((i || !r) && history.state && history.state.scroll) || null
    return xn()
      .then(() => a(t, n, o))
      .then((e) => e && Kc(e))
      .catch((e) => te(e, t, n))
  }
  let ie = (e) => i.go(e),
    ae,
    oe = new Set(),
    se = {
      currentRoute: c,
      listening: !0,
      addRoute: p,
      removeRoute: m,
      clearRoutes: t.clearRoutes,
      hasRoute: g,
      getRoutes: h,
      resolve: _,
      options: e,
      push: b,
      replace: x,
      go: ie,
      back: () => ie(-1),
      forward: () => ie(1),
      beforeEach: a.add,
      beforeResolve: o.add,
      afterEach: s.add,
      onError: ee.add,
      isReady: N,
      install(e) {
        ;(e.component(`RouterLink`, Bl),
          e.component(`RouterView`, ql),
          (e.config.globalProperties.$router = se),
          Object.defineProperty(e.config.globalProperties, '$route', {
            enumerable: !0,
            get: () => B(c),
          }),
          ec && !ae && c.value === Rc && ((ae = !0), b(i.location).catch((e) => {})))
        let t = {}
        for (let e in Rc) Object.defineProperty(t, e, { get: () => c.value[e], enumerable: !0 })
        ;(e.provide(sl, se), e.provide(cl, Ft(t)), e.provide(ll, c))
        let n = e.unmount
        ;(oe.add(e),
          (e.unmount = function () {
            ;(oe.delete(e), oe.size < 1 && ((l = Rc), k && k(), (k = null), (c.value = Rc), (ae = !1), (M = !1)), n())
          }))
      },
    }
  function ce(e) {
    return e.reduce((e, t) => e.then(() => T(t)), Promise.resolve())
  }
  return se
}
function Yl() {
  return Ln(sl)
}
function Xl(e) {
  return Ln(cl)
}
var Zl = { consent: `xc_butler_consent`, pos: `xc_butler_pos`, dismissed: `xc_butler_dismissed` }
function Ql() {
  try {
    return localStorage.getItem(Zl.consent) === `v1`
  } catch {
    return !1
  }
}
function $l() {
  try {
    let e = localStorage.getItem(Zl.pos)
    if (e) {
      let t = JSON.parse(e)
      if (typeof t.x == `number` && typeof t.y == `number`) return { x: t.x, y: t.y }
    }
  } catch {}
  return { x: Math.max(8, window.innerWidth - 152), y: Math.max(8, window.innerHeight - 118) }
}
function eu() {
  try {
    return localStorage.getItem(Zl.dismissed) === `1`
  } catch {
    return !1
  }
}
var tu = Qs(`agent`, () => {
    let e = z(!1),
      t = z(`idle`),
      n = z(Ql()),
      r = z(!1),
      i = z($l()),
      a = z(eu()),
      o = z([]),
      s = z(null),
      c = z(!1),
      l = z(null),
      u = z(null),
      d = z(0),
      f = z(!1),
      p = q(() => t.value === `idle`)
    function m(t) {
      if (!n.value) {
        r.value = !0
        return
      }
      ;(t?.focusFiles && (f.value = !0), (e.value = !0), (d.value = 0))
    }
    function h() {
      f.value = !1
    }
    function g() {
      e.value = !1
    }
    function _() {
      ;((n.value = !0), (r.value = !1))
      try {
        localStorage.setItem(Zl.consent, `v1`)
      } catch {}
      e.value = !0
    }
    function v() {
      r.value = !1
    }
    function y() {
      ;((a.value = !0), (e.value = !1))
      try {
        localStorage.setItem(Zl.dismissed, `1`)
      } catch {}
    }
    function b() {
      a.value = !1
      try {
        localStorage.removeItem(Zl.dismissed)
      } catch {}
    }
    function x(e) {
      t.value = e
    }
    function S(e, t) {
      i.value = { x: e, y: t }
      try {
        localStorage.setItem(Zl.pos, JSON.stringify({ x: e, y: t }))
      } catch {}
    }
    function C(t) {
      ;((o.value = [...o.value, t]), !e.value && t.role !== `system` && (d.value += 1))
    }
    function w(e) {
      let t = o.value
      t.length && (o.value = [...t.slice(0, -1), { ...t[t.length - 1], ...e }])
    }
    function T() {
      ;((o.value = []), (l.value = null))
    }
    function E(e) {
      ;((s.value = e), e ? (t.value = `awaiting_confirm`) : t.value === `awaiting_confirm` && (t.value = `idle`))
    }
    function D() {
      ;((u.value = null), t.value === `orchestrating` && (t.value = `idle`))
    }
    return {
      isOpen: e,
      mode: t,
      consentGiven: n,
      showPermissionDialog: r,
      position: i,
      dismissed: a,
      messages: o,
      pendingAction: s,
      isLoading: c,
      currentConversationId: l,
      orchestrationSession: u,
      unreadCount: d,
      focusFilesDrawer: f,
      isIdle: p,
      openPanel: m,
      clearFilesDrawerFocus: h,
      closePanel: g,
      grantConsent: _,
      dismissLater: v,
      dismissButler: y,
      restoreButler: b,
      setMode: x,
      savePosition: S,
      addMessage: C,
      updateLastMessage: w,
      clearMessages: T,
      setPendingAction: E,
      clearOrchestration: D,
    }
  }),
  nu = `(max-width: 960px)`
function ru() {
  return typeof window > `u` ? !1 : window.matchMedia(nu).matches
}
function iu() {
  let e = z(ru())
  return (
    Fr(() => {
      let t = window.matchMedia(nu),
        n = () => {
          e.value = t.matches
        }
      ;(n(), t.addEventListener(`change`, n), Rr(() => t.removeEventListener(`change`, n)))
    }),
    e
  )
}
function au() {
  return ru() ? `下方` : `左侧`
}
var ou = `xc_butler_pos_corp`
function su() {
  return typeof window > `u` ? !1 : /\/contact(?:\.html)?\/?$/i.test(window.location.pathname)
}
function cu() {
  let e = Math.max(8, window.innerHeight - 82 - 24),
    t = ru()
  return { x: su() || t ? 16 : Math.max(8, window.innerWidth - 64 - 16), y: e }
}
function lu(e, t) {
  if (!ru()) return !1
  let n = window.innerWidth - 72,
    r = window.innerHeight - 80
  return e >= n && t >= r
}
function uu(e, t) {
  return {
    x: Math.max(8, Math.min(window.innerWidth - 64 - 8, e)),
    y: Math.max(8, Math.min(window.innerHeight - 82 - 8, t)),
  }
}
function du(e, t) {
  return typeof window > `u` || ru() || su()
    ? !1
    : t < 120 || (e < Math.min(480, window.innerWidth * 0.42) && t < window.innerHeight * 0.55)
}
function fu() {
  try {
    let e = localStorage.getItem(ou)
    if (e) {
      let t = JSON.parse(e)
      if (typeof t.x == `number` && typeof t.y == `number`) {
        let e = uu(t.x, t.y)
        if (lu(e.x, e.y) || du(e.x, e.y)) {
          let e = cu()
          try {
            localStorage.setItem(ou, JSON.stringify(e))
          } catch {}
          return e
        }
        return e
      }
    }
  } catch {}
  return cu()
}
function pu(e, t) {
  let n = uu(e, t)
  try {
    localStorage.setItem(ou, JSON.stringify(n))
  } catch {}
  return n
}
function mu() {
  let e = [],
    t = document.title || ``
  ;(t && e.push(`页面标题：${t}`), e.push(`当前路径：${window.location.pathname}`))
  let n = Array.from(document.querySelectorAll(`h1, h2, h3`))
    .map((e) => e.textContent?.trim())
    .filter(Boolean)
    .slice(0, 8)
  n.length && e.push(`页面标题区：${n.join(` | `)}`)
  let r = Array.from(document.querySelectorAll(`button, [role="button"], a.btn, .btn`))
    .filter((e) => hu(e))
    .map((e) => e.textContent?.trim() || e.getAttribute(`aria-label`) || ``)
    .filter(Boolean)
    .slice(0, 20)
  r.length && e.push(`页面按钮：${r.join(` | `)}`)
  let i = Array.from(document.querySelectorAll(`input[placeholder], textarea[placeholder]`))
    .filter((e) => hu(e))
    .map((e) => e.placeholder)
    .filter(Boolean)
    .slice(0, 10)
  i.length && e.push(`输入框提示：${i.join(` | `)}`)
  let a = Array.from(document.querySelectorAll(`th`))
    .map((e) => e.textContent?.trim())
    .filter(Boolean)
    .slice(0, 15)
  a.length && e.push(`表格列：${a.join(` | `)}`)
  let o = document.querySelector(`main`)?.textContent?.replace(/\s+/g, ` `).trim().slice(0, 400) || ``
  return (
    o && e.push(`页面主要内容：${o}`),
    e.join(`
`)
  )
}
function hu(e) {
  if (!(e instanceof HTMLElement)) return !0
  let t = window.getComputedStyle(e)
  return t.display !== `none` && t.visibility !== `hidden` && t.opacity !== `0`
}
var Z = {
    home: `/index.html`,
    about: `/about.html`,
    services: `/services.html`,
    solutions: `/solutions.html`,
    cases: `/cases.html`,
    caseManufacture: `/case-manufacture.html`,
    casePark: `/case-park.html`,
    caseEdu: `/case-edu.html`,
    news: `/news.html`,
    honors: `/honors.html`,
    contact: `/contact.html`,
    excelToAi: `/excel-to-ai.html`,
    market: `/market/`,
  },
  gu = `Hi，我是小C`,
  _u = { label: `预约方案沟通`, task: `navigate`, payload: { href: Z.contact } },
  vu = { label: `进入 AI 市场`, task: `navigate`, payload: { href: Z.market } },
  yu = {
    home: {
      pageId: `home`,
      paths: [`/`, `/index.html`, `/index`],
      title: `成都修茈科技有限公司 | XCAGI 企业 AI 自动化`,
      description: `成都修茈科技有限公司专注 AI 单据智能处理、Excel 识别、标签打印、出货收货管理和企业流程自动化，帮助中小企业把业务数据真正跑起来。`,
      welcomeTitle: `Hi，想了解修茈能帮您做什么？`,
      welcomeDesc: `我可以介绍产品矩阵，并引导您查看行业方案、客户案例或预约沟通。`,
      summary: `官网首页展示修茈科技产品矩阵：AI Excel 单据识别、标签打印与库存记录、MODstore 智能体市场，以及制造、园区、教育等场景案例入口。`,
      highlights: [`AI Excel Helper 单据识别`, `标签打印与收发货记录`, `MODstore AI 工作台`, `预约方案沟通`],
      quickActions: [
        { label: `介绍产品矩阵`, message: `你们有哪些产品？` },
        { label: `查看行业解决方案`, message: `有哪些行业解决方案？` },
        { label: `看看客户案例`, message: `有哪些客户案例？` },
        _u,
        vu,
      ],
    },
    about: {
      pageId: `about`,
      paths: [`/about.html`],
      title: `关于修茈 | 成都修茈科技有限公司`,
      description: `了解成都修茈科技有限公司：专注 AI 单据处理、企业流程自动化与 XCAGI 工作台，为中小企业提供可落地的数字化方案。`,
      welcomeTitle: `Hi，想了解修茈科技是谁？`,
      welcomeDesc: `本页介绍公司定位、XCAGI 工作台与 MODstore 的关系，可问我如何开始试用。`,
      summary: `成都修茈科技（XCAGI）专注中小企业 AI 自动化：从单据识别到工作台与智能体市场，强调可落地实施与持续迭代。`,
      highlights: [`公司定位与团队方向`, `XCAGI 工作台能力`, `与 MODstore 智能体市场衔接`],
      quickActions: [
        { label: `公司是做什么的`, message: `修茈科技是做什么的？` },
        { label: `有哪些产品能力`, message: `你们有哪些产品？` },
        { label: `如何开始试用`, message: `怎么注册或试用 AI 市场？` },
        _u,
        vu,
      ],
    },
    services: {
      pageId: `services`,
      paths: [`/services.html`],
      title: `产品中心 | 成都修茈科技有限公司`,
      description: `修茈科技产品中心：AI Excel Helper、标签打印、出货收货管理、微信消息自动化、知识库与 AI 工作流。`,
      welcomeTitle: `Hi，想了解哪类产品？`,
      welcomeDesc: `可问我各产品线适用场景，或带您看行业方案与预约沟通。`,
      summary: `产品中心涵盖 AI Excel 单据识别、标签打印与库存、出货收货、微信自动化、知识库与 MODstore 智能体市场等可组合能力。`,
      highlights: [`AI Excel Helper`, `标签打印与库存`, `MODstore 市场`, `微信与知识库自动化`],
      quickActions: [
        { label: `AI Excel 单据识别`, message: `AI Excel 单据识别能做什么？` },
        { label: `标签打印与库存`, message: `标签打印和库存记录怎么用？` },
        { label: `看行业解决方案`, message: `有哪些行业解决方案？` },
        _u,
        vu,
      ],
    },
    solutions: {
      pageId: `solutions`,
      paths: [`/solutions.html`],
      title: `解决方案 | 成都修茈科技有限公司`,
      description: `修茈科技解决方案覆盖制造贸易单据处理、园区服务协同、教育移动服务和企业 AI 工作流。`,
      welcomeTitle: `Hi，您的行业是哪种场景？`,
      welcomeDesc: `可按制造贸易、园区、教育等方向了解方案，并查看对应案例。`,
      summary: `解决方案覆盖制造贸易单据与库存协同、园区企业服务、教育移动服务，以及企业级 AI 工作流编排。`,
      highlights: [`制造与贸易`, `园区综合服务`, `教育协同`, `AI 工作流`],
      quickActions: [
        { label: `制造贸易怎么落地`, message: `制造贸易场景怎么落地？` },
        { label: `园区综合服务`, message: `园区企业服务平台案例` },
        { label: `校园移动服务`, message: `校园移动服务案例` },
        { label: `了解产品能力`, message: `你们有哪些产品？` },
        _u,
      ],
    },
    cases: {
      pageId: `cases`,
      paths: [`/cases.html`],
      title: `客户案例 | 成都修茈科技有限公司`,
      description: `修茈科技案例中心：制造企业生产协同、园区企业服务平台、校园移动服务与业务协同。`,
      welcomeTitle: `Hi，想看看哪类客户实践？`,
      welcomeDesc: `案例中心汇总制造、园区、教育等方向，可指定行业让我推荐详情。`,
      summary: `案例中心展示制造生产协同、园区企业服务平台、校园移动服务等方向的实践摘要与详情链接。`,
      highlights: [`制造生产协同`, `园区服务平台`, `校园移动服务`],
      quickActions: [
        { label: `制造生产协同案例`, message: `制造企业案例详情` },
        { label: `园区服务平台案例`, message: `园区企业服务平台案例` },
        { label: `校园移动服务案例`, message: `校园移动服务案例` },
        { label: `了解产品与方案`, message: `你们有哪些产品？` },
        _u,
      ],
    },
    'case-manufacture': {
      pageId: `case-manufacture`,
      paths: [`/case-manufacture.html`],
      title: `案例详情 - 生产协同与库存管理 | 成都修茈科技有限公司`,
      description: `制造企业生产协同与库存管理案例，围绕生产计划、库存数据、报表分析和跨部门协同进行系统化建设。`,
      welcomeTitle: `Hi，想了解制造协同案例？`,
      welcomeDesc: `本页介绍生产计划、库存、报表与跨部门协同，可问挑战、方案或如何复用到您企业。`,
      summary: `制造案例：围绕生产计划、仓储库存、报表分析与跨部门协同建设一体化系统，降低重复录入与错漏。`,
      highlights: [`生产计划协同`, `库存数据统一`, `报表分析`, `跨部门流程`],
      quickActions: [
        { label: `案例解决了什么问题`, message: `这个制造案例解决了什么问题？` },
        { label: `方案怎么落地`, message: `制造贸易场景怎么落地？` },
        { label: `更多客户案例`, message: `有哪些客户案例？` },
        _u,
        { label: `了解产品能力`, message: `你们有哪些产品？` },
      ],
    },
    'case-park': {
      pageId: `case-park`,
      paths: [`/case-park.html`],
      title: `案例详情 - 园区企业综合服务平台 | 成都修茈科技有限公司`,
      description: `园区企业综合服务平台案例，建设企业服务、事项办理、统计分析和领导驾驶舱等能力。`,
      welcomeTitle: `Hi，想了解园区服务案例？`,
      welcomeDesc: `本页介绍企业服务、事项办理、统计与领导驾驶舱，可问实施路径或预约交流。`,
      summary: `园区案例：整合企业服务、事项办理、数据统计与领导驾驶舱，提升园区数字化管理效率。`,
      highlights: [`企业服务入口`, `事项办理`, `统计分析`, `领导驾驶舱`],
      quickActions: [
        { label: `案例亮点是什么`, message: `园区企业服务平台案例` },
        { label: `如何在我们园区复用`, message: `园区方案怎么在我们园区落地？` },
        { label: `更多客户案例`, message: `有哪些客户案例？` },
        _u,
        { label: `了解产品能力`, message: `你们有哪些产品？` },
      ],
    },
    'case-edu': {
      pageId: `case-edu`,
      paths: [`/case-edu.html`],
      title: `案例详情 - 校园移动服务与业务协同 | 成都修茈科技有限公司`,
      description: `校园移动服务与业务协同案例，整合通知、审批、服务申请和统计分析，提升师生服务体验。`,
      welcomeTitle: `Hi，想了解校园服务案例？`,
      welcomeDesc: `本页介绍通知、审批、服务申请与统计，可问适用学校类型或对接方式。`,
      summary: `教育案例：统一通知、审批、服务申请与数据统计，改善师生服务体验与管理效率。`,
      highlights: [`移动服务入口`, `审批流程`, `服务申请`, `数据统计`],
      quickActions: [
        { label: `案例适用哪些学校`, message: `校园移动服务案例` },
        { label: `教育场景怎么落地`, message: `教育场景怎么落地？` },
        { label: `更多客户案例`, message: `有哪些客户案例？` },
        _u,
        { label: `了解产品能力`, message: `你们有哪些产品？` },
      ],
    },
    news: {
      pageId: `news`,
      paths: [`/news.html`],
      title: `新闻资讯 | 成都修茈科技有限公司`,
      description: `修茈科技新闻资讯与行业观察：企业 AI 自动化、单据处理、Agent 趋势与中小企业数字化。`,
      welcomeTitle: `Hi，想了解最新动态？`,
      welcomeDesc: `可问公司新闻、行业观察，或带您看产品与预约沟通。`,
      summary: `新闻资讯栏目提供公司动态、产品更新与行业观察，帮助了解 AI 自动化与单据处理趋势。`,
      highlights: [`公司动态`, `行业观察`, `产品更新`],
      quickActions: [
        { label: `最新公司动态`, message: `修茈科技最近有什么动态？` },
        { label: `行业与 AI 趋势`, message: `企业 AI 自动化有什么趋势？` },
        { label: `了解产品`, message: `你们有哪些产品？` },
        _u,
        vu,
      ],
    },
    honors: {
      pageId: `honors`,
      paths: [`/honors.html`],
      title: `资质与能力 | 成都修茈科技有限公司`,
      description: `成都修茈科技有限公司能力说明：软件开发、项目实施、信息安全、服务机制和持续迭代能力。`,
      welcomeTitle: `Hi，想了解合作保障？`,
      welcomeDesc: `本页说明研发、交付、安全与服务机制（以实际公示为准），可问资质或预约沟通。`,
      summary: `能力说明涵盖软件开发、项目实施、信息安全、服务机制与持续迭代；具体资质证照以实际公示为准。`,
      highlights: [`软件开发能力`, `项目实施`, `信息安全`, `服务与迭代机制`],
      quickActions: [
        { label: `交付与服务机制`, message: `修茈科技的服务和交付机制是怎样的？` },
        { label: `信息安全能力`, message: `你们的信息安全能力如何？` },
        { label: `有哪些产品`, message: `你们有哪些产品？` },
        _u,
        vu,
      ],
    },
    contact: {
      pageId: `contact`,
      paths: [`/contact.html`],
      title: `联系我们 | 成都修茈科技有限公司`,
      description: `联系成都修茈科技有限公司，咨询 AI 单据处理、企业自动化、MODstore 智能体市场和数字化解决方案。`,
      welcomeTitle: `Hi，我来帮您填需求问卷`,
      welcomeDesc: `告诉我公司与系统类型，我可一键预填右侧问卷，您简单改改就能提交。`,
      summary: `联系我们页提供预约方案沟通表单，可说明单据识别、标签打印、AI 工作台等需求，我们会尽快回复。`,
      highlights: [`预约方案沟通`, `场景需求说明`, `销售与技术支持入口`],
      quickActions: [
        {
          label: `AI 一键填好问卷`,
          task: `intake_fill`,
          message: `请根据公司与系统类型帮我预填问卷`,
        },
        {
          label: `贸易公司 + Excel 跟单示例`,
          task: `intake_fill`,
          payload: {
            prompt: `公司：示例贸易有限公司
主要系统/业务：Excel 跟单

请根据该公司与系统类型的典型业务场景，完整预填联系页需求问卷。draft 中 company 填「示例贸易有限公司」。不要编造手机、邮箱、姓名。`,
          },
        },
        { label: `跳到联系方式`, task: `intake_step`, payload: { stepId: `contact` } },
        { label: `提交前帮我核对`, task: `intake_review` },
      ],
    },
    'excel-to-ai': {
      pageId: `excel-to-ai`,
      paths: [`/excel-to-ai.html`],
      title: `Excel → AI 上传工具 | 成都修茈科技有限公司`,
      description: `在线体验 AI Excel 单据识别：上传出货单、收货单等表格，自动提取关键字段，了解修茈科技单据处理能力。`,
      welcomeTitle: `Hi，想体验 Excel 识别？`,
      welcomeDesc: `本页可上传表格试识别；完整流程与打印联动见产品中心，也可预约方案沟通。`,
      summary: `Excel → AI 工具页用于快速体验表格单据识别，提取产品、数量、价格等字段，完整能力见 AI Excel Helper 与产品中心。`,
      highlights: [`上传 Excel 体验`, `字段自动提取`, `对接完整产品线`],
      quickActions: [
        { label: `上传工具怎么用`, message: `Excel 上传工具怎么用？` },
        { label: `完整单据识别能力`, message: `AI Excel 单据识别能做什么？` },
        { label: `查看产品中心`, task: `navigate`, payload: { href: Z.services } },
        _u,
        vu,
      ],
    },
    'market-about': {
      pageId: `market-about`,
      paths: [],
      title: `XC AGI 市场 | 智能员工与 AI 工作台`,
      description: `修茈科技 AI 市场：组合 Mod 与 AI 员工，处理单据、流程与报表；支持注册试用与进入工作台。`,
      welcomeDesc: `这是 AI 市场公开介绍页。可了解智能员工能力，或引导您注册、查看会员方案。`,
      summary: `AI 市场落地页介绍可复制的智能员工团队：单据识别、自动化处理、7×24 运行与多行业场景，可注册进入工作台。`,
      highlights: [`智能单据识别`, `自动化处理`, `7×24 AI 员工`, `免费注册试用`],
      quickActions: [
        { label: `有哪些能力`, message: `AI 市场有什么功能？` },
        { label: `会员方案`, message: `会员和价格怎么样？` },
        { label: `免费注册`, message: `怎么注册账号？` },
        { label: `官网产品`, message: `你们有哪些产品？` },
        { label: `联系咨询`, message: `怎么联系你们？` },
        { label: `本页介绍`, message: `这个页面有什么功能？` },
      ],
    },
  },
  bu = {
    'workbench-home': {
      pageId: `workbench-home`,
      title: `工作台首页 | XC AGI`,
      description: `XC AGI 工作台：对话、员工与 Mod 编排入口。`,
      summary: `工作台首页是登录后的主界面，可发起对话、管理 AI 员工与进入各工作台模块。`,
      highlights: [`新对话`, `员工与 Mod`, `快捷进入各模块`],
      quickActions: [
        { label: `这页有什么`, message: `这个页面有什么功能？` },
        { label: `AI 市场`, message: `去 AI 市场` },
        { label: `搜索员工`, message: `帮我搜索 AI 员工` },
        { label: `会员方案`, message: `去会员页面` },
        { label: `钱包余额`, message: `查看钱包余额` },
      ],
    },
    'ai-store': {
      pageId: `ai-store`,
      title: `AI 市场 | XC AGI`,
      description: `浏览与选购 AI 员工、模板与能力包。`,
      summary: `AI 市场页可浏览、搜索并选购 AI 员工与相关能力，支持查看详情与加入工作台。`,
      highlights: [`搜索员工`, `分类浏览`, `购买与试用`],
      quickActions: [
        { label: `搜索员工`, message: `帮我搜索 AI 员工` },
        { label: `这页有什么`, message: `这个页面有什么功能？` },
        { label: `去工作台`, message: `去工作台首页` },
        { label: `会员方案`, message: `去会员页面` },
        { label: `钱包`, message: `打开钱包` },
      ],
    },
    plans: {
      pageId: `plans`,
      title: `会员方案 | XC AGI`,
      description: `查看与购买 XC AGI 会员套餐。`,
      summary: `会员方案页展示各档套餐权益与价格，支持选择方案并完成购买。`,
      highlights: [`套餐对比`, `权益说明`, `购买开通`],
      quickActions: [
        { label: `会员方案`, message: `介绍一下会员套餐` },
        { label: `去充值`, message: `去充值页面` },
        { label: `AI 市场`, message: `去 AI 市场` },
        { label: `这页有什么`, message: `这个页面有什么功能？` },
      ],
    },
    wallet: {
      pageId: `wallet`,
      title: `钱包 | XC AGI`,
      description: `查看余额、消费记录与充值入口。`,
      summary: `钱包页展示账户余额、消费明细，并可进入充值或已购内容。`,
      highlights: [`余额查询`, `消费记录`, `充值入口`],
      quickActions: [
        { label: `去充值`, message: `去充值页面` },
        { label: `已购内容`, message: `查看已购 AI 员工` },
        { label: `会员方案`, message: `去会员页面` },
        { label: `这页有什么`, message: `这个页面有什么功能？` },
      ],
    },
    recharge: {
      pageId: `recharge`,
      title: `充值 | XC AGI`,
      description: `为账户充值以使用 AI 能力与员工。`,
      summary: `充值页可选择金额并完成支付，为后续调用 AI 员工与 LLM 提供余额。`,
      highlights: [`选择金额`, `支付方式`, `到账余额`],
      quickActions: [
        { label: `查看钱包`, message: `打开钱包` },
        { label: `会员方案`, message: `去会员页面` },
        { label: `这页有什么`, message: `这个页面有什么功能？` },
      ],
    },
    orders: {
      pageId: `orders`,
      title: `订单 | XC AGI`,
      description: `查看购买订单与支付状态。`,
      summary: `订单页列出历史购买记录与订单状态，便于核对会员与员工购买。`,
      highlights: [`订单列表`, `支付状态`, `订单详情`],
      quickActions: [
        { label: `AI 市场`, message: `去 AI 市场` },
        { label: `钱包`, message: `打开钱包` },
        { label: `这页有什么`, message: `这个页面有什么功能？` },
      ],
    },
    templates: {
      pageId: `templates`,
      title: `模板 | XC AGI`,
      description: `浏览工作流与场景模板。`,
      summary: `模板页提供可复用的工作流与场景模板，便于快速搭建 AI 员工与流程。`,
      highlights: [`模板分类`, `预览说明`, `应用到工作台`],
      quickActions: [
        { label: `去工作台`, message: `去工作台首页` },
        { label: `AI 市场`, message: `去 AI 市场` },
        { label: `这页有什么`, message: `这个页面有什么功能？` },
      ],
    },
    'developer-portal': {
      pageId: `developer-portal`,
      title: `开发者门户 | XC AGI`,
      description: `API、Mod 开发与集成文档入口。`,
      summary: `开发者门户提供 API 与 Mod 开发相关入口，便于二次集成与扩展。`,
      highlights: [`API 文档`, `Mod 开发`, `集成说明`],
      quickActions: [
        { label: `去工作台`, message: `去工作台首页` },
        { label: `账户设置`, message: `打开账户设置` },
        { label: `这页有什么`, message: `这个页面有什么功能？` },
      ],
    },
    account: {
      pageId: `account`,
      title: `账户设置 | XC AGI`,
      description: `个人资料、LLM 配置与 API Key 管理。`,
      summary: `账户设置页可修改资料、配置 LLM 供应商与 API Key，管理管家相关偏好。`,
      highlights: [`个人资料`, `LLM 设置`, `API Key`],
      quickActions: [
        { label: `钱包`, message: `打开钱包` },
        { label: `去工作台`, message: `去工作台首页` },
        { label: `这页有什么`, message: `这个页面有什么功能？` },
      ],
    },
    'workbench-shell': {
      pageId: `workbench-shell`,
      title: `工作台 | XC AGI`,
      description: `编辑 Mod、工作流或 AI 员工。`,
      summary: `工作台 Shell 用于编辑 Mod、工作流图或员工配置，是深度编排与调试入口。`,
      highlights: [`Mod 编辑`, `工作流`, `员工配置`],
      quickActions: [
        { label: `去首页`, message: `去工作台首页` },
        { label: `AI 市场`, message: `去 AI 市场` },
        { label: `这页有什么`, message: `这个页面有什么功能？` },
      ],
    },
  },
  xu = [
    { label: `这页有什么`, message: `这个页面有什么功能？` },
    { label: `去会员页`, message: `去会员页面` },
    { label: `搜索员工`, message: `帮我搜索 AI 员工` },
    { label: `AI 市场`, message: `去 AI 市场` },
    { label: `钱包`, message: `打开钱包` },
  ]
function Su(e) {
  return /\/contact(?:\.html)?\/?$/i.test(e || ``)
}
function Cu(e) {
  let t = e.replace(/\/$/, ``) || `/`
  for (let e of Object.values(yu))
    if (e.paths.some((e) => e === t || (e === `/` && (t === `/` || t.endsWith(`/index.html`))))) return e.pageId
  return (t === `` || t === `/` || /index\.html$/i.test(t), `home`)
}
function wu(e, t) {
  let { paths: n, ...r } = yu[e || (t ? Cu(t) : `home`)] || yu.home
  return r
}
function Tu(e) {
  return e ? (bu[e] ?? null) : null
}
function Eu(e) {
  let t = wu(void 0, e)
  return t.welcomeDesc || t.summary
}
function Du(e) {
  return wu(void 0, e).welcomeTitle || gu
}
function Ou(e) {
  return wu(void 0, e).quickActions
}
function ku(e) {
  return Tu(e)?.quickActions ?? xu
}
function Au(e) {
  let t = Tu(e)
  return t ? t.welcomeDesc || t.summary : `我可以理解当前页面，并帮你跳转、搜索或执行常用操作。`
}
function ju(e) {
  let t = e.corpPathname == null ? null : wu(void 0, e.corpPathname),
    n = (e.routeName ? Tu(e.routeName) : null) || t
  if (!n) return e.domExcerpt?.slice(0, 800) || ``
  let r = n.highlights.map((e) => `• ${e}`).join(`
`),
    i = `${n.summary}\n\n要点：\n${r}`
  return (e.domExcerpt?.trim() && (i += `\n\n页面可见内容（节选）：\n${e.domExcerpt.slice(0, 400)}`), i.slice(0, 1200))
}
function Mu(e) {
  return (
    {
      home: Z.home,
      about: Z.about,
      services: Z.services,
      solutions: Z.solutions,
      cases: Z.cases,
      'case-manufacture': Z.caseManufacture,
      'case-park': Z.casePark,
      'case-edu': Z.caseEdu,
      news: Z.news,
      honors: Z.honors,
      contact: Z.contact,
      'excel-to-ai': Z.excelToAi,
      'market-about': Z.market,
    }[e] || Z.home
  )
}
function Nu(e) {
  return { success: !0, message: e, assistantReply: e }
}
function Pu(e) {
  let t = Cu(e),
    n = wu(t)
  return t === `contact`
    ? `您正在查看联系我们页，可直接填写需求表单预约方案沟通。`
    : t === `services`
      ? `您正在产品中心，可了解各产品线与能力说明。`
      : t === `solutions`
        ? `您正在解决方案页，可按行业查看场景与案例链接。`
        : t === `cases` || t.startsWith(`case-`)
          ? `您正在案例相关页面，可了解实践方向或进入详情。`
          : t === `news`
            ? `您正在新闻资讯页，可查看公司动态与行业观察。`
            : t === `honors`
              ? `您正在资质与能力页，了解研发、交付与安全服务机制。`
              : t === `excel-to-ai`
                ? `您正在 Excel 体验工具页，可上传表格试识别；完整能力见产品中心。`
                : t === `home`
                  ? `您正在官网首页，可了解产品矩阵并进入 AI 市场或预约沟通。`
                  : `您正在「${n.title.replace(/\s*\|.*/, ``)}」。${n.summary}`
}
function Fu(e) {
  let t = e.userMessage.trim().toLowerCase(),
    n = e.route || ``
  if (/这页|页面|当前|干什么|介绍.*页/.test(t)) {
    let t = Cu(n),
      r = wu(t),
      i = Pu(n),
      a = e.pageSummary?.trim() || r.summary
    return Nu(`${i}\n\n${a.slice(0, 320)}${a.length > 320 ? `…` : ``}\n\n相关链接：${Mu(t)}`)
  }
  return /联系|咨询|预约|电话|微信|销售|合作|填表|表单/.test(t)
    ? Nu(
        `可以在这里留下需求，我们会尽快联系您：${Z.contact}\n\n也可直接说明您关心的场景（单据识别、标签打印、AI 工作台等），我帮您整理要点。`,
      )
    : /excel|上传|识别.*工具|试.*识别/.test(t)
      ? Nu(`可在此体验 Excel 上传识别：${Z.excelToAi}\n\n完整产品线见：${Z.services}`)
      : /产品|服务|功能|单据|标签|打印|modstore|市场/.test(t) && !/案例/.test(t)
        ? Nu(`${wu(`services`).summary}\n\n详见产品中心：${Z.services}\n\n想深入某一场景可看解决方案：${Z.solutions}`)
        : /方案|制造|贸易|园区|教育|行业|场景/.test(t)
          ? Nu(
              `解决方案覆盖制造贸易、园区服务、教育协同与企业 AI 工作流：${Z.solutions}\n\n• 制造案例 → ${Z.caseManufacture}\n• 园区案例 → ${Z.casePark}\n• 教育案例 → ${Z.caseEdu}`,
            )
          : /制造|生产|库存/.test(t) && /案例|详情/.test(t)
            ? Nu(`制造案例详情：${Z.caseManufacture}\n\n更多案例：${Z.cases}`)
            : /园区/.test(t) && /案例|详情/.test(t)
              ? Nu(`园区案例详情：${Z.casePark}\n\n更多案例：${Z.cases}`)
              : /校园|教育/.test(t) && /案例|详情/.test(t)
                ? Nu(`教育案例详情：${Z.caseEdu}\n\n更多案例：${Z.cases}`)
                : /案例|客户|行业/.test(t)
                  ? Nu(`我们整理了制造、园区、教育等客户案例：${Z.cases}\n\n• ${Z.caseManufacture}\n• ${Z.casePark}\n• ${Z.caseEdu}`)
                  : /新闻|资讯|动态|行业观察/.test(t)
                    ? Nu(`最新新闻与行业观察见：${Z.news}`)
                    : /资质|能力|证照|认证|交付|安全/.test(t)
                      ? Nu(`${wu(`honors`).summary}\n\n详见：${Z.honors}（具体资质以实际公示为准）`)
                      : /市场|登录|注册|会员|工作台|试用/.test(t)
                        ? Nu(`登录 AI 市场可体验完整工作台与数字管家能力：${Z.market}\n\n若尚未注册，可先预约方案沟通：${Z.contact}`)
                        : /价格|报价|费用|多少钱|收费|会员.*价/.test(t)
                          ? Nu(
                              `方案与报价因业务场景而异，请通过「预约方案沟通」提交需求：${Z.contact}\n\n已注册用户也可在 AI 市场查看会员方案：${Z.market.replace(/\/$/, ``)}/plans`,
                            )
                          : /公司|修茈|关于|是谁|介绍/.test(t)
                            ? Nu(`${wu(`about`).summary}\n\n了解更多：${Z.about}`)
                            : /注册|账号|开户/.test(t)
                              ? Nu(`注册 AI 市场账号：${Z.market}register\n\n也可先预约沟通：${Z.contact}`)
                              : null
}
var Iu = [`profile`, `problem`, `workflow`, `contact`, `plan`, `review`]
function Lu() {
  if (typeof window > `u`) return null
  let e = window.XcContactIntake
  return e && typeof e.applyDraft == `function` ? e : null
}
function Ru(e = 4e3) {
  let t = Lu()
  return t
    ? Promise.resolve(t)
    : typeof document > `u`
      ? Promise.resolve(null)
      : new Promise((t) => {
          let n = Date.now(),
            r = () => {
              let i = Lu()
              if (i) {
                t(i)
                return
              }
              if (Date.now() - n >= e) {
                t(null)
                return
              }
              window.setTimeout(r, 80)
            }
          r()
        })
}
function zu(e, t) {
  switch (e) {
    case `profile`:
      return !t.userRole.trim() || !t.roleSummary.trim()
    case `problem`:
      return !t.primaryGoal.trim()
    case `workflow`:
      return !t.manualSteps.trim() || !t.painGoals.trim()
    case `contact`:
      return !t.name.trim() || !t.email.trim()
    case `plan`:
      return !t.timeline.trim() || !t.needIntegration.trim()
    case `review`:
      return !1
    default:
      return !1
  }
}
function Bu(e) {
  for (let t of Iu) if (zu(t, e)) return t
  return `review`
}
function Vu() {
  document.querySelector(`.contact-intake-section`)?.scrollIntoView({ behavior: `smooth`, block: `start` })
}
function Hu(e) {
  let t = Lu()
  if (!t || t.isSubmitted()) return !1
  t.applyDraft(e)
  let n = { ...t.getState(), ...e }
  return (t.goToStep(Bu(n)), Vu(), !0)
}
async function Uu(e, t) {
  let n = await Ru(8e3)
  if (!n) return (Vu(), { ok: !1, message: `问卷尚未就绪，请刷新页面后重试。` })
  if (n.isSubmitted()) return { ok: !1, message: `您已提交过需求问卷，如需修改请通过电话或邮件联系我们。` }
  if (typeof n.runAiAssistFill != `function`) return (Vu(), { ok: !1, message: `预填功能未加载，请强制刷新页面（Cmd+Shift+R）后重试。` })
  let r = e.trim(),
    i = t.trim()
  return !r || !i ? { ok: !1, message: `请填写公司名称和系统 / 业务类型。` } : n.runAiAssistFill({ company: r, system: i })
}
var Wu = `modstore_token`,
  Gu = `modstore_refresh_token`
function Ku() {
  return typeof localStorage > `u` ? null : localStorage
}
function qu() {
  return Ku()?.getItem(`modstore_token`) || ``
}
function Ju() {
  return Ku()?.getItem(`modstore_refresh_token`) || ``
}
function Yu(e) {
  let t = Ku()
  t && (e?.access_token && t.setItem(Wu, e.access_token), e?.refresh_token && t.setItem(Gu, e.refresh_token))
}
function Xu() {
  let e = Ku()
  e && (e.removeItem(Wu), e.removeItem(Gu))
}
var Zu = ``.replace(/\/$/, ``),
  Qu = class extends Error {
    status
    detail
    constructor(e, t, n) {
      ;(super(e), (this.status = t), (this.detail = n), (this.name = `ApiError`))
    }
  }
async function $u(e) {
  let t = await e.text()
  if (!t) return null
  try {
    return JSON.parse(t)
  } catch {
    return { detail: t || e.statusText }
  }
}
function ed(e) {
  let t = e.trim()
  return t.startsWith(`<!`) || /^<html/i.test(t)
}
function td(e, t) {
  let n = e?.message
  if (typeof n == `string` && n.trim()) return n.trim()
  let r = e?.detail
  return Array.isArray(r)
    ? r.map((e) => e.msg || JSON.stringify(e)).join(`; `)
    : typeof r == `string`
      ? ed(r)
        ? /504|Gateway Time-out/i.test(r)
          ? `HTTP 504 Gateway Time-out（网关读超时：长请求请在 nginx 增大 proxy_read_timeout，见 MODstore_deploy/docs/nginx-https-example.conf）`
          : /502|Bad Gateway/i.test(r)
            ? `HTTP 502 Bad Gateway（上游不可用或连接被重置）`
            : t || `网关返回了 HTML 错误页而非 JSON`
        : r
      : r && typeof r == `object`
        ? JSON.stringify(r)
        : t
}
async function nd() {
  let e = Ju()
  if (!e) return null
  let t = await fetch(`${Zu}/api/auth/refresh`, {
      method: `POST`,
      credentials: `include`,
      headers: { 'Content-Type': `application/json` },
      body: JSON.stringify({ refresh_token: e }),
    }),
    n = await $u(t)
  return t.ok ? (Yu(n), n?.access_token || null) : (Xu(), null)
}
var rd = null
function id() {
  if (typeof document > `u`) return null
  for (let e of document.cookie.split(`;`)) {
    let t = e.trim()
    if (t.startsWith(`csrf_token=`))
      try {
        return decodeURIComponent(t.slice(11))
      } catch {
        return t.slice(11)
      }
  }
  return null
}
function ad(e, t) {
  let n = t.toUpperCase()
  if (n === `GET` || n === `HEAD` || n === `OPTIONS` || e.has(`Authorization`) || e.has(`X-CSRF-Token`)) return
  let r = id()
  r && e.set(`X-CSRF-Token`, r)
}
function od() {
  return (
    (rd ||= nd().finally(() => {
      rd = null
    })),
    rd
  )
}
function sd(e) {
  return (
    e.includes(`/api/auth/login`) ||
    e.includes(`/api/auth/register`) ||
    e.includes(`/api/auth/login-with-code`) ||
    e.includes(`/api/auth/refresh`) ||
    e.includes(`/api/auth/send-`)
  )
}
function cd(e, t = {}) {
  let n = (t.method || `GET`).toUpperCase(),
    r = new Headers(t.headers || {}),
    i = qu()
  i && !r.has(`Authorization`) && r.set(`Authorization`, `Bearer ${i}`)
  let a = t.body
  return (
    !(a instanceof FormData) &&
      n !== `GET` &&
      n !== `HEAD` &&
      a !== void 0 &&
      !r.has(`Content-Type`) &&
      r.set(`Content-Type`, `application/json`),
    ad(r, n),
    { method: n, headers: r, body: a }
  )
}
function ld(e, t) {
  let n = e.split(`?`)[0] || e
  return (
    t.status === 401 ||
    (t.status === 403 &&
      (e.includes(`/api/payment`) ||
        e.includes(`/api/wallet`) ||
        e.includes(`/api/refunds`) ||
        e.includes(`/api/admin`) ||
        n === `/api/auth/me`))
  )
}
async function ud(e) {
  if (e.ok) return
  let t
  try {
    t = await e.json()
  } catch {
    try {
      t = await e.text()
    } catch {
      t = null
    }
  }
  throw new Qu(td(t, e.statusText), e.status, t)
}
async function dd(e, t = {}, n = 0) {
  let { timeoutMs: r, ...i } = t,
    { method: a, headers: o, body: s } = cd(e, i),
    c = r && r > 0 ? new AbortController() : null,
    l =
      c == null
        ? null
        : setTimeout(() => {
            c.abort()
          }, r),
    u = c ? (i.signal ? AbortSignal.any([i.signal, c.signal]) : c.signal) : i.signal,
    d
  try {
    d = await fetch(`${Zu}${e}`, {
      ...i,
      method: a,
      headers: o,
      body: s,
      credentials: `include`,
      signal: u,
    })
  } catch (e) {
    throw c?.signal.aborted && e?.name === `AbortError`
      ? new Qu(`请求超时（LLM 生成量化报告可能需 1–3 分钟；若反复超时请检查 API Key 或稍后重试）。`, 408, null)
      : e
  } finally {
    l != null && clearTimeout(l)
  }
  let f = await $u(d),
    p = e.split(`?`)[0] || e
  if (
    (d.status === 401 ||
      (d.status === 403 &&
        (e.includes(`/api/payment`) ||
          e.includes(`/api/wallet`) ||
          e.includes(`/api/refunds`) ||
          e.includes(`/api/admin`) ||
          e.includes(`/api/auth/verify-admin-digest-code`) ||
          p === `/api/auth/me`))) &&
    n === 0 &&
    qu() &&
    !sd(e) &&
    !o.has(`X-Skip-Auth-Refresh`) &&
    (await od())
  )
    return dd(e, t, 1)
  if (!d.ok) {
    let e = td(f, d.statusText)
    throw (
      d.status === 504
        ? (e = `HTTP 504 Gateway Time-out（网关在等待上游响应时超时。工作台 LLM / 基准测试可能需数分钟：请为 location /api/ 设置 proxy_read_timeout 3600s 或更高。）`)
        : d.status === 503
          ? (e = `HTTP 503 Service Unavailable（上游过载或未就绪。请在浏览器 Network 面板确认具体 URL：常见于 /api/llm/status、/api/llm/catalog 或网关到后端的连接。）`)
          : typeof e == `string` && e.length > 600 && (e = `${e.slice(0, 400)}…`),
      new Qu(e, d.status, f)
    )
  }
  return f
}
async function fd(e, t) {
  let n = await fetch(`${Zu}${e}`, t ? { headers: t } : {}),
    r = await n.arrayBuffer()
  if (!n.ok) throw new Qu(n.statusText || `请求失败`, n.status)
  let i = new Uint8Array(r)
  if (r.byteLength < 4 || i[0] !== 80 || i[1] !== 75) throw Error(`响应不是 zip 文件`)
  return new Blob([r], { type: `application/zip` })
}
async function pd(e, t = {}, n = 0) {
  let { method: r, headers: i, body: a } = cd(e, t),
    o = await fetch(`${Zu}${e}`, { ...t, method: r, headers: i, body: a, credentials: `include` })
  return ld(e, o) && n === 0 && qu() && !sd(e) && !i.has(`X-Skip-Auth-Refresh`) && (await od()) ? pd(e, t, 1) : (await ud(o), o.blob())
}
async function md(e, t = {}, n = 0) {
  let { method: r, headers: i, body: a } = cd(e, t),
    o = await fetch(`${Zu}${e}`, { ...t, method: r, headers: i, body: a, credentials: `include` })
  return ld(e, o) && n === 0 && qu() && !sd(e) && !i.has(`X-Skip-Auth-Refresh`) && (await od()) ? md(e, t, 1) : (await ud(o), o)
}
async function hd(e, t = {}, n = 0) {
  let r = await md(e, t, n),
    i = r.body?.getReader()
  if (!i) return r.blob()
  let a = [],
    o = r.headers.get(`content-type`) || `audio/mpeg`
  try {
    for (;;) {
      let { done: e, value: t } = await i.read()
      if (e) break
      t?.byteLength && a.push(t)
    }
  } finally {
    i.releaseLock()
  }
  return new Blob(a, { type: o })
}
var Q = dd
function gd(e) {
  Yu(e)
}
function _d() {
  let e = qu()
  return e ? { Authorization: `Bearer ${e}` } : void 0
}
async function vd(e, t = {}) {
  return Q(e, t)
}
var yd = {
    register: async (e, t, n, r = ``) => {
      let i = await vd(`/api/auth/register`, {
        method: `POST`,
        body: JSON.stringify({ username: e, password: t, email: n, verification_code: r }),
      })
      return (gd(i), i)
    },
    login: async (e, t) => {
      let n = await vd(`/api/auth/login`, {
        method: `POST`,
        body: JSON.stringify({ username: e, password: t }),
      })
      return (gd(n), n)
    },
    loginWithCode: async (e, t) => {
      let n = await vd(`/api/auth/login-with-code`, {
        method: `POST`,
        body: JSON.stringify({ email: e, code: t }),
      })
      return (gd(n), n)
    },
    sendPhoneCode: (e) => Q(`/api/auth/send-phone-code`, { method: `POST`, body: JSON.stringify({ phone: e }) }),
    loginWithPhoneCode: async (e, t) => {
      let n = await vd(`/api/auth/login-with-phone-code`, {
        method: `POST`,
        body: JSON.stringify({ phone: e, code: t }),
      })
      return (gd(n), n)
    },
    me: () => Q(`/api/auth/me`),
    accountBootstrap: () => Q(`/api/account/bootstrap`),
    sendVerificationCode: (e) => Q(`/api/auth/send-code`, { method: `POST`, body: JSON.stringify({ email: e }) }),
    sendRegisterVerificationCode: (e) => Q(`/api/auth/send-register-code`, { method: `POST`, body: JSON.stringify({ email: e }) }),
    sendResetPasswordCode: (e) =>
      Q(`/api/auth/send-reset-password-code`, {
        method: `POST`,
        body: JSON.stringify({ email: e }),
      }),
    resetPassword: (e, t, n) =>
      Q(`/api/auth/reset-password`, {
        method: `POST`,
        body: JSON.stringify({ email: e, code: t, new_password: n }),
      }),
    submitLandingContact: (e) =>
      Q(`/api/public/contact`, {
        method: `POST`,
        body: JSON.stringify({
          name: e.name,
          email: e.email,
          phone: e.phone ?? ``,
          company: e.company ?? ``,
          message: e.message ?? ``,
          source: e.source ?? `home`,
          cs_uid: e.cs_uid ?? void 0,
          cs_t: e.cs_t ?? ``,
        }),
      }),
    updateProfile: (e) => Q(`/api/auth/profile`, { method: `PUT`, body: JSON.stringify({ username: e }) }),
    changePassword: (e, t) =>
      Q(`/api/auth/change-password`, {
        method: `POST`,
        body: JSON.stringify({ current_password: e, new_password: t }),
      }),
    uploadAvatar: (e) => {
      let t = new FormData()
      return (t.append(`file`, e), Q(`/api/auth/avatar`, { method: `POST`, body: t }))
    },
    deleteAvatar: () => Q(`/api/auth/avatar`, { method: `DELETE` }),
    fetchAvatarBlob: (e) => pd(e.startsWith(`/`) ? e : `/${e}`),
  },
  bd = {
    balance: () => Q(`/api/wallet/balance`),
    walletOverview: (e = 20, t = 0) => Q(`/api/wallet/overview?limit=${e}&offset=${t}`),
    walletAdminSelfCredit: (e, t = ``) =>
      Q(`/api/wallet/admin-self-credit`, {
        method: `POST`,
        body: JSON.stringify({ amount: e, description: t }),
      }),
    recharge: (e, t = ``) =>
      Q(`/api/wallet/recharge`, {
        method: `POST`,
        body: JSON.stringify({ amount: e, description: t }),
      }),
    transactions: (e = 50, t = 0) => Q(`/api/wallet/transactions?limit=${e}&offset=${t}`),
  },
  xd = {
    paymentPlans: () => Q(`/api/payment/plans`),
    paymentMyPlan: () => Q(`/api/payment/my-plan`),
    paymentQuery: (e, t) => {
      let n = t?.reconcile ? `?reconcile=true` : ``
      return Q(`/api/payment/query/${encodeURIComponent(e)}${n}`)
    },
    paymentOrders: (e = ``, t = 50, n = 0) => {
      let r = new URLSearchParams({ limit: String(t), offset: String(n) })
      return (e && r.set(`status`, e), Q(`/api/payment/orders?${r}`))
    },
    paymentDismissNonActiveOrders: () => Q(`/api/payment/orders/dismiss-non-active`, { method: `POST`, body: `{}` }),
    paymentCancelOrder: (e) => Q(`/api/payment/cancel/${encodeURIComponent(e)}`, { method: `POST`, body: `{}` }),
    paymentDiagnostics: () => Q(`/api/payment/diagnostics`),
    paymentEntitlements: () => Q(`/api/payment/entitlements`),
    paymentCheckout: async (e) => {
      let t = await Q(`/api/payment/sign-checkout`, {
          method: `POST`,
          body: JSON.stringify({
            plan_id: e?.plan_id ?? ``,
            item_id: Number(e?.item_id ?? 0) || 0,
            total_amount: Number(e?.total_amount ?? 0) || 0,
            subject: e?.subject ?? ``,
            wallet_recharge: !!e?.wallet_recharge,
          }),
        }),
        n = {
          plan_id: t.plan_id ?? ``,
          item_id: t.item_id ?? 0,
          total_amount: t.total_amount ?? 0,
          subject: t.subject ?? ``,
          wallet_recharge: !!t.wallet_recharge,
          request_id: t.request_id,
          timestamp: t.timestamp,
          signature: t.signature,
        }
      ;(e?.pay_channel && (n.pay_channel = e.pay_channel), e?.pay_type && (n.pay_type = e.pay_type))
      let r = await Q(`/api/payment/checkout`, { method: `POST`, body: JSON.stringify(n) })
      if (r?.ok === !1) return r
      if (r?.ok !== !0) throw Error(`支付下单返回异常：缺少成功标识`)
      let i = String(r.type || ``).trim()
      if (!i) throw Error(`支付下单返回异常：缺少支付类型`)
      if (i === `page` || i === `wap`) {
        let e = r.redirect_url
        if (!e || String(e).trim() === ``) throw Error(`支付下单返回异常：缺少跳转地址`)
      }
      if (i === `precreate` || i === `wechat_native`) {
        let e = r.order_id
        if (!e || String(e).trim() === ``) throw Error(`支付下单返回异常：缺少订单号`)
      }
      return r
    },
  },
  Sd = {
    refundsApply: async (e, t) => {
      let n = await Q(`/api/refunds/apply`, {
        method: `POST`,
        body: JSON.stringify({ order_no: e, reason: t }),
      })
      if (n?.ok === !1) throw Error(n.message || `退款申请失败`)
      return n
    },
    refundsMy: () => Q(`/api/refunds/my`),
    refundsAdminPending: () => Q(`/api/refunds/admin/pending`),
    refundsAdminReview: (e, t, n = ``) =>
      Q(`/api/refunds/admin/${encodeURIComponent(String(e))}/review`, {
        method: `POST`,
        body: JSON.stringify({ action: t, admin_note: n }),
      }),
  },
  Cd = {
    catalog: (e = ``, t = ``, n = 50, r = 0, i = ``, a = ``, o = ``, s = ``, c = !1, l = ``) => {
      let u = new URLSearchParams({ limit: String(n), offset: String(r) })
      return (
        e && u.set(`q`, e),
        t && u.set(`artifact`, t),
        i && u.set(`industry`, i),
        a && u.set(`security_level`, a),
        o && u.set(`material_category`, o),
        s && u.set(`license_scope`, s),
        l && u.set(`collection`, l),
        c && u.set(`_cb`, String(Date.now())),
        Q(`/api/market/catalog?${u}`)
      )
    },
    downloadOfficeEmployeePack: async () => {
      let e = await fd(`/api/market/catalog/office-employee-pack/bundle`, _d()),
        t = URL.createObjectURL(e),
        n = document.createElement(`a`)
      ;((n.href = t),
        (n.download = `office-employee-pack.zip`),
        (n.style.display = `none`),
        document.body.appendChild(n),
        n.click(),
        n.remove(),
        window.setTimeout(() => URL.revokeObjectURL(t), 6e4))
    },
    downloadWorkflowEmployeePack: async () => {
      let e = await fd(`/api/market/catalog/workflow-employee-pack/bundle`, _d()),
        t = URL.createObjectURL(e),
        n = document.createElement(`a`)
      ;((n.href = t),
        (n.download = `workflow-employee-pack.zip`),
        (n.style.display = `none`),
        document.body.appendChild(n),
        n.click(),
        n.remove(),
        window.setTimeout(() => URL.revokeObjectURL(t), 6e4))
    },
    downloadHostFoundationEmployeePack: async () => {
      let e = await fd(`/api/market/catalog/host-foundation-employee-pack/download`, _d()),
        t = URL.createObjectURL(e),
        n = document.createElement(`a`)
      ;((n.href = t),
        (n.download = `xcagi-host-foundation-employee.xcemp`),
        (n.style.display = `none`),
        document.body.appendChild(n),
        n.click(),
        n.remove(),
        window.setTimeout(() => URL.revokeObjectURL(t), 6e4))
    },
    catalogFacets: () => Q(`/api/market/facets`),
    catalogDetail: (e) => Q(`/api/market/catalog/${encodeURIComponent(String(e))}`),
    catalogQuality: (e, t = !1) => {
      let n = typeof t == `boolean` ? { refresh: t } : t,
        r = new URLSearchParams()
      ;(n.refresh && r.set(`refresh`, `1`), n.llm && r.set(`llm`, `1`))
      let i = r.toString()
      return Q(`/api/market/catalog/${encodeURIComponent(String(e))}/quality${i ? `?${i}` : ``}`)
    },
    catalogReviews: (e) => Q(`/api/market/catalog/${encodeURIComponent(String(e))}/reviews`),
    catalogSubmitReview: (e, t, n = ``) =>
      Q(`/api/market/catalog/${encodeURIComponent(String(e))}/review`, {
        method: `POST`,
        body: JSON.stringify({ rating: t, content: n }),
      }),
    catalogSubmitComplaint: (e, t, n, r = {}) =>
      Q(`/api/market/catalog/${encodeURIComponent(String(e))}/complaints`, {
        method: `POST`,
        body: JSON.stringify({ complaint_type: t, reason: n, evidence: r }),
      }),
    catalogToggleFavorite: (e) =>
      Q(`/api/market/catalog/${encodeURIComponent(String(e))}/favorite`, {
        method: `POST`,
        body: `{}`,
      }),
    buyItem: (e) => Q(`/api/market/catalog/${encodeURIComponent(String(e))}/buy`, { method: `POST` }),
    downloadItem: async (e) => {
      let t = await fd(`/api/market/catalog/${encodeURIComponent(String(e))}/download`, _d()),
        n = URL.createObjectURL(t),
        r = document.createElement(`a`)
      ;((r.href = n),
        (r.download = `mod-${e}.zip`),
        (r.style.display = `none`),
        document.body.appendChild(r),
        r.click(),
        r.remove(),
        window.setTimeout(() => URL.revokeObjectURL(n), 6e4))
    },
    myStore: (e = 50, t = 0) => Q(`/api/my-store?limit=${e}&offset=${t}`),
  },
  wd = {
    adminStatus: () => Q(`/api/admin/status`),
    adminResearchSettings: () => Q(`/api/admin/research-settings`),
    adminSaveResearchSettings: (e) => Q(`/api/admin/research-settings`, { method: `PUT`, body: JSON.stringify(e || {}) }),
    adminVectorSettings: () => Q(`/api/admin/vector-settings`),
    adminSaveVectorSettings: (e) => Q(`/api/admin/vector-settings`, { method: `PUT`, body: JSON.stringify(e || {}) }),
    adminUpload: (e) => Q(`/api/admin/catalog`, { method: `POST`, body: e }),
    adminListCatalog: (e = 200, t = 0) => Q(`/api/admin/catalog?limit=${e}&offset=${t}`),
    adminDeleteCatalog: (e) => Q(`/api/admin/catalog/${encodeURIComponent(String(e))}`, { method: `DELETE` }),
    adminDeleteEmployeePack: (e) => Q(`/api/admin/employee-packs/${encodeURIComponent(e)}`, { method: `DELETE` }),
    adminPurgeAllEmployeePacks: () => Q(`/api/admin/employee-packs/purge-all`, { method: `POST` }),
    adminAlignEmployeeLlmFromDeepseek: (e = !1) =>
      Q(`/api/admin/employee-packs/align-llm-from-deepseek?dry_run=${e ? `true` : `false`}`, {
        method: `POST`,
      }),
    adminAlignEmployeeLlmToAuto: (e = !1) =>
      Q(`/api/admin/employee-packs/align-llm-to-auto?dry_run=${e ? `true` : `false`}`, {
        method: `POST`,
      }),
    adminAlignSingleEmployeeLlmToAuto: (e, t = !1) =>
      Q(`/api/admin/employee-packs/${encodeURIComponent(e)}/align-llm-to-auto-single?dry_run=${t ? `true` : `false`}`, { method: `POST` }),
    adminListNoKeyEmployees: () => Q(`/api/admin/duty-graph/no-key-employees`),
    verifyAdminDigestCode: (e) =>
      Q(`/api/auth/verify-admin-digest-code`, {
        method: `POST`,
        body: JSON.stringify({ code: e }),
      }),
    adminOpsSshHint: () => Q(`/api/admin/ops-ssh-hint`),
    adminOpsAuditLogs: (e) => {
      let t = new URLSearchParams()
      ;(e?.employee_id && t.set(`employee_id`, e.employee_id), e?.limit != null && t.set(`limit`, String(e.limit)))
      let n = t.toString()
      return Q(`/api/admin/ops/audit${n ? `?${n}` : ``}`)
    },
    adminOpsStagedChanges: (e) => {
      let t = new URLSearchParams()
      ;(e?.status && t.set(`status`, e.status), e?.limit != null && t.set(`limit`, String(e.limit)))
      let n = t.toString()
      return Q(`/api/admin/ops/staged-changes${n ? `?${n}` : ``}`)
    },
    adminOpsApprovalTokens: (e) => {
      let t = new URLSearchParams()
      e?.limit != null && t.set(`limit`, String(e.limit))
      let n = t.toString()
      return Q(`/api/admin/ops/approval-tokens${n ? `?${n}` : ``}`)
    },
    adminEmployeeExecutionMetrics: (e, t) => {
      let n = new URLSearchParams()
      ;(t?.limit != null && n.set(`limit`, String(t.limit)),
        t?.offset != null && n.set(`offset`, String(t.offset)),
        t?.user_id != null && n.set(`user_id`, String(t.user_id)))
      let r = n.toString()
      return Q(`/api/admin/employees/${encodeURIComponent(e)}/execution-metrics${r ? `?${r}` : ``}`)
    },
    adminEmployeeExecutionCapability: (e) => Q(`/api/admin/employees/${encodeURIComponent(e)}/execution-capability`),
    adminEmployeeExecutionCapabilities: (e) =>
      Q(`/api/admin/employees/execution-capabilities`, {
        method: `POST`,
        body: JSON.stringify({ employee_ids: Array.isArray(e) ? e : [] }),
      }),
    adminDutyGraphRunStart: (e) => Q(`/api/admin/duty-graph/runs`, { method: `POST`, body: JSON.stringify(e || {}) }),
    adminDutyGraphRunDetail: (e) => Q(`/api/admin/duty-graph/runs/${encodeURIComponent(String(e))}`),
    adminDutyGraphHealth: () => Q(`/api/admin/duty-graph/health`),
    adminEmployeeAutonomyDashboard: (e = 30) => Q(`/api/admin/employee-autonomy/dashboard?limit_recent=${encodeURIComponent(String(e))}`),
    adminEmployeeSuggestions: (e) => {
      let t = new URLSearchParams()
      ;(e?.status && t.set(`status`, e.status),
        e?.risk_level && t.set(`risk_level`, e.risk_level),
        e?.limit != null && t.set(`limit`, String(e.limit)),
        e?.offset != null && t.set(`offset`, String(e.offset)))
      let n = t.toString()
      return Q(`/api/admin/employee-autonomy/suggestions${n ? `?${n}` : ``}`)
    },
    adminEmployeeSuggestionApprove: (e, t = !0) =>
      Q(`/api/admin/employee-autonomy/suggestions/${encodeURIComponent(String(e))}/approve`, {
        method: `POST`,
        body: JSON.stringify({ dispatch_now: t }),
      }),
    adminEmployeeSuggestionReject: (e, t = ``) =>
      Q(`/api/admin/employee-autonomy/suggestions/${encodeURIComponent(String(e))}/reject`, {
        method: `POST`,
        body: JSON.stringify({ reason: t }),
      }),
    adminEmployeeSuggestionBatchReview: (e) =>
      Q(`/api/admin/employee-autonomy/suggestions/batch-review`, {
        method: `POST`,
        body: JSON.stringify(e || {}),
      }),
    adminEmployeeBriefTasks: (e) => {
      let t = new URLSearchParams()
      ;(e?.status && t.set(`status`, e.status), e?.limit != null && t.set(`limit`, String(e.limit)))
      let n = t.toString()
      return Q(`/api/admin/employee-autonomy/brief-tasks${n ? `?${n}` : ``}`)
    },
    adminEmployeeDispatchBriefTasks: (e = 20) =>
      Q(`/api/admin/employee-autonomy/dispatch/brief-tasks`, {
        method: `POST`,
        body: JSON.stringify({ limit: e }),
      }),
    adminEmployeeDispatchSuggestions: (e = 20) =>
      Q(`/api/admin/employee-autonomy/dispatch/suggestions`, {
        method: `POST`,
        body: JSON.stringify({ limit: e }),
      }),
    adminEmployeeEvolutionScan: (e) =>
      Q(`/api/admin/employee-autonomy/evolution/scan`, {
        method: `POST`,
        body: JSON.stringify(e || {}),
      }),
    adminEmployeeCollabThreads: (e) => {
      let t = new URLSearchParams()
      ;(e?.status && t.set(`status`, e.status), e?.limit != null && t.set(`limit`, String(e.limit)))
      let n = t.toString()
      return Q(`/api/admin/employee-autonomy/collab/threads${n ? `?${n}` : ``}`)
    },
    adminEmployeeCreateCollabThread: (e) =>
      Q(`/api/admin/employee-autonomy/collab/threads`, {
        method: `POST`,
        body: JSON.stringify(e || {}),
      }),
    adminEmployeeCollabMessages: (e, t = 100) =>
      Q(`/api/admin/employee-autonomy/collab/threads/${encodeURIComponent(String(e))}/messages?limit=${encodeURIComponent(String(t))}`),
    adminEmployeePostCollabMessage: (e, t) =>
      Q(`/api/admin/employee-autonomy/collab/threads/${encodeURIComponent(String(e))}/messages`, {
        method: `POST`,
        body: JSON.stringify(t || {}),
      }),
    opsOrchestrateAsync: (e) =>
      Q(`/api/ops/orchestrate/async`, {
        method: `POST`,
        body: JSON.stringify({
          use_task_router: !0,
          max_concurrency: 2,
          allow_high_risk_real_run: !1,
          ...e,
        }),
      }),
    opsOrchestrateJob: (e) => Q(`/api/ops/orchestrate/jobs/${encodeURIComponent(e)}`),
    opsOrchestrateJobs: (e = 20) => Q(`/api/ops/orchestrate/jobs?limit=${encodeURIComponent(String(e))}`),
    adminChangeRequestsList: (e) => {
      let t = new URLSearchParams()
      ;(e?.status && t.set(`status`, e.status), e?.limit != null && t.set(`limit`, String(e.limit)))
      let n = t.toString()
      return Q(`/api/admin/change-requests${n ? `?${n}` : ``}`)
    },
    adminChangeRequestDetail: (e) => Q(`/api/admin/change-requests/${encodeURIComponent(String(e))}`),
    adminChangeRequestApprove: (e) => Q(`/api/admin/change-requests/${encodeURIComponent(String(e))}/approve`, { method: `POST` }),
    adminChangeRequestReject: (e, t) =>
      Q(`/api/admin/change-requests/${encodeURIComponent(String(e))}/reject`, {
        method: `POST`,
        body: JSON.stringify(t || {}),
      }),
    adminListAiAccounts: (e = {}) => {
      let t = new URLSearchParams()
      ;(e.platform && t.set(`platform`, e.platform),
        e.employee_id && t.set(`employee_id`, e.employee_id),
        e.status && t.set(`status`, e.status),
        e.limit != null && t.set(`limit`, String(e.limit)),
        e.offset != null && t.set(`offset`, String(e.offset)))
      let n = t.toString()
      return Q(`/api/admin/ai-accounts${n ? `?${n}` : ``}`)
    },
    adminCreateAiAccount: (e) => Q(`/api/admin/ai-accounts`, { method: `POST`, body: JSON.stringify(e) }),
    adminUpdateAiAccount: (e, t) =>
      Q(`/api/admin/ai-accounts/${encodeURIComponent(String(e))}`, {
        method: `PATCH`,
        body: JSON.stringify(t),
      }),
    adminRotateAiAccountSecret: (e, t) =>
      Q(`/api/admin/ai-accounts/${encodeURIComponent(String(e))}/rotate`, {
        method: `POST`,
        body: JSON.stringify({ secret: t }),
      }),
    adminDeleteAiAccount: (e) => Q(`/api/admin/ai-accounts/${encodeURIComponent(String(e))}`, { method: `DELETE` }),
    butlerQqStatus: () => Q(`/api/agent/butler/qq/status`),
    adminYuangonOnboardStatus: () => Q(`/api/admin/yuangon-onboard/status`),
    adminYuangonOnboardRun: (e) => Q(`/api/admin/yuangon-onboard/run`, { method: `POST`, body: JSON.stringify(e || {}) }),
    adminPurgeAllMods: () => Q(`/api/admin/mods/purge-all`, { method: `POST` }),
    adminListCatalogComplaints: (e = ``, t = 50, n = 0) => {
      let r = new URLSearchParams({ limit: String(t), offset: String(n) })
      return (e && r.set(`status`, e), Q(`/api/admin/catalog/complaints?${r}`))
    },
    adminReviewCatalogComplaint: (e, t, n = ``, r = {}) =>
      Q(`/api/admin/catalog/complaints/${encodeURIComponent(String(e))}/review`, {
        method: `POST`,
        body: JSON.stringify({ action: t, admin_note: n, ...r }),
      }),
    adminListUsers: (e = 200, t = 0, n) => {
      let r = new URLSearchParams({ limit: String(e), offset: String(t) })
      return (n === !0 ? r.set(`is_enterprise`, `true`) : n === !1 && r.set(`is_enterprise`, `false`), Q(`/api/admin/users?${r}`))
    },
    adminSetUserAdmin: (e, t) => Q(`/api/admin/users/${e}/admin?is_admin=${t}`, { method: `PUT` }),
    adminSetUserEnterprise: (e, t) => Q(`/api/admin/users/${e}/enterprise?is_enterprise=${t}`, { method: `PUT` }),
    adminEnterpriseAssignableMods: () => Q(`/api/admin/enterprise/assignable-mods`),
    adminListUserMods: (e) => Q(`/api/admin/users/${encodeURIComponent(String(e))}/mods`),
    adminBindUserMod: (e, t) =>
      Q(`/api/admin/users/${encodeURIComponent(String(e))}/mods/${encodeURIComponent(t)}`, {
        method: `POST`,
      }),
    adminUnbindUserMod: (e, t) =>
      Q(`/api/admin/users/${encodeURIComponent(String(e))}/mods/${encodeURIComponent(t)}`, {
        method: `DELETE`,
      }),
    adminListWallets: (e = 200, t = 0) => Q(`/api/admin/wallets?limit=${e}&offset=${t}`),
    adminListTransactions: (e = 200, t = 0) => Q(`/api/admin/transactions?limit=${e}&offset=${t}`),
  },
  Td = {
    listMods: (e = !1) => Q(`/api/mods${e ? `?_=${Date.now()}` : ``}`),
    deleteMod: (e) => Q(`/api/mods/${encodeURIComponent(e)}`, { method: `DELETE` }),
    createMod: (e, t, n = `通用`) =>
      Q(`/api/mods/create`, {
        method: `POST`,
        body: JSON.stringify({ mod_id: e, display_name: t, industry_id: n }),
      }),
    importZIP: (e, t = !0) => {
      let n = new FormData()
      return (n.append(`file`, e), Q(`/api/mods/import?replace=${t}`, { method: `POST`, body: n }))
    },
    modAiScaffold: (e, t = ``, n = !0, r = `通用`, i, a) =>
      Q(`/api/mods/ai-scaffold`, {
        method: `POST`,
        body: JSON.stringify({
          brief: e,
          suggested_id: t || void 0,
          replace: n,
          industry_id: r || `通用`,
          provider: i,
          model: a,
        }),
      }),
    push: (e = null) => Q(`/api/sync/push`, { method: `POST`, body: JSON.stringify({ mod_ids: e }) }),
    pull: (e = null) => Q(`/api/sync/pull`, { method: `POST`, body: JSON.stringify({ mod_ids: e }) }),
    getRepoConfig: () => Q(`/api/config`),
    putRepoConfig: (e) => Q(`/api/config`, { method: `PUT`, body: JSON.stringify(e || {}) }),
    getMod: (e) => Q(`/api/mods/${encodeURIComponent(e)}`),
    putModManifest: (e, t) =>
      Q(`/api/mods/${encodeURIComponent(e)}/manifest`, {
        method: `PUT`,
        body: JSON.stringify({ manifest: t }),
      }),
    getModFile: (e, t) => Q(`/api/mods/${encodeURIComponent(e)}/file?path=${encodeURIComponent(t)}`),
    putModFile: (e, t, n) =>
      Q(`/api/mods/${encodeURIComponent(e)}/file`, {
        method: `PUT`,
        body: JSON.stringify({ path: t, content: n }),
      }),
    regenerateModFrontend: (e, t = ``) =>
      Q(`/api/mods/${encodeURIComponent(e)}/frontend/regenerate`, {
        method: `POST`,
        body: JSON.stringify({ brief: t }),
      }),
    listModSnapshots: (e) => Q(`/api/mods/${encodeURIComponent(e)}/snapshots`),
    captureModSnapshot: (e, t = ``) =>
      Q(`/api/mods/${encodeURIComponent(e)}/snapshots`, {
        method: `POST`,
        body: JSON.stringify({ label: t }),
      }),
    restoreModSnapshot: (e, t) =>
      Q(`/api/mods/${encodeURIComponent(e)}/snapshots/${encodeURIComponent(t)}/restore`, {
        method: `POST`,
        body: `{}`,
      }),
    bumpModManifestPatchVersion: (e) =>
      Q(`/api/mods/${encodeURIComponent(e)}/manifest/bump-patch-version`, {
        method: `POST`,
        body: `{}`,
      }),
    modWorkflowLink: (e, t) =>
      Q(`/api/mods/${encodeURIComponent(e)}/workflow-link`, {
        method: `POST`,
        body: JSON.stringify(t),
      }),
    scaffoldWorkflowEmployee: (e, t) =>
      Q(`/api/mods/${encodeURIComponent(e)}/workflow-employees/scaffold`, {
        method: `POST`,
        body: JSON.stringify(t),
      }),
    getModAuthoringSummary: (e) => Q(`/api/mods/${encodeURIComponent(e)}/authoring-summary`),
    getModBlueprintRoutes: (e) => Q(`/api/mods/${encodeURIComponent(e)}/blueprint-routes`),
    getAuthoringExtensionSurface: (e = !1) => Q(`/api/authoring/extension-surface?merge_host=${e ? `true` : `false`}`),
    exportEmployeePackZip: async (e, t = 0) => {
      let n = String(e || ``).trim(),
        r = Number.parseInt(String(t ?? 0), 10),
        i = `workflow_index=${Number.isFinite(r) && r >= 0 ? r : 0}`,
        a = _d(),
        o = [
          `/api/mods/${encodeURIComponent(n)}/export-employee-pack?${i}`,
          `/api/mods/${encodeURIComponent(n)}/export_employee_pack?${i}`,
        ],
        s = (e) => {
          let t = String(e || ``).trim()
          if (/mod\s*不存在|Mod 不存在/i.test(t)) return !1
          if (/^not found$/i.test(t) || t === `{"detail":"Not Found"}`) return !0
          try {
            let e = JSON.parse(t)?.detail
            if (e === `Not Found` || (Array.isArray(e) && e.some((e) => String(e?.msg || ``).toLowerCase() === `not found`))) return !0
          } catch {}
          return !1
        },
        c
      for (let e = 0; e < o.length; e++)
        try {
          return await fd(o[e], a)
        } catch (t) {
          if (((c = t), s(String(t?.message || ``).trim()) && e === 0)) continue
          break
        }
      let l = String(c?.message || `导出失败`).trim()
      throw s(l)
        ? Error(
            `${l} — 8765 上的 API 进程里若没有该路由，会返回 Not Found。请完全退出旧进程后重启：在 MODstore_deploy 目录执行 start-modstore.bat / restart.bat，或手动运行 python -m modstore_server。自检：打开 http://127.0.0.1:8765/docs 搜索「export-employee-pack」，搜不到即仍是旧代码。`,
          )
        : c instanceof Error
          ? c
          : Error(l)
    },
    exportModZip: (e) => fd(`/api/mods/${encodeURIComponent(e)}/export`, _d()),
  },
  Ed = {
    auditPackage: (e, t = null) => {
      let n = new FormData()
      return (
        n.append(`file`, e),
        t != null && n.append(`metadata`, JSON.stringify(t)),
        Q(`/api/package-audit`, { method: `POST`, body: n })
      )
    },
    listV1Packages: (e = ``, t = ``, n = 50, r = 0, i = !1) => {
      let a = new URLSearchParams({ limit: String(n), offset: String(r) })
      return (e && a.set(`artifact`, e), t && a.set(`q`, t), i && a.set(`_`, String(Date.now())), Q(`/v1/packages?${a}`))
    },
    listCatalogPackageVersions: (e) => Q(`/v1/packages/by-id/${encodeURIComponent(e)}/versions`),
    promoteCatalogPackage: (e, t) =>
      Q(`/v1/packages/${encodeURIComponent(e)}/promote`, {
        method: `POST`,
        body: JSON.stringify({ from_version: t }),
        headers: void 0,
      }),
    downloadCatalogPackageBlob: (e, t) => fd(`/v1/packages/${encodeURIComponent(e)}/${encodeURIComponent(t)}/download`),
    uploadPackage: (e, t) => {
      let n = new FormData()
      return (n.append(`metadata`, JSON.stringify(e)), n.append(`file`, t), Q(`/v1/packages`, { method: `POST`, body: n, headers: void 0 }))
    },
    registerWorkflowEmployeeCatalog: (e, t = 0, n = {}) =>
      Q(`/api/mods/${encodeURIComponent(e)}/register-workflow-employee-catalog`, {
        method: `POST`,
        body: JSON.stringify({
          workflow_index: t,
          industry: n.industry || `通用`,
          price: n.price ?? 0,
          release_channel: n.release_channel || `stable`,
        }),
      }),
    patchModWorkflowEmployeeNodes: (e) => Q(`/api/mods/${encodeURIComponent(e)}/patch-workflow-employee-nodes`, { method: `POST` }),
    runWorkflowEmployeeClosure: (e, t = {}) =>
      Q(`/api/mods/${encodeURIComponent(e)}/workflow-employee-closure`, {
        method: `POST`,
        body: JSON.stringify({
          register_missing: t.register_missing !== !1,
          patch_canvas: t.patch_canvas !== !1,
          industry: t.industry || `通用`,
        }),
      }),
  },
  Dd = {
    employeeBenchTest: (e, t, n) =>
      Q(`/api/workbench/employee-bench-test`, {
        method: `POST`,
        body: JSON.stringify({ employee_id: e, provider: t || null, model: n || null }),
      }),
    employeePublish: (e, t) =>
      Q(`/api/workbench/employee-publish`, {
        method: `POST`,
        body: JSON.stringify({ employee_id: e, ...(t || {}) }),
      }),
    employeeSaveManifest: (e, t, n) =>
      Q(`/api/workbench/employee-save`, {
        method: `POST`,
        body: JSON.stringify({
          manifest: e,
          employee_id: t || null,
          provider: n?.provider || null,
          model: n?.model || null,
          register_skills: n?.registerSkills !== !1,
        }),
      }),
    employeeExportZip: async (e, t, n) => {
      let r = _d() || {}
      r[`Content-Type`] = `application/json`
      let i = await fetch(`/api/workbench/employee-export`, {
        method: `POST`,
        headers: r,
        body: JSON.stringify({
          manifest: e,
          employee_id: t || null,
          standalone: n?.standalone === !0,
        }),
      })
      if (!i.ok) {
        let e = await i.json().catch(() => ({}))
        throw Error(String(e?.detail || e?.error || `HTTP ${i.status}`))
      }
      return i.blob()
    },
    employeeSyncTest: (e, t, n, r) =>
      Q(`/api/workbench/employee-sync-test`, {
        method: `POST`,
        body: JSON.stringify({
          employee_id: e,
          fhd_base_url: t || null,
          provider: n || null,
          model: r || null,
        }),
      }),
  },
  Od = {
    listScriptWorkflows: (e = ``) => Q(`/api/script-workflows${e ? `?status=${encodeURIComponent(e)}` : ``}`),
    getScriptWorkflow: (e) => Q(`/api/script-workflows/${e}`),
    updateScriptWorkflow: (e, t) => Q(`/api/script-workflows/${e}`, { method: `PUT`, body: JSON.stringify(t) }),
    deleteScriptWorkflow: (e) => Q(`/api/script-workflows/${e}`, { method: `DELETE` }),
    sandboxRunScriptWorkflow: (e, t) => {
      let n = new FormData()
      return (t.forEach((e) => n.append(`files`, e)), Q(`/api/script-workflows/${e}/sandbox-run`, { method: `POST`, body: n }))
    },
    runScriptWorkflow: (e, t) => {
      let n = new FormData()
      return (t.forEach((e) => n.append(`files`, e)), Q(`/api/script-workflows/${e}/run`, { method: `POST`, body: n }))
    },
    activateScriptWorkflow: (e) => Q(`/api/script-workflows/${e}/activate`, { method: `POST` }),
    deactivateScriptWorkflow: (e) => Q(`/api/script-workflows/${e}/deactivate`, { method: `POST` }),
    listScriptWorkflowRuns: (e, t = ``) => Q(`/api/script-workflows/${e}/runs${t ? `?mode=${encodeURIComponent(t)}` : ``}`),
    downloadScriptWorkflowRunFile: async (e, t, n) => {
      let r = await fetch(
        `/api/script-workflows/${encodeURIComponent(String(e))}/runs/${encodeURIComponent(String(t))}/files/${encodeURIComponent(n)}`,
        { headers: _d() },
      )
      if (!r.ok) throw Error(r.statusText || `下载失败`)
      return r.blob()
    },
    listScriptWorkflowVersions: (e) => Q(`/api/script-workflows/${e}/versions`),
    commitScriptWorkflowSession: (e, t) =>
      Q(`/api/script-workflows/sessions/${encodeURIComponent(e)}/commit`, {
        method: `POST`,
        body: JSON.stringify(t),
      }),
    getScriptWorkflowSession: (e) => Q(`/api/script-workflows/sessions/${encodeURIComponent(e)}`),
  },
  kd = {
    listWorkflows: () => Q(`/api/workflow/`),
    listESkills: () => Q(`/api/eskills`),
    createESkill: (e) => Q(`/api/eskills`, { method: `POST`, body: JSON.stringify(e || {}) }),
    runESkill: (e, t) => Q(`/api/eskills/${e}/run`, { method: `POST`, body: JSON.stringify(t || {}) }),
    listEmployeeEligibleWorkflows: () => Q(`/api/workflow/employee-eligible`),
    listWorkflowsByEmployee: (e) => Q(`/api/workflow/by-employee?employee_id=${encodeURIComponent(e)}`),
    getWorkflow: (e) => Q(`/api/workflow/${e}`),
    createWorkflow: (e, t) => Q(`/api/workflow/`, { method: `POST`, body: JSON.stringify({ name: e, description: t }) }),
    updateWorkflow: (e, t, n, r) =>
      Q(`/api/workflow/${e}`, {
        method: `PUT`,
        body: JSON.stringify({ name: t, description: n, is_active: r }),
      }),
    deleteWorkflow: (e) => Q(`/api/workflow/${e}`, { method: `DELETE` }),
    addWorkflowNode: (e, t, n, r, i, a) =>
      Q(`/api/workflow/${e}/nodes`, {
        method: `POST`,
        body: JSON.stringify({ node_type: t, name: n, config: r, position_x: i, position_y: a }),
      }),
    updateWorkflowNode: (e, t, n, r, i) =>
      Q(`/api/workflow/nodes/${e}`, {
        method: `PUT`,
        body: JSON.stringify({ name: t, config: n, position_x: r, position_y: i }),
      }),
    deleteWorkflowNode: (e) => Q(`/api/workflow/nodes/${e}`, { method: `DELETE` }),
    addWorkflowEdge: (e, t, n, r = ``) =>
      Q(`/api/workflow/${e}/edges`, {
        method: `POST`,
        body: JSON.stringify({ source_node_id: t, target_node_id: n, condition: r }),
      }),
    deleteWorkflowEdge: (e) => Q(`/api/workflow/edges/${e}`, { method: `DELETE` }),
    executeWorkflow: (e, t = {}) => Q(`/api/workflow/${e}/execute`, { method: `POST`, body: JSON.stringify({ input_data: t }) }),
    workflowValidate: (e) => Q(`/api/workflow/${e}/validate`),
    workflowSandboxRun: (e, t) => Q(`/api/workflow/${e}/sandbox-run`, { method: `POST`, body: JSON.stringify(t || {}) }),
    listWorkflowExecutions: (e, t = 50, n = 0) => Q(`/api/workflow/${e}/executions?limit=${t}&offset=${n}`),
    listWorkflowTriggers: (e) => Q(`/api/workflow/${e}/triggers`),
    createWorkflowTrigger: (e, t) => Q(`/api/workflow/${e}/triggers`, { method: `POST`, body: JSON.stringify(t || {}) }),
    deleteWorkflowTrigger: (e, t) => Q(`/api/workflow/${e}/triggers/${t}`, { method: `DELETE` }),
    workflowWebhookRun: (e, t = {}) => Q(`/api/workflow/${e}/webhook-run`, { method: `POST`, body: JSON.stringify(t) }),
    publishWorkflowVersion: (e, t = ``) =>
      Q(`/api/workflow/${e}/versions/publish`, {
        method: `POST`,
        body: JSON.stringify({ note: t }),
      }),
    listWorkflowVersions: (e, t = 50, n = 0) => Q(`/api/workflow/${e}/versions?limit=${t}&offset=${n}`),
    getWorkflowVersion: (e, t) => Q(`/api/workflow/${e}/versions/${t}`),
    rollbackWorkflowVersion: (e, t) => Q(`/api/workflow/${e}/versions/${t}/rollback`, { method: `POST` }),
    getExecution: (e) => Q(`/api/workflow/executions/${e}`),
  },
  Ad = {
    developerListTokens: () => Q(`/api/developer/tokens`),
    developerCreateToken: (e, t = [], n = null) =>
      Q(`/api/developer/tokens`, {
        method: `POST`,
        body: JSON.stringify({ name: e, scopes: t, expires_days: n }),
      }),
    developerRevokeToken: (e) => Q(`/api/developer/tokens/${e}`, { method: `DELETE` }),
    developerExportKeyBundle: (e) =>
      Q(`/api/developer/key-export/bundle`, {
        method: `POST`,
        body: JSON.stringify({
          recipient_public_key_spki_b64: e.recipient_public_key_spki_b64,
          current_password: e.current_password,
          token_ids: e.token_ids,
          rotate_source_tokens: e.rotate_source_tokens !== !1,
        }),
      }),
    developerListKeyExportAudit: (e = 50) => Q(`/api/developer/key-export/audit?limit=${encodeURIComponent(String(e))}`),
    developerWebhookEventCatalog: () => Q(`/api/developer/webhooks/event-catalog`),
    developerListWebhooks: () => Q(`/api/developer/webhooks`),
    developerCreateWebhook: (e) => Q(`/api/developer/webhooks`, { method: `POST`, body: JSON.stringify(e) }),
    developerUpdateWebhook: (e, t) => Q(`/api/developer/webhooks/${e}`, { method: `PUT`, body: JSON.stringify(t) }),
    developerDeleteWebhook: (e) => Q(`/api/developer/webhooks/${e}`, { method: `DELETE` }),
    developerListWebhookDeliveries: (e, t = {}) => {
      let n = new URLSearchParams()
      ;(t.limit && n.set(`limit`, String(t.limit)), t.offset && n.set(`offset`, String(t.offset)), t.status && n.set(`status`, t.status))
      let r = n.toString()
      return Q(`/api/developer/webhooks/${e}/deliveries${r ? `?${r}` : ``}`)
    },
    developerRetryWebhookDelivery: (e) => Q(`/api/developer/webhooks/deliveries/${e}/retry`, { method: `POST` }),
    developerTestWebhook: (e) => Q(`/api/developer/webhooks/${e}/test`, { method: `POST` }),
  },
  jd = {
    templatesList: (e = {}) => {
      let t = new URLSearchParams()
      return (
        e.q && t.set(`q`, e.q),
        e.category && t.set(`category`, e.category),
        e.difficulty && t.set(`difficulty`, e.difficulty),
        e.sort && t.set(`sort`, e.sort),
        e.limit && t.set(`limit`, String(e.limit)),
        e.offset && t.set(`offset`, String(e.offset)),
        Q(`/api/templates${t.toString() ? `?` + t.toString() : ``}`)
      )
    },
    templatesCategories: () => Q(`/api/templates/categories`),
    templateDetail: (e) => Q(`/api/templates/${encodeURIComponent(String(e))}`),
    templateInstall: (e) => Q(`/api/templates/${encodeURIComponent(String(e))}/install`, { method: `POST` }),
    saveWorkflowAsTemplate: (e, t) => Q(`/api/templates/from-workflow/${e}`, { method: `POST`, body: JSON.stringify(t) }),
  },
  Md = {
    notificationsList: (e = !1, t = 50, n = ``) => {
      let r = new URLSearchParams({ unread_only: e ? `true` : `false`, limit: String(t) })
      return (n && r.set(`kind`, n), Q(`/api/notifications/?${r}`))
    },
    notificationMarkRead: (e) => Q(`/api/notifications/${e}/read`, { method: `POST` }),
    notificationsMarkAllRead: () => Q(`/api/notifications/read-all`, { method: `POST` }),
    analyticsDashboard: () => Q(`/api/analytics/dashboard`),
  },
  Nd = {
    listEmployees: () => Q(`/api/employees/`),
    getEmployeeStatus: (e) => Q(`/api/employees/${encodeURIComponent(e)}/status`),
    getEmployeeManifest: async (e) => {
      try {
        return await Q(`/api/employees/${encodeURIComponent(e)}/manifest`)
      } catch (t) {
        let n = String(t?.message || ``)
        if (n.includes(`404`) || n.includes(`不存在`) || n.includes(`Not Found`))
          return { pack_id: e, name: e, version: `0.0.0`, manifest: {} }
        throw t
      }
    },
    employeeCatalogManifestDiagnostics: (e) =>
      Q(`/api/employees/catalog-manifest-diagnostics${e ? `?pack_id=${encodeURIComponent(e)}` : ``}`),
    executeEmployeeTask: (e, t, n) =>
      Q(`/api/employees/${e}/execute`, {
        method: `POST`,
        body: JSON.stringify({ task: t, input_data: n }),
      }),
    employeeExecuteFile: (e, t, n) => {
      let r = new FormData()
      return (
        r.append(`file`, t),
        n?.template && r.append(`template_file`, n.template),
        r.append(`task`, n?.task ?? ``),
        r.append(`input_data_json`, JSON.stringify(n?.inputData ?? {})),
        Q(`/api/employees/${encodeURIComponent(e)}/execute-file`, {
          method: `POST`,
          body: r,
          timeoutMs: n?.timeoutMs,
        })
      )
    },
    employeeOutputDownload: (e, t) =>
      pd(`/api/employees/downloads/${encodeURIComponent(e)}/${encodeURIComponent(t)}`, {
        method: `GET`,
      }),
  },
  Pd = `modulepreload`,
  Fd = function (e) {
    return `/corp-butler/` + e
  },
  Id = {},
  Ld = function (e, t, n) {
    let r = Promise.resolve()
    if (t && t.length > 0) {
      let e = document.getElementsByTagName(`link`),
        i = document.querySelector(`meta[property=csp-nonce]`),
        a = i?.nonce || i?.getAttribute(`nonce`)
      function o(e) {
        return Promise.all(
          e.map((e) =>
            Promise.resolve(e).then(
              (e) => ({ status: `fulfilled`, value: e }),
              (e) => ({ status: `rejected`, reason: e }),
            ),
          ),
        )
      }
      function s(e) {
        return import.meta.resolve
          ? import.meta.resolve(e)
          : new URL(e, new URL(`../../../src/node/plugins/importAnalysisBuild.ts`, import.meta.url)).href
      }
      r = o(
        t.map((t) => {
          if (((t = Fd(t, n)), (t = s(t)), t in Id)) return
          Id[t] = !0
          let r = t.endsWith(`.css`)
          for (let n = e.length - 1; n >= 0; n--) {
            let i = e[n]
            if (i.href === t && (!r || i.rel === `stylesheet`)) return
          }
          let i = document.createElement(`link`)
          if (
            ((i.rel = r ? `stylesheet` : Pd),
            r || (i.as = `script`),
            (i.crossOrigin = ``),
            (i.href = t),
            a && i.setAttribute(`nonce`, a),
            document.head.appendChild(i),
            r)
          )
            return new Promise((e, n) => {
              ;(i.addEventListener(`load`, e), i.addEventListener(`error`, () => n(Error(`Unable to preload CSS for ${t}`))))
            })
        }),
      )
    }
    function i(e) {
      let t = new Event(`vite:preloadError`, { cancelable: !0 })
      if (((t.payload = e), window.dispatchEvent(t), !t.defaultPrevented)) throw e
    }
    return r.then((t) => {
      for (let e of t || []) e.status === `rejected` && i(e.reason)
      return e().catch(i)
    })
  },
  Rd = {
    llmStatus: () => Q(`/api/llm/status`),
    llmResolveChatDefault: () => Q(`/api/llm/resolve-chat-default`),
    llmCatalog: (e = !1) => Q(`/api/llm/catalog?refresh=${+!!e}`),
    llmSaveCredentials: (e, t, n) =>
      Q(`/api/llm/credentials/${encodeURIComponent(e)}`, {
        method: `PUT`,
        body: JSON.stringify({ api_key: t, base_url: n ?? null }),
      }),
    llmDeleteCredentials: (e) => Q(`/api/llm/credentials/${encodeURIComponent(e)}`, { method: `DELETE` }),
    llmSavePreferences: (e, t) => Q(`/api/llm/preferences`, { method: `PUT`, body: JSON.stringify({ provider: e, model: t }) }),
    llmPricing: () => Q(`/api/llm/pricing`),
    llmUsage: (e = 50, t = 0) => Q(`/api/llm/usage?limit=${e}&offset=${t}`),
    llmConversations: (e = 30, t = 0) => Q(`/api/llm/conversations?limit=${e}&offset=${t}`),
    llmConversationDetail: (e) => Q(`/api/llm/conversations/${encodeURIComponent(String(e))}`),
    llmAdminSavePrice: (e) => Q(`/api/llm/admin/pricing`, { method: `PUT`, body: JSON.stringify(e || {}) }),
    llmAdminListPricing: (e) => {
      let t = new URLSearchParams()
      ;(e?.provider && t.set(`provider`, e.provider),
        e?.q && t.set(`q`, e.q),
        e?.limit != null && t.set(`limit`, String(e.limit)),
        e?.offset != null && t.set(`offset`, String(e.offset)))
      let n = t.toString()
      return Q(`/api/llm/admin/pricing${n ? `?${n}` : ``}`)
    },
    llmAdminBatchPricing: (e) => Q(`/api/llm/admin/pricing/batch`, { method: `POST`, body: JSON.stringify(e || {}) }),
    llmAdminPricingSettings: (e) => Q(`/api/llm/admin/pricing/settings`, { method: `PUT`, body: JSON.stringify(e || {}) }),
    llmAdminDisablePrice: (e, t) =>
      Q(`/api/llm/admin/pricing?${new URLSearchParams({ provider: e, model: t }).toString()}`, {
        method: `DELETE`,
      }),
    llmAdminOfficialSources: (e) => Q(`/api/llm/admin/pricing/official-sources?provider=${encodeURIComponent(e)}`),
    llmAdminSyncOfficialPrices: (e) => Q(`/api/llm/admin/pricing/sync-official`, { method: `POST`, body: JSON.stringify(e || {}) }),
    llmAdminApplyOfficialMarkup: (e) =>
      Q(`/api/llm/admin/pricing/apply-official-markup`, {
        method: `POST`,
        body: JSON.stringify(e || {}),
      }),
    llmAdminModelCapabilities: (e) => {
      let t = new URLSearchParams()
      ;(e?.provider && t.set(`provider`, e.provider), e?.q && t.set(`q`, e.q), e?.limit != null && t.set(`limit`, String(e.limit)))
      let n = t.toString()
      return Q(`/api/llm/admin/model-capabilities${n ? `?${n}` : ``}`)
    },
    llmAdminModelCapabilityReview: (e) => Q(`/api/llm/admin/model-capabilities/review`, { method: `PUT`, body: JSON.stringify(e) }),
    llmChat: async (e, t, n, r = null, i = null) => {
      let a = await Q(`/api/llm/chat`, {
        method: `POST`,
        body: JSON.stringify({
          provider: e,
          model: t,
          messages: n,
          max_tokens: r,
          conversation_id: i,
        }),
      })
      return (
        a &&
          (a.billed === !0 || (Number(a.charge_amount) || 0) > 0) &&
          Ld(() => import(`./chunks/llmBillingRefresh-DCwC0SeJ.js`).then((e) => e.refreshLevelAndWalletAfterLlm()), []),
        a
      )
    },
    llmChatStream: (e, t, n, r = null, i = null, a) => {
      let o = new Headers(_d())
      return (
        o.set(`Content-Type`, `application/json`),
        o.set(`Accept`, `text/event-stream`),
        fetch(`/api/llm/chat/stream`, {
          method: `POST`,
          headers: o,
          signal: a,
          body: JSON.stringify({
            provider: e,
            model: t,
            messages: n,
            max_tokens: r,
            conversation_id: i,
          }),
        })
      )
    },
    llmGenerateImage: (e, t, n, r = {}) =>
      Q(`/api/llm/image`, {
        method: `POST`,
        body: JSON.stringify({
          provider: e,
          model: t,
          prompt: n,
          size: r.size || `1024x1024`,
          n: r.count || r.n || 1,
        }),
      }),
    llmGenerateVideo: (e, t, n, r = {}) =>
      Q(`/api/llm/video`, {
        method: `POST`,
        body: JSON.stringify({
          provider: e,
          model: t,
          prompt: n,
          size: r.size || `1280x720`,
          seconds: r.seconds || r.durationSec || 5,
        }),
      }),
    llmGeneratePptxBlob: async (e, t, n = `ai-presentation.pptx`) => {
      let r = new Headers(_d())
      r.set(`Content-Type`, `application/json`)
      let i = await fetch(`/api/llm/pptx`, {
          method: `POST`,
          headers: r,
          body: JSON.stringify({ title: e, markdown: t, filename: n }),
        }),
        a = await i.arrayBuffer()
      if (!i.ok) {
        let e = i.statusText || `生成 PPT 失败`
        try {
          let t = new TextDecoder().decode(a),
            n = JSON.parse(t)
          e = n?.detail || n?.message || e
        } catch {}
        throw Error(e)
      }
      return new Blob([a], {
        type: `application/vnd.openxmlformats-officedocument.presentationml.presentation`,
      })
    },
  },
  zd = (e, t = {}) => fetch(e, t),
  Bd = {
    workbenchWebSearch: (e) => Q(`/api/workbench/web-search`, { method: `POST`, body: JSON.stringify(e) }),
    workbenchResearchContext: (e) => Q(`/api/workbench/research-context`, { method: `POST`, body: JSON.stringify(e) }),
    workbenchStartSession: (e) => Q(`/api/workbench/sessions`, { method: `POST`, body: JSON.stringify(e) }),
    workbenchStartSessionWithFiles: (e, t) => {
      let n = new FormData()
      n.append(`metadata`, JSON.stringify(e || {}))
      for (let e of t || []) n.append(`files`, e)
      return Q(`/api/workbench/sessions`, { method: `POST`, body: n })
    },
    workbenchStartScriptSession: (e, t) => {
      let n = new FormData()
      n.append(`metadata`, JSON.stringify(e || {}))
      for (let e of t || []) n.append(`files`, e)
      return Q(`/api/workbench/script-sessions`, { method: `POST`, body: n })
    },
    workbenchGetSession: (e) => Q(`/api/workbench/sessions/${encodeURIComponent(e)}`),
    streamEmployeeAiDraft: (e, t) =>
      zd(`/api/workbench/employee-ai/draft`, {
        method: `POST`,
        headers: { 'Content-Type': `application/json`, ..._d() },
        body: JSON.stringify({
          brief: e,
          provider: t?.provider || void 0,
          model: t?.model || void 0,
          suggested_id: t?.suggestedId || void 0,
        }),
      }),
    refineSystemPrompt: (e) => Q(`/api/workbench/employee-ai/refine-prompt`, { method: `POST`, body: JSON.stringify(e) }),
    workbenchEdgeTts: (e, t, n) =>
      pd(`/api/workbench/tts/edge`, {
        method: `POST`,
        body: JSON.stringify({
          text: e,
          ...(t ? { voice: t } : {}),
          ...(n != null && Number.isFinite(n) ? { rate: n } : {}),
        }),
      }),
    workbenchEdgeTtsStream: (e, t, n) =>
      hd(`/api/workbench/tts/edge/stream`, {
        method: `POST`,
        body: JSON.stringify({
          text: e,
          ...(t ? { voice: t } : {}),
          ...(n != null && Number.isFinite(n) ? { rate: n } : {}),
        }),
      }),
    listStudioAssets: (e) => {
      let t = e?.offset ?? 0,
        n = e?.limit ?? 50
      return Q(`/api/workbench/studio-assets?offset=${encodeURIComponent(String(t))}&limit=${encodeURIComponent(String(n))}`)
    },
    uploadStudioAsset: (e, t) => {
      let n = new FormData()
      return (
        n.append(`file`, e),
        t?.kind && n.append(`kind`, t.kind),
        t?.metadata && Object.keys(t.metadata).length && n.append(`metadata`, JSON.stringify(t.metadata)),
        Q(`/api/workbench/studio-assets`, { method: `POST`, body: n })
      )
    },
    deleteStudioAsset: (e) => Q(`/api/workbench/studio-assets/${encodeURIComponent(String(e))}`, { method: `DELETE` }),
    patchStudioAssetMetadata: (e, t) =>
      Q(`/api/workbench/studio-assets/${encodeURIComponent(String(e))}`, {
        method: `PATCH`,
        body: JSON.stringify({ metadata: t }),
      }),
    downloadStudioAssetBlob: (e) => pd(`/api/workbench/studio-assets/${encodeURIComponent(String(e))}/file`),
  },
  Vd = {
    knowledgeStatus: () => Q(`/api/knowledge/status`),
    knowledgeListDocuments: () => Q(`/api/knowledge/documents`),
    knowledgeUploadDocument: (e, t) => {
      let n = new FormData()
      return (
        n.append(`file`, e),
        t?.embeddingProvider && n.append(`embedding_provider`, t.embeddingProvider),
        t?.embeddingModel && n.append(`embedding_model`, t.embeddingModel),
        Q(`/api/knowledge/documents`, { method: `POST`, body: n })
      )
    },
    knowledgeDeleteDocument: (e) => Q(`/api/knowledge/documents/${encodeURIComponent(e)}`, { method: `DELETE` }),
    knowledgeExtractText: (e) => {
      let t = new FormData()
      return (t.append(`file`, e), Q(`/api/knowledge/extract-text`, { method: `POST`, body: t }))
    },
    knowledgeSearch: (e, t = 6, n) =>
      Q(`/api/knowledge/search`, {
        method: `POST`,
        body: JSON.stringify({
          query: e,
          limit: t,
          embedding_provider: n?.embeddingProvider,
          embedding_model: n?.embeddingModel,
        }),
      }),
    knowledgeV2Status: () => Q(`/api/knowledge/v2/status`),
    knowledgeV2ListCollections: (e) => {
      let t = []
      return (
        e?.ownerKind && t.push(`owner_kind=${encodeURIComponent(e.ownerKind)}`),
        e?.ownerId !== void 0 && e?.ownerId !== null && t.push(`owner_id=${encodeURIComponent(String(e.ownerId))}`),
        Q(`/api/knowledge/v2/collections${t.length ? `?${t.join(`&`)}` : ``}`)
      )
    },
    knowledgeV2CreateCollection: (e) => Q(`/api/knowledge/v2/collections`, { method: `POST`, body: JSON.stringify(e) }),
    knowledgeV2UpdateCollection: (e, t) =>
      Q(`/api/knowledge/v2/collections/${encodeURIComponent(String(e))}`, {
        method: `PATCH`,
        body: JSON.stringify(t),
      }),
    knowledgeV2DeleteCollection: (e) => Q(`/api/knowledge/v2/collections/${encodeURIComponent(String(e))}`, { method: `DELETE` }),
    knowledgeV2ListDocuments: (e) => Q(`/api/knowledge/v2/collections/${encodeURIComponent(String(e))}/documents`),
    knowledgeV2UploadDocument: (e, t, n) => {
      let r = new FormData()
      return (
        r.append(`file`, t),
        n?.embeddingProvider && r.append(`embedding_provider`, n.embeddingProvider),
        n?.embeddingModel && r.append(`embedding_model`, n.embeddingModel),
        Q(`/api/knowledge/v2/collections/${encodeURIComponent(String(e))}/documents`, {
          method: `POST`,
          body: r,
        })
      )
    },
    knowledgeV2DeleteDocument: (e, t) =>
      Q(`/api/knowledge/v2/collections/${encodeURIComponent(String(e))}/documents/${encodeURIComponent(t)}`, { method: `DELETE` }),
    knowledgeV2ShareCollection: (e, t) =>
      Q(`/api/knowledge/v2/collections/${encodeURIComponent(String(e))}/share`, {
        method: `POST`,
        body: JSON.stringify(t),
      }),
    knowledgeV2Unshare: (e, t) =>
      Q(`/api/knowledge/v2/collections/${encodeURIComponent(String(e))}/share/${encodeURIComponent(String(t))}`, { method: `DELETE` }),
    knowledgeV2Retrieve: (e) => Q(`/api/knowledge/v2/retrieve`, { method: `POST`, body: JSON.stringify(e) }),
  },
  Hd = {
    openApiListConnectors: () => Q(`/api/openapi-connectors/`),
    openApiGetConnector: (e) => Q(`/api/openapi-connectors/${encodeURIComponent(String(e))}`),
    openApiImportConnector: (e) => Q(`/api/openapi-connectors/import`, { method: `POST`, body: JSON.stringify(e) }),
    openApiDeleteConnector: (e) => Q(`/api/openapi-connectors/${encodeURIComponent(String(e))}`, { method: `DELETE` }),
    openApiSaveCredentials: (e, t, n) =>
      Q(`/api/openapi-connectors/${encodeURIComponent(String(e))}/credentials`, {
        method: `PUT`,
        body: JSON.stringify({ auth_type: t, config: n }),
      }),
    openApiDeleteCredentials: (e) =>
      Q(`/api/openapi-connectors/${encodeURIComponent(String(e))}/credentials`, {
        method: `DELETE`,
      }),
    openApiToggleOperation: (e, t, n) =>
      Q(`/api/openapi-connectors/${encodeURIComponent(String(e))}/operations/${encodeURIComponent(t)}`, {
        method: `PATCH`,
        body: JSON.stringify({ enabled: n }),
      }),
    openApiTestOperation: (e, t, n) =>
      Q(`/api/openapi-connectors/${encodeURIComponent(String(e))}/operations/${encodeURIComponent(t)}/test`, {
        method: `POST`,
        body: JSON.stringify(n || {}),
      }),
    openApiPublishWorkflowNode: (e, t) =>
      Q(`/api/openapi-connectors/${encodeURIComponent(String(e))}/publish-workflow-node`, {
        method: `POST`,
        body: JSON.stringify(t || {}),
      }),
    openApiListLogs: (e, t = 50, n = 0) => Q(`/api/openapi-connectors/${encodeURIComponent(String(e))}/logs?limit=${t}&offset=${n}`),
  },
  Ud = {
    customerServiceChat: (e) => Q(`/api/customer-service/chat`, { method: `POST`, body: JSON.stringify(e) }),
    customerServiceSessions: () => Q(`/api/customer-service/sessions`),
    customerServiceSessionDetail: (e) => Q(`/api/customer-service/sessions/${encodeURIComponent(String(e))}`),
    customerServiceTickets: (e = ``) => Q(`/api/customer-service/tickets${e ? `?status=${encodeURIComponent(e)}` : ``}`),
    customerServiceTicketDetail: (e) => Q(`/api/customer-service/tickets/${encodeURIComponent(String(e))}`),
    customerServiceActions: (e) => Q(`/api/customer-service/actions${e ? `?ticket_id=${encodeURIComponent(String(e))}` : ``}`),
    customerServiceStandards: () => Q(`/api/customer-service/standards`),
    customerServiceCreateStandard: (e) => Q(`/api/customer-service/standards`, { method: `POST`, body: JSON.stringify(e || {}) }),
    customerServiceUpdateStandard: (e, t) =>
      Q(`/api/customer-service/standards/${encodeURIComponent(String(e))}`, {
        method: `PUT`,
        body: JSON.stringify(t || {}),
      }),
    customerServiceIntegrations: () => Q(`/api/customer-service/integrations`),
    customerServiceCreateIntegration: (e) => Q(`/api/customer-service/integrations`, { method: `POST`, body: JSON.stringify(e || {}) }),
    customerServiceUpdateIntegration: (e, t) =>
      Q(`/api/customer-service/integrations/${encodeURIComponent(String(e))}`, {
        method: `PUT`,
        body: JSON.stringify(t || {}),
      }),
  },
  Wd = {
    agentCorpChat: (e) => Q(`/api/agent/butler/corp-chat`, { method: `POST`, body: JSON.stringify(e) }),
    agentCorpIntakeFill: (e) => Q(`/api/agent/butler/corp-intake-fill`, { method: `POST`, body: JSON.stringify(e) }),
    agentButlerChat: (e) => Q(`/api/agent/butler/chat`, { method: `POST`, body: JSON.stringify(e) }),
    agentButlerChatStream: (e, t) =>
      zd(`/api/agent/butler/chat/stream`, {
        method: `POST`,
        signal: t,
        headers: { 'Content-Type': `application/json`, Accept: `text/event-stream`, ..._d() },
        body: JSON.stringify(e),
      }),
    csSsotRetrieve: (e) => Q(`/api/agent/butler/cs-ssot/retrieve`, { method: `POST`, body: JSON.stringify(e) }),
    listButlerSkills: () => Q(`/api/agent/butler/skills`),
    recordButlerAction: (e) => Q(`/api/agent/butler/actions`, { method: `POST`, body: JSON.stringify(e) }),
    updateButlerSkillActive: (e, t) =>
      Q(`/api/agent/butler/skills/${encodeURIComponent(String(e))}`, {
        method: `PATCH`,
        body: JSON.stringify({ is_active: t }),
      }),
    butlerOrchestrateStart: (e) => Q(`/api/agent/butler/orchestrate`, { method: `POST`, body: JSON.stringify(e) }),
    butlerAllHandsReportStartSession: (e) =>
      Q(`/api/agent/butler/all-hands-report/sessions`, {
        method: `POST`,
        body: JSON.stringify(e || {}),
      }),
    butlerAllHandsReport: (e) => Q(`/api/agent/butler/all-hands-report`, { method: `POST`, body: JSON.stringify(e || {}) }),
  },
  Gd = {
    ...yd,
    ...bd,
    ...xd,
    ...Sd,
    ...Cd,
    ...wd,
    ...Td,
    ...Ed,
    ...Dd,
    ...Od,
    ...kd,
    ...Ad,
    ...jd,
    ...Md,
    ...Nd,
    ...Rd,
    ...Bd,
    ...Vd,
    ...Hd,
    ...Ud,
    ...Wd,
  },
  $ = dd
function Kd(e) {
  Yu(e)
}
function qd() {
  let e = qu()
  return e ? { Authorization: `Bearer ${e}` } : void 0
}
async function Jd(e, t = {}) {
  return $(e, t)
}
var Yd = {
  register: async (e, t, n, r = ``) => {
    let i = await Jd(`/api/auth/register`, {
      method: `POST`,
      body: JSON.stringify({ username: e, password: t, email: n, verification_code: r }),
    })
    return (Kd(i), i)
  },
  login: async (e, t) => {
    let n = await Jd(`/api/auth/login`, {
      method: `POST`,
      body: JSON.stringify({ username: e, password: t }),
    })
    return (Kd(n), n)
  },
  loginWithCode: async (e, t) => {
    let n = await Jd(`/api/auth/login-with-code`, {
      method: `POST`,
      body: JSON.stringify({ email: e, code: t }),
    })
    return (Kd(n), n)
  },
  sendPhoneCode: (e) => $(`/api/auth/send-phone-code`, { method: `POST`, body: JSON.stringify({ phone: e }) }),
  loginWithPhoneCode: async (e, t) => {
    let n = await Jd(`/api/auth/login-with-phone-code`, {
      method: `POST`,
      body: JSON.stringify({ phone: e, code: t }),
    })
    return (Kd(n), n)
  },
  me: () => $(`/api/auth/me`),
  accountBootstrap: () => $(`/api/account/bootstrap`),
  sendVerificationCode: (e) => $(`/api/auth/send-code`, { method: `POST`, body: JSON.stringify({ email: e }) }),
  sendRegisterVerificationCode: (e) => $(`/api/auth/send-register-code`, { method: `POST`, body: JSON.stringify({ email: e }) }),
  sendResetPasswordCode: (e) => $(`/api/auth/send-reset-password-code`, { method: `POST`, body: JSON.stringify({ email: e }) }),
  resetPassword: (e, t, n) =>
    $(`/api/auth/reset-password`, {
      method: `POST`,
      body: JSON.stringify({ email: e, code: t, new_password: n }),
    }),
  submitLandingContact: (e) =>
    $(`/api/public/contact`, {
      method: `POST`,
      body: JSON.stringify({
        name: e.name,
        email: e.email,
        phone: e.phone ?? ``,
        company: e.company ?? ``,
        message: e.message ?? ``,
        source: e.source ?? `home`,
      }),
    }),
  updateProfile: (e) => $(`/api/auth/profile`, { method: `PUT`, body: JSON.stringify({ username: e }) }),
  changePassword: (e, t) =>
    $(`/api/auth/change-password`, {
      method: `POST`,
      body: JSON.stringify({ current_password: e, new_password: t }),
    }),
  balance: () => $(`/api/wallet/balance`),
  walletOverview: (e = 20, t = 0) => $(`/api/wallet/overview?limit=${e}&offset=${t}`),
  walletAdminSelfCredit: (e, t = ``) =>
    $(`/api/wallet/admin-self-credit`, {
      method: `POST`,
      body: JSON.stringify({ amount: e, description: t }),
    }),
  recharge: (e, t = ``) =>
    $(`/api/wallet/recharge`, {
      method: `POST`,
      body: JSON.stringify({ amount: e, description: t }),
    }),
  transactions: (e = 50, t = 0) => $(`/api/wallet/transactions?limit=${e}&offset=${t}`),
  paymentPlans: () => $(`/api/payment/plans`),
  paymentMyPlan: () => $(`/api/payment/my-plan`),
  paymentQuery: (e, t) => {
    let n = t?.reconcile ? `?reconcile=true` : ``
    return $(`/api/payment/query/${encodeURIComponent(e)}${n}`)
  },
  paymentOrders: (e = ``, t = 50, n = 0) => {
    let r = new URLSearchParams({ limit: String(t), offset: String(n) })
    return (e && r.set(`status`, e), $(`/api/payment/orders?${r}`))
  },
  paymentDismissNonActiveOrders: () => $(`/api/payment/orders/dismiss-non-active`, { method: `POST`, body: `{}` }),
  paymentCancelOrder: (e) => $(`/api/payment/cancel/${encodeURIComponent(e)}`, { method: `POST`, body: `{}` }),
  paymentDiagnostics: () => $(`/api/payment/diagnostics`),
  paymentEntitlements: () => $(`/api/payment/entitlements`),
  paymentCheckout: async (e) => {
    let t = await $(`/api/payment/sign-checkout`, {
        method: `POST`,
        body: JSON.stringify({
          plan_id: e?.plan_id ?? ``,
          item_id: Number(e?.item_id ?? 0) || 0,
          total_amount: Number(e?.total_amount ?? 0) || 0,
          subject: e?.subject ?? ``,
          wallet_recharge: !!e?.wallet_recharge,
        }),
      }),
      n = {
        plan_id: t.plan_id ?? ``,
        item_id: t.item_id ?? 0,
        total_amount: t.total_amount ?? 0,
        subject: t.subject ?? ``,
        wallet_recharge: !!t.wallet_recharge,
        request_id: t.request_id,
        timestamp: t.timestamp,
        signature: t.signature,
      }
    ;(e?.pay_channel && (n.pay_channel = e.pay_channel), e?.pay_type && (n.pay_type = e.pay_type))
    let r = await $(`/api/payment/checkout`, { method: `POST`, body: JSON.stringify(n) })
    if (r?.ok === !1) return r
    if (r?.ok !== !0) throw Error(`支付下单返回异常：缺少成功标识`)
    let i = String(r.type || ``).trim()
    if (!i) throw Error(`支付下单返回异常：缺少支付类型`)
    if (i === `page` || i === `wap`) {
      let e = r.redirect_url
      if (!e || String(e).trim() === ``) throw Error(`支付下单返回异常：缺少跳转地址`)
    }
    if (i === `precreate` || i === `wechat_native`) {
      let e = r.order_id
      if (!e || String(e).trim() === ``) throw Error(`支付下单返回异常：缺少订单号`)
    }
    return r
  },
  refundsApply: async (e, t) => {
    let n = await $(`/api/refunds/apply`, {
      method: `POST`,
      body: JSON.stringify({ order_no: e, reason: t }),
    })
    if (n?.ok === !1) throw Error(n.message || `退款申请失败`)
    return n
  },
  refundsMy: () => $(`/api/refunds/my`),
  refundsAdminPending: () => $(`/api/refunds/admin/pending`),
  refundsAdminReview: (e, t, n = ``) =>
    $(`/api/refunds/admin/${encodeURIComponent(String(e))}/review`, {
      method: `POST`,
      body: JSON.stringify({ action: t, admin_note: n }),
    }),
  catalog: (e = ``, t = ``, n = 50, r = 0, i = ``, a = ``, o = ``, s = ``, c = !1) => {
    let l = new URLSearchParams({ limit: String(n), offset: String(r) })
    return (
      e && l.set(`q`, e),
      t && l.set(`artifact`, t),
      i && l.set(`industry`, i),
      a && l.set(`security_level`, a),
      o && l.set(`material_category`, o),
      s && l.set(`license_scope`, s),
      c && l.set(`_cb`, String(Date.now())),
      $(`/api/market/catalog?${l}`)
    )
  },
  catalogFacets: () => $(`/api/market/facets`),
  catalogDetail: (e) => $(`/api/market/catalog/${encodeURIComponent(String(e))}`),
  catalogQuality: (e, t = !1) => {
    let n = typeof t == `boolean` ? { refresh: t } : t,
      r = new URLSearchParams()
    ;(n.refresh && r.set(`refresh`, `1`), n.llm && r.set(`llm`, `1`))
    let i = r.toString()
    return $(`/api/market/catalog/${encodeURIComponent(String(e))}/quality${i ? `?${i}` : ``}`)
  },
  catalogReviews: (e) => $(`/api/market/catalog/${encodeURIComponent(String(e))}/reviews`),
  catalogSubmitReview: (e, t, n = ``) =>
    $(`/api/market/catalog/${encodeURIComponent(String(e))}/review`, {
      method: `POST`,
      body: JSON.stringify({ rating: t, content: n }),
    }),
  catalogSubmitComplaint: (e, t, n, r = {}) =>
    $(`/api/market/catalog/${encodeURIComponent(String(e))}/complaints`, {
      method: `POST`,
      body: JSON.stringify({ complaint_type: t, reason: n, evidence: r }),
    }),
  catalogToggleFavorite: (e) =>
    $(`/api/market/catalog/${encodeURIComponent(String(e))}/favorite`, {
      method: `POST`,
      body: `{}`,
    }),
  buyItem: (e) => $(`/api/market/catalog/${encodeURIComponent(String(e))}/buy`, { method: `POST` }),
  downloadItem: async (e) => {
    let t = await fd(`/api/market/catalog/${encodeURIComponent(String(e))}/download`, qd()),
      n = URL.createObjectURL(t),
      r = document.createElement(`a`)
    ;((r.href = n),
      (r.download = `mod-${e}.zip`),
      (r.style.display = `none`),
      document.body.appendChild(r),
      r.click(),
      r.remove(),
      window.setTimeout(() => URL.revokeObjectURL(n), 6e4))
  },
  myStore: (e = 50, t = 0) => $(`/api/my-store?limit=${e}&offset=${t}`),
  adminStatus: () => $(`/api/admin/status`),
  adminResearchSettings: () => $(`/api/admin/research-settings`),
  adminSaveResearchSettings: (e) => $(`/api/admin/research-settings`, { method: `PUT`, body: JSON.stringify(e || {}) }),
  adminVectorSettings: () => $(`/api/admin/vector-settings`),
  adminSaveVectorSettings: (e) => $(`/api/admin/vector-settings`, { method: `PUT`, body: JSON.stringify(e || {}) }),
  adminUpload: (e) => $(`/api/admin/catalog`, { method: `POST`, body: e }),
  adminListCatalog: (e = 200, t = 0) => $(`/api/admin/catalog?limit=${e}&offset=${t}`),
  adminDeleteCatalog: (e) => $(`/api/admin/catalog/${encodeURIComponent(String(e))}`, { method: `DELETE` }),
  adminDeleteEmployeePack: (e) => $(`/api/admin/employee-packs/${encodeURIComponent(e)}`, { method: `DELETE` }),
  adminPurgeAllEmployeePacks: () => $(`/api/admin/employee-packs/purge-all`, { method: `POST` }),
  adminAlignEmployeeLlmFromDeepseek: (e = !1) =>
    $(`/api/admin/employee-packs/align-llm-from-deepseek?dry_run=${e ? `true` : `false`}`, {
      method: `POST`,
    }),
  adminAlignEmployeeLlmToAuto: (e = !1) =>
    $(`/api/admin/employee-packs/align-llm-to-auto?dry_run=${e ? `true` : `false`}`, {
      method: `POST`,
    }),
  adminAlignSingleEmployeeLlmToAuto: (e, t = !1) =>
    $(`/api/admin/employee-packs/${encodeURIComponent(e)}/align-llm-to-auto-single?dry_run=${t ? `true` : `false`}`, { method: `POST` }),
  adminListNoKeyEmployees: () => $(`/api/admin/duty-graph/no-key-employees`),
  verifyAdminDigestCode: (e) => $(`/api/auth/verify-admin-digest-code`, { method: `POST`, body: JSON.stringify({ code: e }) }),
  adminOpsSshHint: () => $(`/api/admin/ops-ssh-hint`),
  adminOpsAuditLogs: (e) => {
    let t = new URLSearchParams()
    ;(e?.employee_id && t.set(`employee_id`, e.employee_id), e?.limit != null && t.set(`limit`, String(e.limit)))
    let n = t.toString()
    return $(`/api/admin/ops/audit${n ? `?${n}` : ``}`)
  },
  adminOpsStagedChanges: (e) => {
    let t = new URLSearchParams()
    ;(e?.status && t.set(`status`, e.status), e?.limit != null && t.set(`limit`, String(e.limit)))
    let n = t.toString()
    return $(`/api/admin/ops/staged-changes${n ? `?${n}` : ``}`)
  },
  adminOpsApprovalTokens: (e) => {
    let t = new URLSearchParams()
    e?.limit != null && t.set(`limit`, String(e.limit))
    let n = t.toString()
    return $(`/api/admin/ops/approval-tokens${n ? `?${n}` : ``}`)
  },
  adminEmployeeExecutionMetrics: (e, t) => {
    let n = new URLSearchParams()
    ;(t?.limit != null && n.set(`limit`, String(t.limit)),
      t?.offset != null && n.set(`offset`, String(t.offset)),
      t?.user_id != null && n.set(`user_id`, String(t.user_id)))
    let r = n.toString()
    return $(`/api/admin/employees/${encodeURIComponent(e)}/execution-metrics${r ? `?${r}` : ``}`)
  },
  adminEmployeeExecutionCapability: (e) => $(`/api/admin/employees/${encodeURIComponent(e)}/execution-capability`),
  adminEmployeeExecutionCapabilities: (e) =>
    $(`/api/admin/employees/execution-capabilities`, {
      method: `POST`,
      body: JSON.stringify({ employee_ids: Array.isArray(e) ? e : [] }),
    }),
  adminDutyGraphRunStart: (e) => $(`/api/admin/duty-graph/runs`, { method: `POST`, body: JSON.stringify(e || {}) }),
  adminDutyGraphRunDetail: (e) => $(`/api/admin/duty-graph/runs/${encodeURIComponent(String(e))}`),
  adminDutyGraphHealth: () => $(`/api/admin/duty-graph/health`),
  adminEmployeeAutonomyDashboard: (e = 30) => $(`/api/admin/employee-autonomy/dashboard?limit_recent=${encodeURIComponent(String(e))}`),
  adminEmployeeSuggestions: (e) => {
    let t = new URLSearchParams()
    ;(e?.status && t.set(`status`, e.status),
      e?.risk_level && t.set(`risk_level`, e.risk_level),
      e?.limit != null && t.set(`limit`, String(e.limit)),
      e?.offset != null && t.set(`offset`, String(e.offset)))
    let n = t.toString()
    return $(`/api/admin/employee-autonomy/suggestions${n ? `?${n}` : ``}`)
  },
  adminEmployeeSuggestionApprove: (e, t = !0) =>
    $(`/api/admin/employee-autonomy/suggestions/${encodeURIComponent(String(e))}/approve`, {
      method: `POST`,
      body: JSON.stringify({ dispatch_now: t }),
    }),
  adminEmployeeSuggestionReject: (e, t = ``) =>
    $(`/api/admin/employee-autonomy/suggestions/${encodeURIComponent(String(e))}/reject`, {
      method: `POST`,
      body: JSON.stringify({ reason: t }),
    }),
  adminEmployeeSuggestionBatchReview: (e) =>
    $(`/api/admin/employee-autonomy/suggestions/batch-review`, {
      method: `POST`,
      body: JSON.stringify(e || {}),
    }),
  adminEmployeeBriefTasks: (e) => {
    let t = new URLSearchParams()
    ;(e?.status && t.set(`status`, e.status), e?.limit != null && t.set(`limit`, String(e.limit)))
    let n = t.toString()
    return $(`/api/admin/employee-autonomy/brief-tasks${n ? `?${n}` : ``}`)
  },
  adminEmployeeDispatchBriefTasks: (e = 20) =>
    $(`/api/admin/employee-autonomy/dispatch/brief-tasks`, {
      method: `POST`,
      body: JSON.stringify({ limit: e }),
    }),
  adminEmployeeDispatchSuggestions: (e = 20) =>
    $(`/api/admin/employee-autonomy/dispatch/suggestions`, {
      method: `POST`,
      body: JSON.stringify({ limit: e }),
    }),
  adminEmployeeEvolutionScan: (e) =>
    $(`/api/admin/employee-autonomy/evolution/scan`, {
      method: `POST`,
      body: JSON.stringify(e || {}),
    }),
  adminEmployeeCollabThreads: (e) => {
    let t = new URLSearchParams()
    ;(e?.status && t.set(`status`, e.status), e?.limit != null && t.set(`limit`, String(e.limit)))
    let n = t.toString()
    return $(`/api/admin/employee-autonomy/collab/threads${n ? `?${n}` : ``}`)
  },
  adminEmployeeCreateCollabThread: (e) =>
    $(`/api/admin/employee-autonomy/collab/threads`, {
      method: `POST`,
      body: JSON.stringify(e || {}),
    }),
  adminEmployeeCollabMessages: (e, t = 100) =>
    $(`/api/admin/employee-autonomy/collab/threads/${encodeURIComponent(String(e))}/messages?limit=${encodeURIComponent(String(t))}`),
  adminEmployeePostCollabMessage: (e, t) =>
    $(`/api/admin/employee-autonomy/collab/threads/${encodeURIComponent(String(e))}/messages`, {
      method: `POST`,
      body: JSON.stringify(t || {}),
    }),
  opsOrchestrateAsync: (e) =>
    $(`/api/ops/orchestrate/async`, {
      method: `POST`,
      body: JSON.stringify({
        use_task_router: !0,
        max_concurrency: 2,
        allow_high_risk_real_run: !1,
        ...e,
      }),
    }),
  opsOrchestrateJob: (e) => $(`/api/ops/orchestrate/jobs/${encodeURIComponent(e)}`),
  opsOrchestrateJobs: (e = 20) => $(`/api/ops/orchestrate/jobs?limit=${encodeURIComponent(String(e))}`),
  adminChangeRequestsList: (e) => {
    let t = new URLSearchParams()
    ;(e?.status && t.set(`status`, e.status), e?.limit != null && t.set(`limit`, String(e.limit)))
    let n = t.toString()
    return $(`/api/admin/change-requests${n ? `?${n}` : ``}`)
  },
  adminChangeRequestDetail: (e) => $(`/api/admin/change-requests/${encodeURIComponent(String(e))}`),
  adminChangeRequestApprove: (e) => $(`/api/admin/change-requests/${encodeURIComponent(String(e))}/approve`, { method: `POST` }),
  adminChangeRequestReject: (e, t) =>
    $(`/api/admin/change-requests/${encodeURIComponent(String(e))}/reject`, {
      method: `POST`,
      body: JSON.stringify(t || {}),
    }),
  adminListAiAccounts: (e = {}) => {
    let t = new URLSearchParams()
    ;(e.platform && t.set(`platform`, e.platform),
      e.employee_id && t.set(`employee_id`, e.employee_id),
      e.status && t.set(`status`, e.status),
      e.limit != null && t.set(`limit`, String(e.limit)),
      e.offset != null && t.set(`offset`, String(e.offset)))
    let n = t.toString()
    return $(`/api/admin/ai-accounts${n ? `?${n}` : ``}`)
  },
  adminCreateAiAccount: (e) => $(`/api/admin/ai-accounts`, { method: `POST`, body: JSON.stringify(e) }),
  adminUpdateAiAccount: (e, t) =>
    $(`/api/admin/ai-accounts/${encodeURIComponent(String(e))}`, {
      method: `PATCH`,
      body: JSON.stringify(t),
    }),
  adminRotateAiAccountSecret: (e, t) =>
    $(`/api/admin/ai-accounts/${encodeURIComponent(String(e))}/rotate`, {
      method: `POST`,
      body: JSON.stringify({ secret: t }),
    }),
  adminDeleteAiAccount: (e) => $(`/api/admin/ai-accounts/${encodeURIComponent(String(e))}`, { method: `DELETE` }),
  butlerQqStatus: () => $(`/api/agent/butler/qq/status`),
  adminYuangonOnboardStatus: () => $(`/api/admin/yuangon-onboard/status`),
  adminYuangonOnboardRun: (e) => $(`/api/admin/yuangon-onboard/run`, { method: `POST`, body: JSON.stringify(e || {}) }),
  adminPurgeAllMods: () => $(`/api/admin/mods/purge-all`, { method: `POST` }),
  adminListCatalogComplaints: (e = ``, t = 50, n = 0) => {
    let r = new URLSearchParams({ limit: String(t), offset: String(n) })
    return (e && r.set(`status`, e), $(`/api/admin/catalog/complaints?${r}`))
  },
  adminReviewCatalogComplaint: (e, t, n = ``, r = {}) =>
    $(`/api/admin/catalog/complaints/${encodeURIComponent(String(e))}/review`, {
      method: `POST`,
      body: JSON.stringify({ action: t, admin_note: n, ...r }),
    }),
  adminListUsers: (e = 200, t = 0, n) => {
    let r = new URLSearchParams({ limit: String(e), offset: String(t) })
    return (n === !0 ? r.set(`is_enterprise`, `true`) : n === !1 && r.set(`is_enterprise`, `false`), $(`/api/admin/users?${r}`))
  },
  adminSetUserAdmin: (e, t) => $(`/api/admin/users/${e}/admin?is_admin=${t}`, { method: `PUT` }),
  adminSetUserEnterprise: (e, t) => $(`/api/admin/users/${e}/enterprise?is_enterprise=${t}`, { method: `PUT` }),
  adminEnterpriseAssignableMods: () => $(`/api/admin/enterprise/assignable-mods`),
  adminListUserMods: (e) => $(`/api/admin/users/${encodeURIComponent(String(e))}/mods`),
  adminBindUserMod: (e, t) =>
    $(`/api/admin/users/${encodeURIComponent(String(e))}/mods/${encodeURIComponent(t)}`, {
      method: `POST`,
    }),
  adminUnbindUserMod: (e, t) =>
    $(`/api/admin/users/${encodeURIComponent(String(e))}/mods/${encodeURIComponent(t)}`, {
      method: `DELETE`,
    }),
  adminListWallets: (e = 200, t = 0) => $(`/api/admin/wallets?limit=${e}&offset=${t}`),
  adminListTransactions: (e = 200, t = 0) => $(`/api/admin/transactions?limit=${e}&offset=${t}`),
  listMods: (e = !1) => $(`/api/mods${e ? `?_=${Date.now()}` : ``}`),
  deleteMod: (e) => $(`/api/mods/${encodeURIComponent(e)}`, { method: `DELETE` }),
  createMod: (e, t, n = `通用`) =>
    $(`/api/mods/create`, {
      method: `POST`,
      body: JSON.stringify({ mod_id: e, display_name: t, industry_id: n }),
    }),
  importZIP: (e, t = !0) => {
    let n = new FormData()
    return (n.append(`file`, e), $(`/api/mods/import?replace=${t}`, { method: `POST`, body: n }))
  },
  modAiScaffold: (e, t = ``, n = !0, r = `通用`, i, a) =>
    $(`/api/mods/ai-scaffold`, {
      method: `POST`,
      body: JSON.stringify({
        brief: e,
        suggested_id: t || void 0,
        replace: n,
        industry_id: r || `通用`,
        provider: i,
        model: a,
      }),
    }),
  push: (e = null) => $(`/api/sync/push`, { method: `POST`, body: JSON.stringify({ mod_ids: e }) }),
  pull: (e = null) => $(`/api/sync/pull`, { method: `POST`, body: JSON.stringify({ mod_ids: e }) }),
  getRepoConfig: () => $(`/api/config`),
  putRepoConfig: (e) => $(`/api/config`, { method: `PUT`, body: JSON.stringify(e || {}) }),
  getMod: (e) => $(`/api/mods/${encodeURIComponent(e)}`),
  putModManifest: (e, t) =>
    $(`/api/mods/${encodeURIComponent(e)}/manifest`, {
      method: `PUT`,
      body: JSON.stringify({ manifest: t }),
    }),
  attachCatalogEmployeeToMod: (e, t) =>
    $(`/api/mods/${encodeURIComponent(e)}/attach-catalog-employee`, {
      method: `POST`,
      body: JSON.stringify(t),
    }),
  getModFile: (e, t) => $(`/api/mods/${encodeURIComponent(e)}/file?path=${encodeURIComponent(t)}`),
  putModFile: (e, t, n) =>
    $(`/api/mods/${encodeURIComponent(e)}/file`, {
      method: `PUT`,
      body: JSON.stringify({ path: t, content: n }),
    }),
  regenerateModFrontend: (e, t = ``) =>
    $(`/api/mods/${encodeURIComponent(e)}/frontend/regenerate`, {
      method: `POST`,
      body: JSON.stringify({ brief: t }),
    }),
  listModSnapshots: (e) => $(`/api/mods/${encodeURIComponent(e)}/snapshots`),
  captureModSnapshot: (e, t = ``) =>
    $(`/api/mods/${encodeURIComponent(e)}/snapshots`, {
      method: `POST`,
      body: JSON.stringify({ label: t }),
    }),
  restoreModSnapshot: (e, t) =>
    $(`/api/mods/${encodeURIComponent(e)}/snapshots/${encodeURIComponent(t)}/restore`, {
      method: `POST`,
      body: `{}`,
    }),
  bumpModManifestPatchVersion: (e) =>
    $(`/api/mods/${encodeURIComponent(e)}/manifest/bump-patch-version`, {
      method: `POST`,
      body: `{}`,
    }),
  modWorkflowLink: (e, t) =>
    $(`/api/mods/${encodeURIComponent(e)}/workflow-link`, {
      method: `POST`,
      body: JSON.stringify(t),
    }),
  scaffoldWorkflowEmployee: (e, t) =>
    $(`/api/mods/${encodeURIComponent(e)}/workflow-employees/scaffold`, {
      method: `POST`,
      body: JSON.stringify(t),
    }),
  getModAuthoringSummary: (e) => $(`/api/mods/${encodeURIComponent(e)}/authoring-summary`),
  getModBlueprintRoutes: (e) => $(`/api/mods/${encodeURIComponent(e)}/blueprint-routes`),
  getAuthoringExtensionSurface: (e = !1) => $(`/api/authoring/extension-surface?merge_host=${e ? `true` : `false`}`),
  exportEmployeePackZip: async (e, t = 0) => {
    let n = String(e || ``).trim(),
      r = Number.parseInt(String(t ?? 0), 10),
      i = `workflow_index=${Number.isFinite(r) && r >= 0 ? r : 0}`,
      a = qd(),
      o = [`/api/mods/${encodeURIComponent(n)}/export-employee-pack?${i}`, `/api/mods/${encodeURIComponent(n)}/export_employee_pack?${i}`],
      s = (e) => {
        let t = String(e || ``).trim()
        if (/mod\s*不存在|Mod 不存在/i.test(t)) return !1
        if (/^not found$/i.test(t) || t === `{"detail":"Not Found"}`) return !0
        try {
          let e = JSON.parse(t)?.detail
          if (e === `Not Found` || (Array.isArray(e) && e.some((e) => String(e?.msg || ``).toLowerCase() === `not found`))) return !0
        } catch {}
        return !1
      },
      c
    for (let e = 0; e < o.length; e++)
      try {
        return await fd(o[e], a)
      } catch (t) {
        if (((c = t), s(String(t?.message || ``).trim()) && e === 0)) continue
        break
      }
    let l = String(c?.message || `导出失败`).trim()
    throw s(l)
      ? Error(
          `${l} — 8765 上的 API 进程里若没有该路由，会返回 Not Found。请完全退出旧进程后重启：在 MODstore_deploy 目录执行 start-modstore.bat / restart.bat，或手动运行 python -m modstore_server。自检：打开 http://127.0.0.1:8765/docs 搜索「export-employee-pack」，搜不到即仍是旧代码。`,
        )
      : c instanceof Error
        ? c
        : Error(l)
  },
  exportModZip: (e) => fd(`/api/mods/${encodeURIComponent(e)}/export`, qd()),
  auditPackage: (e, t = null) => {
    let n = new FormData()
    return (n.append(`file`, e), t != null && n.append(`metadata`, JSON.stringify(t)), $(`/api/package-audit`, { method: `POST`, body: n }))
  },
  listV1Packages: (e = ``, t = ``, n = 50, r = 0, i = !1) => {
    let a = new URLSearchParams({ limit: String(n), offset: String(r) })
    return (e && a.set(`artifact`, e), t && a.set(`q`, t), i && a.set(`_`, String(Date.now())), $(`/v1/packages?${a}`))
  },
  listCatalogPackageVersions: (e) => $(`/v1/packages/by-id/${encodeURIComponent(e)}/versions`),
  promoteCatalogPackage: (e, t) =>
    $(`/v1/packages/${encodeURIComponent(e)}/promote`, {
      method: `POST`,
      body: JSON.stringify({ from_version: t }),
      headers: void 0,
    }),
  downloadCatalogPackageBlob: (e, t) => fd(`/v1/packages/${encodeURIComponent(e)}/${encodeURIComponent(t)}/download`),
  uploadPackage: (e, t) => {
    let n = new FormData()
    return (n.append(`metadata`, JSON.stringify(e)), n.append(`file`, t), $(`/v1/packages`, { method: `POST`, body: n, headers: void 0 }))
  },
  registerWorkflowEmployeeCatalog: (e, t = 0, n = {}) =>
    $(`/api/mods/${encodeURIComponent(e)}/register-workflow-employee-catalog`, {
      method: `POST`,
      body: JSON.stringify({
        workflow_index: t,
        industry: n.industry || `通用`,
        price: n.price ?? 0,
        release_channel: n.release_channel || `stable`,
      }),
    }),
  patchModWorkflowEmployeeNodes: (e) => $(`/api/mods/${encodeURIComponent(e)}/patch-workflow-employee-nodes`, { method: `POST` }),
  runWorkflowEmployeeClosure: (e, t = {}) =>
    $(`/api/mods/${encodeURIComponent(e)}/workflow-employee-closure`, {
      method: `POST`,
      body: JSON.stringify({
        register_missing: t.register_missing !== !1,
        patch_canvas: t.patch_canvas !== !1,
        industry: t.industry || `通用`,
      }),
    }),
  employeeBenchTest: (e, t, n) =>
    $(`/api/workbench/employee-bench-test`, {
      method: `POST`,
      body: JSON.stringify({ employee_id: e, provider: t || null, model: n || null }),
    }),
  employeePublish: (e, t) =>
    $(`/api/workbench/employee-publish`, {
      method: `POST`,
      body: JSON.stringify({ employee_id: e, ...(t || {}) }),
    }),
  employeeSaveManifest: (e, t, n) =>
    $(`/api/workbench/employee-save`, {
      method: `POST`,
      body: JSON.stringify({
        manifest: e,
        employee_id: t || null,
        provider: n?.provider || null,
        model: n?.model || null,
        register_skills: n?.registerSkills !== !1,
      }),
    }),
  employeeExportZip: async (e, t, n) => {
    let r = qd() || {}
    r[`Content-Type`] = `application/json`
    let i = await fetch(`/api/workbench/employee-export`, {
      method: `POST`,
      headers: r,
      body: JSON.stringify({
        manifest: e,
        employee_id: t || null,
        standalone: n?.standalone === !0,
      }),
    })
    if (!i.ok) {
      let e = await i.json().catch(() => ({}))
      throw Error(String(e?.detail || e?.error || `HTTP ${i.status}`))
    }
    return i.blob()
  },
  employeeSyncTest: (e, t, n, r) =>
    $(`/api/workbench/employee-sync-test`, {
      method: `POST`,
      body: JSON.stringify({
        employee_id: e,
        fhd_base_url: t || null,
        provider: n || null,
        model: r || null,
      }),
    }),
  listScriptWorkflows: (e = ``) => $(`/api/script-workflows${e ? `?status=${encodeURIComponent(e)}` : ``}`),
  getScriptWorkflow: (e) => $(`/api/script-workflows/${e}`),
  updateScriptWorkflow: (e, t) => $(`/api/script-workflows/${e}`, { method: `PUT`, body: JSON.stringify(t) }),
  deleteScriptWorkflow: (e) => $(`/api/script-workflows/${e}`, { method: `DELETE` }),
  sandboxRunScriptWorkflow: (e, t) => {
    let n = new FormData()
    return (t.forEach((e) => n.append(`files`, e)), $(`/api/script-workflows/${e}/sandbox-run`, { method: `POST`, body: n }))
  },
  runScriptWorkflow: (e, t) => {
    let n = new FormData()
    return (t.forEach((e) => n.append(`files`, e)), $(`/api/script-workflows/${e}/run`, { method: `POST`, body: n }))
  },
  activateScriptWorkflow: (e) => $(`/api/script-workflows/${e}/activate`, { method: `POST` }),
  deactivateScriptWorkflow: (e) => $(`/api/script-workflows/${e}/deactivate`, { method: `POST` }),
  listScriptWorkflowRuns: (e, t = ``) => $(`/api/script-workflows/${e}/runs${t ? `?mode=${encodeURIComponent(t)}` : ``}`),
  downloadScriptWorkflowRunFile: async (e, t, n) => {
    let r = await fetch(
      `/api/script-workflows/${encodeURIComponent(String(e))}/runs/${encodeURIComponent(String(t))}/files/${encodeURIComponent(n)}`,
      { headers: qd() },
    )
    if (!r.ok) throw Error(r.statusText || `下载失败`)
    return r.blob()
  },
  listScriptWorkflowVersions: (e) => $(`/api/script-workflows/${e}/versions`),
  commitScriptWorkflowSession: (e, t) =>
    $(`/api/script-workflows/sessions/${encodeURIComponent(e)}/commit`, {
      method: `POST`,
      body: JSON.stringify(t),
    }),
  getScriptWorkflowSession: (e) => $(`/api/script-workflows/sessions/${encodeURIComponent(e)}`),
  listWorkflows: () => $(`/api/workflow/`),
  listESkills: () => $(`/api/eskills`),
  createESkill: (e) => $(`/api/eskills`, { method: `POST`, body: JSON.stringify(e || {}) }),
  runESkill: (e, t) => $(`/api/eskills/${e}/run`, { method: `POST`, body: JSON.stringify(t || {}) }),
  listEmployeeEligibleWorkflows: () => $(`/api/workflow/employee-eligible`),
  listWorkflowsByEmployee: (e) => $(`/api/workflow/by-employee?employee_id=${encodeURIComponent(e)}`),
  getWorkflow: (e) => $(`/api/workflow/${e}`),
  createWorkflow: (e, t) => $(`/api/workflow/`, { method: `POST`, body: JSON.stringify({ name: e, description: t }) }),
  updateWorkflow: (e, t, n, r) =>
    $(`/api/workflow/${e}`, {
      method: `PUT`,
      body: JSON.stringify({ name: t, description: n, is_active: r }),
    }),
  deleteWorkflow: (e) => $(`/api/workflow/${e}`, { method: `DELETE` }),
  addWorkflowNode: (e, t, n, r, i, a) =>
    $(`/api/workflow/${e}/nodes`, {
      method: `POST`,
      body: JSON.stringify({ node_type: t, name: n, config: r, position_x: i, position_y: a }),
    }),
  updateWorkflowNode: (e, t, n, r, i) =>
    $(`/api/workflow/nodes/${e}`, {
      method: `PUT`,
      body: JSON.stringify({ name: t, config: n, position_x: r, position_y: i }),
    }),
  deleteWorkflowNode: (e) => $(`/api/workflow/nodes/${e}`, { method: `DELETE` }),
  addWorkflowEdge: (e, t, n, r = ``) =>
    $(`/api/workflow/${e}/edges`, {
      method: `POST`,
      body: JSON.stringify({ source_node_id: t, target_node_id: n, condition: r }),
    }),
  deleteWorkflowEdge: (e) => $(`/api/workflow/edges/${e}`, { method: `DELETE` }),
  executeWorkflow: (e, t = {}) => $(`/api/workflow/${e}/execute`, { method: `POST`, body: JSON.stringify({ input_data: t }) }),
  workflowValidate: (e) => $(`/api/workflow/${e}/validate`),
  workflowSandboxRun: (e, t) => $(`/api/workflow/${e}/sandbox-run`, { method: `POST`, body: JSON.stringify(t || {}) }),
  listWorkflowExecutions: (e, t = 50, n = 0) => $(`/api/workflow/${e}/executions?limit=${t}&offset=${n}`),
  listWorkflowTriggers: (e) => $(`/api/workflow/${e}/triggers`),
  createWorkflowTrigger: (e, t) => $(`/api/workflow/${e}/triggers`, { method: `POST`, body: JSON.stringify(t || {}) }),
  deleteWorkflowTrigger: (e, t) => $(`/api/workflow/${e}/triggers/${t}`, { method: `DELETE` }),
  workflowWebhookRun: (e, t = {}) => $(`/api/workflow/${e}/webhook-run`, { method: `POST`, body: JSON.stringify(t) }),
  publishWorkflowVersion: (e, t = ``) => $(`/api/workflow/${e}/versions/publish`, { method: `POST`, body: JSON.stringify({ note: t }) }),
  listWorkflowVersions: (e, t = 50, n = 0) => $(`/api/workflow/${e}/versions?limit=${t}&offset=${n}`),
  getWorkflowVersion: (e, t) => $(`/api/workflow/${e}/versions/${t}`),
  rollbackWorkflowVersion: (e, t) => $(`/api/workflow/${e}/versions/${t}/rollback`, { method: `POST` }),
  getExecution: (e) => $(`/api/workflow/executions/${e}`),
  developerListTokens: () => $(`/api/developer/tokens`),
  developerCreateToken: (e, t = [], n = null) =>
    $(`/api/developer/tokens`, {
      method: `POST`,
      body: JSON.stringify({ name: e, scopes: t, expires_days: n }),
    }),
  developerRevokeToken: (e) => $(`/api/developer/tokens/${e}`, { method: `DELETE` }),
  developerExportKeyBundle: (e) =>
    $(`/api/developer/key-export/bundle`, {
      method: `POST`,
      body: JSON.stringify({
        recipient_public_key_spki_b64: e.recipient_public_key_spki_b64,
        current_password: e.current_password,
        token_ids: e.token_ids,
        rotate_source_tokens: e.rotate_source_tokens !== !1,
      }),
    }),
  developerListKeyExportAudit: (e = 50) => $(`/api/developer/key-export/audit?limit=${encodeURIComponent(String(e))}`),
  developerWebhookEventCatalog: () => $(`/api/developer/webhooks/event-catalog`),
  developerListWebhooks: () => $(`/api/developer/webhooks`),
  developerCreateWebhook: (e) => $(`/api/developer/webhooks`, { method: `POST`, body: JSON.stringify(e) }),
  developerUpdateWebhook: (e, t) => $(`/api/developer/webhooks/${e}`, { method: `PUT`, body: JSON.stringify(t) }),
  developerDeleteWebhook: (e) => $(`/api/developer/webhooks/${e}`, { method: `DELETE` }),
  developerListWebhookDeliveries: (e, t = {}) => {
    let n = new URLSearchParams()
    ;(t.limit && n.set(`limit`, String(t.limit)), t.offset && n.set(`offset`, String(t.offset)), t.status && n.set(`status`, t.status))
    let r = n.toString()
    return $(`/api/developer/webhooks/${e}/deliveries${r ? `?${r}` : ``}`)
  },
  developerRetryWebhookDelivery: (e) => $(`/api/developer/webhooks/deliveries/${e}/retry`, { method: `POST` }),
  developerTestWebhook: (e) => $(`/api/developer/webhooks/${e}/test`, { method: `POST` }),
  templatesList: (e = {}) => {
    let t = new URLSearchParams()
    return (
      e.q && t.set(`q`, e.q),
      e.category && t.set(`category`, e.category),
      e.difficulty && t.set(`difficulty`, e.difficulty),
      e.sort && t.set(`sort`, e.sort),
      e.limit && t.set(`limit`, String(e.limit)),
      e.offset && t.set(`offset`, String(e.offset)),
      $(`/api/templates${t.toString() ? `?` + t.toString() : ``}`)
    )
  },
  templatesCategories: () => $(`/api/templates/categories`),
  templateDetail: (e) => $(`/api/templates/${encodeURIComponent(String(e))}`),
  templateInstall: (e) => $(`/api/templates/${encodeURIComponent(String(e))}/install`, { method: `POST` }),
  saveWorkflowAsTemplate: (e, t) => $(`/api/templates/from-workflow/${e}`, { method: `POST`, body: JSON.stringify(t) }),
  notificationsList: (e = !1, t = 50, n = ``) => {
    let r = new URLSearchParams({ unread_only: e ? `true` : `false`, limit: String(t) })
    return (n && r.set(`kind`, n), $(`/api/notifications/?${r}`))
  },
  notificationMarkRead: (e) => $(`/api/notifications/${e}/read`, { method: `POST` }),
  notificationsMarkAllRead: () => $(`/api/notifications/read-all`, { method: `POST` }),
  analyticsDashboard: () => $(`/api/analytics/dashboard`),
  listEmployees: () => $(`/api/employees/`),
  getEmployeeStatus: (e) => $(`/api/employees/${encodeURIComponent(e)}/status`),
  getEmployeeManifest: async (e) => {
    try {
      return await $(`/api/employees/${encodeURIComponent(e)}/manifest`)
    } catch (t) {
      let n = String(t?.message || ``)
      if (n.includes(`404`) || n.includes(`不存在`) || n.includes(`Not Found`))
        return { pack_id: e, name: e, version: `0.0.0`, manifest: {} }
      throw t
    }
  },
  employeeCatalogManifestDiagnostics: (e) =>
    $(`/api/employees/catalog-manifest-diagnostics${e ? `?pack_id=${encodeURIComponent(e)}` : ``}`),
  executeEmployeeTask: (e, t, n) =>
    $(`/api/employees/${e}/execute`, {
      method: `POST`,
      body: JSON.stringify({ task: t, input_data: n }),
    }),
  employeeExecuteFile: (e, t, n) => {
    let r = new FormData()
    return (
      r.append(`file`, t),
      n?.template && r.append(`template_file`, n.template),
      r.append(`task`, n?.task ?? ``),
      r.append(`input_data_json`, JSON.stringify(n?.inputData ?? {})),
      $(`/api/employees/${encodeURIComponent(e)}/execute-file`, {
        method: `POST`,
        body: r,
        timeoutMs: n?.timeoutMs,
      })
    )
  },
  employeeOutputDownload: (e, t) =>
    pd(`/api/employees/downloads/${encodeURIComponent(e)}/${encodeURIComponent(t)}`, {
      method: `GET`,
    }),
  llmStatus: () => $(`/api/llm/status`),
  llmResolveChatDefault: () => $(`/api/llm/resolve-chat-default`),
  llmCatalog: (e = !1) => $(`/api/llm/catalog?refresh=${+!!e}`),
  llmSaveCredentials: (e, t, n) =>
    $(`/api/llm/credentials/${encodeURIComponent(e)}`, {
      method: `PUT`,
      body: JSON.stringify({ api_key: t, base_url: n ?? null }),
    }),
  llmDeleteCredentials: (e) => $(`/api/llm/credentials/${encodeURIComponent(e)}`, { method: `DELETE` }),
  llmSavePreferences: (e, t) => $(`/api/llm/preferences`, { method: `PUT`, body: JSON.stringify({ provider: e, model: t }) }),
  llmPricing: () => $(`/api/llm/pricing`),
  llmUsage: (e = 50, t = 0) => $(`/api/llm/usage?limit=${e}&offset=${t}`),
  llmConversations: (e = 30, t = 0) => $(`/api/llm/conversations?limit=${e}&offset=${t}`),
  llmConversationDetail: (e) => $(`/api/llm/conversations/${encodeURIComponent(String(e))}`),
  llmAdminSavePrice: (e) => $(`/api/llm/admin/pricing`, { method: `PUT`, body: JSON.stringify(e || {}) }),
  llmAdminModelCapabilities: (e) => {
    let t = new URLSearchParams()
    ;(e?.provider && t.set(`provider`, e.provider), e?.q && t.set(`q`, e.q), e?.limit != null && t.set(`limit`, String(e.limit)))
    let n = t.toString()
    return $(`/api/llm/admin/model-capabilities${n ? `?${n}` : ``}`)
  },
  llmAdminModelCapabilityReview: (e) => $(`/api/llm/admin/model-capabilities/review`, { method: `PUT`, body: JSON.stringify(e) }),
  llmChat: async (e, t, n, r = null, i = null) => {
    let a = await $(`/api/llm/chat`, {
      method: `POST`,
      body: JSON.stringify({
        provider: e,
        model: t,
        messages: n,
        max_tokens: r,
        conversation_id: i,
      }),
    })
    return (
      a &&
        (a.billed === !0 || (Number(a.charge_amount) || 0) > 0) &&
        Ld(() => import(`./chunks/llmBillingRefresh-DCwC0SeJ.js`).then((e) => e.refreshLevelAndWalletAfterLlm()), []),
      a
    )
  },
  llmChatStream: (e, t, n, r = null, i = null, a) => {
    let o = new Headers(qd())
    return (
      o.set(`Content-Type`, `application/json`),
      o.set(`Accept`, `text/event-stream`),
      fetch(`/api/llm/chat/stream`, {
        method: `POST`,
        headers: o,
        signal: a,
        body: JSON.stringify({
          provider: e,
          model: t,
          messages: n,
          max_tokens: r,
          conversation_id: i,
        }),
      })
    )
  },
  llmGenerateImage: (e, t, n, r = {}) =>
    $(`/api/llm/image`, {
      method: `POST`,
      body: JSON.stringify({
        provider: e,
        model: t,
        prompt: n,
        size: r.size || `1024x1024`,
        n: r.count || r.n || 1,
      }),
    }),
  llmGenerateVideo: (e, t, n, r = {}) =>
    $(`/api/llm/video`, {
      method: `POST`,
      body: JSON.stringify({
        provider: e,
        model: t,
        prompt: n,
        size: r.size || `1280x720`,
        seconds: r.seconds || r.durationSec || 5,
      }),
    }),
  llmGeneratePptxBlob: async (e, t, n = `ai-presentation.pptx`) => {
    let r = new Headers(qd())
    r.set(`Content-Type`, `application/json`)
    let i = await fetch(`/api/llm/pptx`, {
        method: `POST`,
        headers: r,
        body: JSON.stringify({ title: e, markdown: t, filename: n }),
      }),
      a = await i.arrayBuffer()
    if (!i.ok) {
      let e = i.statusText || `生成 PPT 失败`
      try {
        let t = new TextDecoder().decode(a),
          n = JSON.parse(t)
        e = n?.detail || n?.message || e
      } catch {}
      throw Error(e)
    }
    return new Blob([a], {
      type: `application/vnd.openxmlformats-officedocument.presentationml.presentation`,
    })
  },
  workbenchResearchContext: (e) => $(`/api/workbench/research-context`, { method: `POST`, body: JSON.stringify(e) }),
  workbenchStartSession: (e) => $(`/api/workbench/sessions`, { method: `POST`, body: JSON.stringify(e) }),
  workbenchStartSessionWithFiles: (e, t) => {
    let n = new FormData()
    n.append(`metadata`, JSON.stringify(e || {}))
    for (let e of t || []) n.append(`files`, e)
    return $(`/api/workbench/sessions`, { method: `POST`, body: n })
  },
  workbenchStartScriptSession: (e, t) => {
    let n = new FormData()
    n.append(`metadata`, JSON.stringify(e || {}))
    for (let e of t || []) n.append(`files`, e)
    return $(`/api/workbench/script-sessions`, { method: `POST`, body: n })
  },
  workbenchGetSession: (e) => $(`/api/workbench/sessions/${encodeURIComponent(e)}`),
  workbenchRetrySession: (e) => $(`/api/workbench/sessions/${encodeURIComponent(e)}/retry`, { method: `POST` }),
  streamEmployeeAiDraft: (e, t) =>
    fetch(`/api/workbench/employee-ai/draft`, {
      method: `POST`,
      headers: { 'Content-Type': `application/json` },
      body: JSON.stringify({
        brief: e,
        provider: t?.provider || void 0,
        model: t?.model || void 0,
        suggested_id: t?.suggestedId || void 0,
      }),
    }),
  refineSystemPrompt: (e) => $(`/api/workbench/employee-ai/refine-prompt`, { method: `POST`, body: JSON.stringify(e) }),
  workbenchEdgeTts: (e, t, n) =>
    pd(`/api/workbench/tts/edge`, {
      method: `POST`,
      body: JSON.stringify({
        text: e,
        ...(t ? { voice: t } : {}),
        ...(n != null && Number.isFinite(n) ? { rate: n } : {}),
      }),
    }),
  workbenchEdgeTtsStream: (e, t, n) =>
    hd(`/api/workbench/tts/edge/stream`, {
      method: `POST`,
      body: JSON.stringify({
        text: e,
        ...(t ? { voice: t } : {}),
        ...(n != null && Number.isFinite(n) ? { rate: n } : {}),
      }),
    }),
  listStudioAssets: (e) => {
    let t = e?.offset ?? 0,
      n = e?.limit ?? 50
    return $(`/api/workbench/studio-assets?offset=${encodeURIComponent(String(t))}&limit=${encodeURIComponent(String(n))}`)
  },
  uploadStudioAsset: (e, t) => {
    let n = new FormData()
    return (
      n.append(`file`, e),
      t?.kind && n.append(`kind`, t.kind),
      t?.metadata && Object.keys(t.metadata).length && n.append(`metadata`, JSON.stringify(t.metadata)),
      $(`/api/workbench/studio-assets`, { method: `POST`, body: n })
    )
  },
  deleteStudioAsset: (e) => $(`/api/workbench/studio-assets/${encodeURIComponent(String(e))}`, { method: `DELETE` }),
  patchStudioAssetMetadata: (e, t) =>
    $(`/api/workbench/studio-assets/${encodeURIComponent(String(e))}`, {
      method: `PATCH`,
      body: JSON.stringify({ metadata: t }),
    }),
  downloadStudioAssetBlob: (e) => pd(`/api/workbench/studio-assets/${encodeURIComponent(String(e))}/file`),
  knowledgeStatus: () => $(`/api/knowledge/status`),
  knowledgeListDocuments: () => $(`/api/knowledge/documents`),
  knowledgeUploadDocument: (e, t) => {
    let n = new FormData()
    return (
      n.append(`file`, e),
      t?.embeddingProvider && n.append(`embedding_provider`, t.embeddingProvider),
      t?.embeddingModel && n.append(`embedding_model`, t.embeddingModel),
      $(`/api/knowledge/documents`, { method: `POST`, body: n })
    )
  },
  knowledgeDeleteDocument: (e) => $(`/api/knowledge/documents/${encodeURIComponent(e)}`, { method: `DELETE` }),
  knowledgeExtractText: (e) => {
    let t = new FormData()
    return (t.append(`file`, e), $(`/api/knowledge/extract-text`, { method: `POST`, body: t }))
  },
  knowledgeSearch: (e, t = 6, n) =>
    $(`/api/knowledge/search`, {
      method: `POST`,
      body: JSON.stringify({
        query: e,
        limit: t,
        embedding_provider: n?.embeddingProvider,
        embedding_model: n?.embeddingModel,
      }),
    }),
  knowledgeV2Status: () => $(`/api/knowledge/v2/status`),
  knowledgeV2ListCollections: (e) => {
    let t = []
    return (
      e?.ownerKind && t.push(`owner_kind=${encodeURIComponent(e.ownerKind)}`),
      e?.ownerId !== void 0 && e?.ownerId !== null && t.push(`owner_id=${encodeURIComponent(String(e.ownerId))}`),
      $(`/api/knowledge/v2/collections${t.length ? `?${t.join(`&`)}` : ``}`)
    )
  },
  knowledgeV2CreateCollection: (e) => $(`/api/knowledge/v2/collections`, { method: `POST`, body: JSON.stringify(e) }),
  knowledgeV2UpdateCollection: (e, t) =>
    $(`/api/knowledge/v2/collections/${encodeURIComponent(String(e))}`, {
      method: `PATCH`,
      body: JSON.stringify(t),
    }),
  knowledgeV2DeleteCollection: (e) => $(`/api/knowledge/v2/collections/${encodeURIComponent(String(e))}`, { method: `DELETE` }),
  knowledgeV2ListDocuments: (e) => $(`/api/knowledge/v2/collections/${encodeURIComponent(String(e))}/documents`),
  knowledgeV2UploadDocument: (e, t, n) => {
    let r = new FormData()
    return (
      r.append(`file`, t),
      n?.embeddingProvider && r.append(`embedding_provider`, n.embeddingProvider),
      n?.embeddingModel && r.append(`embedding_model`, n.embeddingModel),
      $(`/api/knowledge/v2/collections/${encodeURIComponent(String(e))}/documents`, {
        method: `POST`,
        body: r,
      })
    )
  },
  knowledgeV2DeleteDocument: (e, t) =>
    $(`/api/knowledge/v2/collections/${encodeURIComponent(String(e))}/documents/${encodeURIComponent(t)}`, { method: `DELETE` }),
  knowledgeV2ShareCollection: (e, t) =>
    $(`/api/knowledge/v2/collections/${encodeURIComponent(String(e))}/share`, {
      method: `POST`,
      body: JSON.stringify(t),
    }),
  knowledgeV2Unshare: (e, t) =>
    $(`/api/knowledge/v2/collections/${encodeURIComponent(String(e))}/share/${encodeURIComponent(String(t))}`, { method: `DELETE` }),
  knowledgeV2Retrieve: (e) => $(`/api/knowledge/v2/retrieve`, { method: `POST`, body: JSON.stringify(e) }),
  openApiListConnectors: () => $(`/api/openapi-connectors/`),
  openApiGetConnector: (e) => $(`/api/openapi-connectors/${encodeURIComponent(String(e))}`),
  openApiImportConnector: (e) => $(`/api/openapi-connectors/import`, { method: `POST`, body: JSON.stringify(e) }),
  openApiDeleteConnector: (e) => $(`/api/openapi-connectors/${encodeURIComponent(String(e))}`, { method: `DELETE` }),
  openApiSaveCredentials: (e, t, n) =>
    $(`/api/openapi-connectors/${encodeURIComponent(String(e))}/credentials`, {
      method: `PUT`,
      body: JSON.stringify({ auth_type: t, config: n }),
    }),
  openApiDeleteCredentials: (e) => $(`/api/openapi-connectors/${encodeURIComponent(String(e))}/credentials`, { method: `DELETE` }),
  openApiToggleOperation: (e, t, n) =>
    $(`/api/openapi-connectors/${encodeURIComponent(String(e))}/operations/${encodeURIComponent(t)}`, {
      method: `PATCH`,
      body: JSON.stringify({ enabled: n }),
    }),
  openApiTestOperation: (e, t, n) =>
    $(`/api/openapi-connectors/${encodeURIComponent(String(e))}/operations/${encodeURIComponent(t)}/test`, {
      method: `POST`,
      body: JSON.stringify(n || {}),
    }),
  openApiPublishWorkflowNode: (e, t) =>
    $(`/api/openapi-connectors/${encodeURIComponent(String(e))}/publish-workflow-node`, {
      method: `POST`,
      body: JSON.stringify(t || {}),
    }),
  openApiListLogs: (e, t = 50, n = 0) => $(`/api/openapi-connectors/${encodeURIComponent(String(e))}/logs?limit=${t}&offset=${n}`),
  customerServiceChat: (e) => $(`/api/customer-service/chat`, { method: `POST`, body: JSON.stringify(e) }),
  customerServiceSessions: () => $(`/api/customer-service/sessions`),
  customerServiceSessionDetail: (e) => $(`/api/customer-service/sessions/${encodeURIComponent(String(e))}`),
  customerServiceTickets: (e = ``) => $(`/api/customer-service/tickets${e ? `?status=${encodeURIComponent(e)}` : ``}`),
  customerServiceTicketDetail: (e) => $(`/api/customer-service/tickets/${encodeURIComponent(String(e))}`),
  customerServiceActions: (e) => $(`/api/customer-service/actions${e ? `?ticket_id=${encodeURIComponent(String(e))}` : ``}`),
  customerServiceStandards: () => $(`/api/customer-service/standards`),
  customerServiceCreateStandard: (e) => $(`/api/customer-service/standards`, { method: `POST`, body: JSON.stringify(e || {}) }),
  customerServiceUpdateStandard: (e, t) =>
    $(`/api/customer-service/standards/${encodeURIComponent(String(e))}`, {
      method: `PUT`,
      body: JSON.stringify(t || {}),
    }),
  customerServiceIntegrations: () => $(`/api/customer-service/integrations`),
  customerServiceCreateIntegration: (e) => $(`/api/customer-service/integrations`, { method: `POST`, body: JSON.stringify(e || {}) }),
  customerServiceUpdateIntegration: (e, t) =>
    $(`/api/customer-service/integrations/${encodeURIComponent(String(e))}`, {
      method: `PUT`,
      body: JSON.stringify(t || {}),
    }),
  agentCorpChat: (e) => $(`/api/agent/butler/corp-chat`, { method: `POST`, body: JSON.stringify(e) }),
  agentButlerChat: (e) => $(`/api/agent/butler/chat`, { method: `POST`, body: JSON.stringify(e) }),
  agentButlerChatStream: (e, t) => {
    let n = new Headers(qd())
    return (
      n.set(`Content-Type`, `application/json`),
      n.set(`Accept`, `text/event-stream`),
      fetch(`/api/agent/butler/chat/stream`, {
        method: `POST`,
        headers: n,
        signal: t,
        body: JSON.stringify(e),
      })
    )
  },
  listButlerSkills: () => $(`/api/agent/butler/skills`),
  recordButlerAction: (e) => $(`/api/agent/butler/actions`, { method: `POST`, body: JSON.stringify(e) }),
  updateButlerSkillActive: (e, t) =>
    $(`/api/agent/butler/skills/${encodeURIComponent(String(e))}`, {
      method: `PATCH`,
      body: JSON.stringify({ is_active: t }),
    }),
  butlerOrchestrateStart: (e) => $(`/api/agent/butler/orchestrate`, { method: `POST`, body: JSON.stringify(e) }),
  butlerAllHandsReportStartSession: (e) =>
    $(`/api/agent/butler/all-hands-report/sessions`, {
      method: `POST`,
      body: JSON.stringify(e || {}),
    }),
  butlerAllHandsReport: (e) => $(`/api/agent/butler/all-hands-report`, { method: `POST`, body: JSON.stringify(e || {}) }),
  ...Gd,
}
function Xd(e) {
  return { success: !0, message: e, assistantReply: e }
}
var Zd = {
  profile: `profile`,
  problem: `problem`,
  workflow: `workflow`,
  contact: `contact`,
  plan: `plan`,
  review: `review`,
  1: `profile`,
  2: `problem`,
  3: `workflow`,
  4: `contact`,
  5: `plan`,
  6: `review`,
}
function Qd(e) {
  let t = e.match(/第\s*([1-6])\s*题/)
  return t
    ? Zd[t[1]] || null
    : /联系方式|姓名|邮箱|手机/.test(e)
      ? `contact`
      : /核对|预览|提交前|review/.test(e)
        ? `review`
        : /计划|时间|预算|对接/.test(e)
          ? `plan`
          : /流程|日常|怎么做/.test(e)
            ? `workflow`
            : /困扰|头疼|改善/.test(e)
              ? `problem`
              : /认识|岗位|角色|第\s*1/.test(e)
                ? `profile`
                : null
}
function $d(e) {
  if (Cu(e.route || ``) !== `contact`) return null
  let t = e.userMessage.trim()
  if (!t) return null
  if (/填表|问卷|预填|帮我写|填写需求|写入问卷|自动填/.test(t)) return { kind: `fill` }
  if (/核对|预览|提交前/.test(t)) return { kind: `review` }
  if (/跳到|跳转|下一步|上一题|去.*题/.test(t)) {
    let e = Qd(t)
    if (e) return { kind: `step`, stepId: e }
  }
  let n = Qd(t)
  return n && /第|步|题|联系方式|核对/.test(t) ? { kind: `step`, stepId: n } : null
}
async function ef(e, t) {
  let n = await Ru()
  if (!n) return (Vu(), Xd(`${au()}问卷尚未就绪，请刷新页面后重试；您也可以直接在表单中逐步填写。`))
  if (n.isSubmitted()) return Xd(`您已提交过需求问卷，如需修改请通过电话或邮件联系我们。`)
  try {
    let r = await Yd.agentCorpIntakeFill({
        message: e,
        current_draft: n.getState(),
        page_summary: t.slice(0, 3500),
      }),
      i = r?.draft || {},
      a = (r?.reply || ``).trim()
    if (!Object.keys(i).length)
      return (Vu(), Xd(a || `我未能从描述中解析出可填写的字段，请补充岗位、日常事务和联系方式，或直接在${au()}表单填写。`))
    if (!Hu(i)) return Xd(`问卷已提交或不可用，无法继续预填。`)
    let o = Object.keys(i).filter((e) => {
        let t = i[e]
        return Array.isArray(t) ? t.length > 0 : String(t ?? ``).trim()
      }),
      s = o.length > 0 ? `\n\n已尝试写入：${o.join(`、`)}。请在${au()}核对，不确定的项请自行修改。` : ``
    return Xd((a || `已根据您的描述预填问卷，请在${au()}逐步核对。`) + s)
  } catch {
    return (Vu(), Xd(`智能预填暂时不可用，已为您定位到问卷区域。请直接在${au()}分步填写，或稍后再试。`))
  }
}
async function tf(e, t) {
  let n = await Ru()
  return n
    ? n.isSubmitted()
      ? Xd(`需求问卷已提交，感谢信任！如需补充说明请联系我们的顾问。`)
      : e.kind === `fill`
        ? ef(t.userMessage, t.pageSummary || ``)
        : e.kind === `review`
          ? (n.goToStep(`review`), Vu(), Xd(`已跳转到「核对并提交」步骤，请检查${au()}摘要后点击提交。`))
          : (n.goToStep(e.stepId),
            Vu(),
            Xd(
              `已跳转到「${{ profile: `认识您`, problem: `您的困扰`, workflow: `日常事务`, contact: `联系方式`, plan: `计划`, review: `提交` }[e.stepId]}」步骤，请继续在${au()}填写。`,
            ))
    : (Vu(), Xd(`请先在${au()}打开需求问卷；若未显示，请刷新页面（Cmd+Shift+R）。`))
}
async function nf(e) {
  if (!e.task) return null
  let t = await Ru()
  if (!t && e.task !== `navigate`) return (Vu(), Xd(`问卷加载中，请稍候再点任务卡片，或刷新页面。`))
  switch (e.task) {
    case `intake_fill`:
      return ef(e.payload?.prompt?.trim() || e.message?.trim() || `请根据我的描述帮我填写${au()}需求问卷`, ``)
    case `intake_step`: {
      let n = e.payload?.stepId || `profile`
      return (t && !t.isSubmitted() && (t.goToStep(n), Vu()), Xd(`已为您打开问卷的「${n}」步骤，请在${au()}继续填写。`))
    }
    case `intake_review`:
      return (t && !t.isSubmitted() && (t.goToStep(`review`), Vu()), Xd(`已打开提交前核对页，请检查${au()}内容后提交。`))
    case `navigate`: {
      let t = e.payload?.href?.trim()
      if (!t) return Xd(`请说明要前往的页面。`)
      let n = (t.startsWith(`http`), t)
      return (
        window.setTimeout(() => {
          window.location.assign(n)
        }, 400),
        Xd(`正在为您打开「${e.label}」…`)
      )
    }
    default:
      return null
  }
}
var rf = nf,
  af = `xc_corp_visitor_id`,
  of = `xc_corp_visitor_label`
function sf() {
  return `v_${(typeof crypto < `u` && typeof crypto.randomUUID == `function` ? crypto.randomUUID().replace(/-/g, ``) : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`).slice(0, 32)}`
}
function cf() {
  try {
    let e = String(localStorage.getItem(af) || ``).trim()
    if (/^v_[A-Za-z0-9_-]{8,64}$/.test(e)) return e
    let t = sf()
    return (localStorage.setItem(af, t), t)
  } catch {
    return sf()
  }
}
function lf() {
  try {
    return String(localStorage.getItem(of) || ``)
      .trim()
      .slice(0, 32)
  } catch {
    return ``
  }
}
function uf(e) {
  let t = String(e || ``)
    .replace(/\s+/g, ` `)
    .trim()
    .slice(0, 32)
  try {
    t ? localStorage.setItem(of, t) : localStorage.removeItem(of)
  } catch {}
}
var df = 0
function ff() {
  return `corp-msg-${Date.now()}-${++df}`
}
function pf(e) {
  return { id: ff(), role: `user`, content: e, timestamp: Date.now() }
}
function mf(e, t = !1) {
  return { id: ff(), role: `assistant`, content: e, timestamp: Date.now(), isLoading: t }
}
function hf(e) {
  return `我是小C（修茈科技官网客服），可以解答产品、案例与预约咨询。\n\n• 产品能力 → ${e}${Z.services}\n• 预约沟通 → ${e}${Z.contact}\n• 登录 AI 市场 → ${e}${Z.market}\n\n您也可以直接问：「有哪些产品？」「怎么联系你们？」`
}
function gf() {
  let e = tu()
  async function t(t, n, r = `idle`) {
    ;(e.updateLastMessage({ content: n, isLoading: !1 }), e.setMode(r), (e.isLoading = !1))
  }
  async function n(n, r) {
    let i = n.trim()
    if (!i) return
    ;((e.isLoading = !0), e.setMode(`thinking`), r?.skipUserInsert || (e.addMessage(pf(i)), e.addMessage(mf(`…`, !0))))
    let a = `${location.pathname}`,
      o = Cu(a),
      s = mu().slice(0, 800)
    try {
      let n = {
          route: `${location.pathname}${location.search}`,
          pageTitle: document.title,
          pageSummary: ju({ corpPathname: a, domExcerpt: s }),
          userMessage: i,
          history: e.messages.slice(-12),
        },
        r = $d(n)
      if (r) {
        let e = await tf(r, n)
        if (e?.assistantReply) {
          await t(``, e.assistantReply)
          return
        }
      }
      let c = Fu(n)
      if (c?.assistantReply) {
        await t(``, c.assistantReply)
        return
      }
      if (o === `contact` && /填|问卷|预填|跟单|录入|单据|excel/i.test(i)) {
        let e = await ef(i, n.pageSummary || ``)
        if (e?.assistantReply) {
          await t(``, e.assistantReply)
          return
        }
      }
      await t(``, (await _f(i, o, n.pageSummary, n.history)) || hf(location.origin))
    } catch (e) {
      await t(``, `暂时无法处理：${e instanceof Error ? e.message : String(e)}`, `error`)
    } finally {
      ;((e.isLoading = !1), e.mode === `thinking` && e.setMode(`idle`))
    }
  }
  async function r(r) {
    let i = r.label.trim()
    if (!(!i && !r.task)) {
      ;((e.isLoading = !0),
        e.setMode(`thinking`),
        r.message?.trim() ? e.addMessage(pf(r.message.trim())) : e.addMessage(pf(i)),
        e.addMessage(mf(`…`, !0)))
      try {
        let e = await rf(r)
        if (e?.assistantReply) {
          await t(``, e.assistantReply)
          return
        }
        if (r.message?.trim()) {
          await n(r.message.trim(), { skipUserInsert: !0 })
          return
        }
        await t(``, `已收到，请继续在${au()}问卷中填写。`)
      } catch (e) {
        await t(``, `暂时无法处理：${e instanceof Error ? e.message : String(e)}`, `error`)
      } finally {
        ;((e.isLoading = !1), e.mode === `thinking` && e.setMode(`idle`))
      }
    }
  }
  return { handleInput: n, runIntakeTask: r }
}
async function _f(e, t, n, r) {
  try {
    let i = wu(t),
      a = r
        .filter((e) => (e.role === `user` || e.role === `assistant`) && !e.isLoading)
        .slice(-8)
        .map((e) => ({ role: e.role, content: e.content })),
      o = cf()
    try {
      let e = String(Lu()?.getState?.()?.name || ``).trim()
      e && uf(e)
    } catch {}
    let s = lf(),
      c = await Yd.agentCorpChat({
        messages: [...a, { role: `user`, content: e }],
        page_id: t,
        page_context: `${i.title}\n${i.summary}\n\n${n}`.slice(0, 3500),
        visitor_id: o,
        visitor_label: s || void 0,
      })
    return (c?.content || c?.message || ``).trim() || null
  } catch {
    return null
  }
}
var vf = z(!1),
  yf = z([]),
  bf = z(0),
  xf = 0
function Sf(e) {
  let t = e.map((e) => String(e || ``).trim()).filter(Boolean)
  xf += 1
  let n = xf
  return ((yf.value = t.map((e) => ({ zh: e, en: `` }))), (bf.value = 0), (vf.value = t.length > 0), t.length || (vf.value = !1), n)
}
function Cf(e) {
  return e === xf && vf.value
}
function wf(e, t) {
  ;(t != null && t !== xf) || !vf.value || !yf.value.length || (bf.value = Math.max(0, Math.min(yf.value.length - 1, e)))
}
function Tf(e, t, n) {
  if (n != null && n !== xf) return
  let r = yf.value[e]
  if (!r) return
  let i = [...yf.value]
  ;((i[e] = { ...r, en: String(t || ``).trim() }), (yf.value = i))
}
function Ef(e) {
  ;(e != null && e !== xf) || ((vf.value = !1), (yf.value = []), (bf.value = 0), (xf += 1))
}
function Df() {
  let e = q(() => yf.value[bf.value] || null),
    t = q(() => (bf.value > 0 && yf.value[bf.value - 1]) || null),
    n = q(() => (bf.value < yf.value.length - 1 && yf.value[bf.value + 1]) || null)
  return {
    visible: It(vf),
    lines: It(yf),
    currentIndex: It(bf),
    current: e,
    prev: t,
    next: n,
    dismiss: () => Ef(),
  }
}
var Of = 80,
  kf = new Map(),
  Af = `/api/agent/butler/corp-translate`
function jf(e) {
  return kf.get(e)
}
function Mf(e, t) {
  for (kf.set(e, t); kf.size > Of; ) {
    let e = kf.keys().next().value
    if (e === void 0) break
    kf.delete(e)
  }
}
function Nf(e) {
  let t = e.trim()
  if (!t) return !0
  let n = (t.match(/[A-Za-z]/g) || []).length,
    r = (t.match(/[\u4e00-\u9fff]/g) || []).length
  return n >= 8 && n > r * 2
}
async function Pf(e, t) {
  let n = String(e || ``).trim()
  if (!n) return ``
  if (Nf(n)) return n
  let r = jf(n)
  if (r) return r
  try {
    let e = await fetch(Af, {
      method: `POST`,
      headers: { 'Content-Type': `application/json`, Accept: `application/json` },
      body: JSON.stringify({ text: n.slice(0, 500), target: `en` }),
      credentials: `same-origin`,
      signal: t,
    })
    if (!e.ok) return ``
    let r = await e.json(),
      i = r.data && typeof r.data == `object` ? r.data : r,
      a = String(i.translation || i.text || i.en || ``).trim()
    return a ? (Mf(n, a), a) : ``
  } catch {
    return ``
  }
}
function Ff(e, t, n) {
  let r = Math.max(1, n?.concurrency ?? 2),
    i = 0,
    a = async () => {
      for (; i < e.length; ) {
        if (n?.signal?.aborted) return
        let r = i
        i += 1
        let a = e[r]
        if (!a) continue
        let o = await Pf(a, n?.signal)
        if (n?.signal?.aborted) return
        o && t(r, o)
      }
    }
  Promise.all(Array.from({ length: r }, () => a()))
}
var If = /[。！？；.!?]\s*|\n+/,
  Lf = /[，、,]\s*/
function Rf(e, t) {
  if (!t.earlyClause) return []
  let n = t.earlyClauseMinLen ?? 8,
    r = (e || ``).trim()
  if (!r) return []
  let i = r
    .split(Lf)
    .map((e) => e.trim())
    .filter(Boolean)
  return i.length <= 1 ? [] : (Lf.test(r.slice(-2)) || /[，、,]$/.test(r) ? i : i.slice(0, -1)).filter((e) => e.length >= n)
}
function zf(e, t) {
  let n = e.trim()
  if (!n) return []
  if (n.length <= t) return [n]
  let r = [],
    i = n
  for (; i.length > t; ) {
    let e = t,
      n = i.lastIndexOf(`，`, t),
      a = i.lastIndexOf(` `, t)
    ;(n > t * 0.4 ? (e = n + 1) : a > t * 0.4 && (e = a + 1), r.push(i.slice(0, e).trim()), (i = i.slice(e).trim()))
  }
  return (i && r.push(i), r)
}
function Bf(e, t) {
  if (!e.length) return []
  let n = [],
    r = ``
  for (let i of e) {
    let e = i.trim()
    if (e) {
      if (!r) {
        r = e
        continue
      }
      r.length < t ? (r = `${r}${e}`) : (n.push(r), (r = e))
    }
  }
  return (r && n.push(r), n)
}
function Vf(e, t) {
  let n = t.map((e) => e.trim()).filter(Boolean),
    r = []
  for (let t of e) {
    let e = (t || ``).trim()
    if (e && !n.includes(e)) {
      for (let t of [...n].sort((e, t) => t.length - e.length))
        if (e.startsWith(t) && e.length > t.length) e = e.slice(t.length).trim()
        else if (e === t) {
          e = ``
          break
        }
      !e || n.includes(e) || r.includes(e) || r.push(e)
    }
  }
  return r
}
function Hf(e, t) {
  let n = t?.minLen ?? 6,
    r = t?.maxLen ?? 120,
    i = (e || ``).trim()
  if (!i) return []
  let a = i
      .split(If)
      .map((e) => e.trim())
      .filter(Boolean),
    o = If.test(i.slice(-2)) || /[。！？；.!?]$/.test(i) ? a : a.slice(0, -1),
    s = [...Rf(i, t || {})]
  for (let e of o) s.some((t) => e.startsWith(t) || t.startsWith(e)) || s.push(e)
  if (!s.length) return []
  let c = []
  for (let e of s) c.push(...zf(e, r))
  return Bf(c, n)
}
function Uf(e, t) {
  let n = t?.minLen ?? 6,
    r = t?.maxLen ?? 120,
    i = (e || ``).trim()
  if (!i) return []
  let a = i
    .split(If)
    .map((e) => e.trim())
    .filter(Boolean)
  if (!a.length) return [i]
  let o = []
  for (let e of a) o.push(...zf(e, r))
  let s = Bf(o, n)
  return s.length ? s : [i]
}
function Wf(e) {
  let t = [],
    n = !1,
    r = (e) => {
      let n = Vf(e, t)
      return (n.length && (t = [...t, ...n]), n)
    },
    i = (r) => {
      let i = e?.firstChunkLen ?? 0
      if (!i || n || t.length || Hf(r, e).length) return []
      let a = (r || ``).trim()
      return a.length < i ? [] : ((n = !0), [a.slice(0, i)])
    }
  return {
    feed(t) {
      let n = r(Hf(t, e))
      return n.length ? n : r(i(t))
    },
    finish(t) {
      return r(Uf(t, e))
    },
    reset() {
      ;((t = []), (n = !1))
    },
  }
}
var Gf = `xc_corp_proactive_intro`,
  Kf = `xc-corp-intro-done:`,
  qf = `/api/agent/butler/corp-tts`
function Jf() {
  try {
    let e = localStorage.getItem(Gf)
    return !(e === `0` || e === `false`)
  } catch {
    return !0
  }
}
function Yf(e) {
  try {
    localStorage.setItem(Gf, e ? `1` : `0`)
  } catch {}
}
function Xf(e) {
  try {
    return sessionStorage.getItem(Kf + e) === `1`
  } catch {
    return !1
  }
}
function Zf(e) {
  try {
    sessionStorage.setItem(Kf + e, `1`)
  } catch {}
}
function Qf(e, t) {
  let n = (e || ``).replace(/\s+/g, ` `).trim()
  return n.length <= t ? n : `${n.slice(0, Math.max(0, t - 1))}…`
}
function $f(e) {
  let t = Cu(e),
    n = wu(t),
    r = Qf((n.title || ``).split(`|`)[0] || n.pageId, 24),
    i = Qf(n.summary || n.description || ``, 72),
    a = (n.highlights || []).slice(0, 2).join(`、`),
    o = a ? Qf(`这页重点：${a}。`, 40) : ``
  return {
    pageId: t,
    text: Qf(`嗨，我是小C。你现在在「${r}」。${i}${o ? ` ${o}` : ``} 想细聊直接跟我说，或点快捷问题就行。`, 160),
  }
}
function ep() {
  if (typeof window > `u` || !window.matchMedia) return !1
  try {
    return window.matchMedia(`(prefers-reduced-motion: reduce)`).matches
  } catch {
    return !1
  }
}
var tp = null,
  np = null,
  rp = 0
function ip() {
  if (!(typeof window > `u`)) {
    if (tp) {
      try {
        ;(tp.pause(), tp.removeAttribute(`src`), tp.load())
      } catch {}
      tp = null
    }
    ;(np?.abort(), (np = null), Ef(rp))
  }
}
async function ap(e) {
  let t = await fetch(qf, {
    method: `POST`,
    headers: { 'Content-Type': `application/json`, Accept: `application/json` },
    body: JSON.stringify({ text: e }),
    credentials: `same-origin`,
  })
  if (!t.ok) return null
  let n = {}
  try {
    n = await t.json()
  } catch {
    return null
  }
  let r = (n.data && typeof n.data == `object` ? n.data : n).audioBase64
  return typeof r == `string` && r.startsWith(`data:`) ? r : null
}
function op(e, t) {
  return new Promise((n) => {
    if (!Cf(t)) {
      n()
      return
    }
    let r = new Audio(e)
    tp = r
    let i = () => {
      ;(tp === r && (tp = null), n())
    }
    ;((r.onended = i), (r.onerror = i), r.play().catch(i))
  })
}
function sp(e) {
  if (typeof window > `u` || !e.trim() || ep()) return Promise.resolve()
  ip()
  let t = e.trim(),
    n = Uf(t),
    r = n.length ? n : [t]
  ;((np = new AbortController()), (rp = Sf(r)))
  let i = rp
  return (
    Ff(
      r,
      (e, t) => {
        Cf(i) && Tf(e, t, i)
      },
      { signal: np.signal, concurrency: 2 },
    ),
    wf(0, i),
    (async () => {
      try {
        let e = new Map(),
          t = (t) => (e.has(t) || e.set(t, ap(r[t])), e.get(t))
        ;(t(0), r.length > 1 && t(1))
        for (let e = 0; e < r.length; e += 1) {
          if (!Cf(i)) return
          ;(wf(e, i), e + 1 < r.length && t(e + 1))
          let n = await t(e)
          !n || !Cf(i) || (await op(n, i))
        }
      } catch {
      } finally {
        ;(Ef(i), (np = null))
      }
    })()
  )
}
var cp = { class: `perm-card` },
  lp = { id: `perm-title`, class: `perm-title` },
  up = { class: `perm-list` },
  dp = { class: `perm-note` },
  fp = { class: `perm-actions` },
  pp = br({
    __name: `AgentPermissionDialog`,
    props: { corpMode: { type: Boolean, default: !1 } },
    emits: [`agree`, `dismiss`],
    setup(e) {
      return (t, n) => (
        H(),
        U(
          `div`,
          {
            class: `perm-overlay`,
            role: `dialog`,
            'aria-modal': `true`,
            'aria-labelledby': `perm-title`,
            onClick: (n[2] ||= ds((e) => t.$emit(`dismiss`), [`self`])),
          },
          [
            W(`div`, cp, [
              (n[9] ||= Ca(
                `<div class="perm-icon" data-v-15ca9138><svg width="24" height="24" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" data-v-15ca9138><rect x="3" y="4" width="10" height="7" rx="1.5" data-v-15ca9138></rect><circle cx="6" cy="7.5" r="0.75" fill="currentColor" stroke="none" data-v-15ca9138></circle><circle cx="10" cy="7.5" r="0.75" fill="currentColor" stroke="none" data-v-15ca9138></circle><path d="M6 11v1.5M10 11v1.5M5 4V2.5M11 4V2.5" data-v-15ca9138></path></svg></div>`,
                1,
              )),
              W(`h2`, lp, F(e.corpMode ? `小C — 隐私提示` : `AI 数字管家 — 隐私提示`), 1),
              (n[10] ||= W(`p`, { class: `perm-sub` }, `为了提供更好的服务，AI 助手需要：`, -1)),
              W(`ul`, up, [
                e.corpMode
                  ? (H(),
                    U(
                      V,
                      { key: 0 },
                      [
                        (n[3] ||= W(`li`, null, `📄 读取当前页面内容，以便介绍本页能做什么`, -1)),
                        (n[4] ||= W(`li`, null, `🔊 同意后可用语音简短介绍本页（可随时在面板关闭）`, -1)),
                        (n[5] ||= W(`li`, null, `💬 回答产品、案例与预约咨询相关问题`, -1)),
                      ],
                      64,
                    ))
                  : (H(),
                    U(
                      V,
                      { key: 1 },
                      [
                        (n[6] ||= W(`li`, null, `📊 记录您的使用习惯，以便主动建议`, -1)),
                        (n[7] ||= W(`li`, null, `📄 读取当前页面内容，以便理解上下文`, -1)),
                        (n[8] ||= W(`li`, null, `🖱️ 代替您执行操作，提高使用效率`, -1)),
                      ],
                      64,
                    )),
              ]),
              W(
                `p`,
                dp,
                F(
                  e.corpMode
                    ? `语音介绍可在悬浮窗随时关闭；对话仅用于本站咨询体验，不会分享给第三方。`
                    : `所有数据仅用于改善您的使用体验，不会分享给第三方。`,
                ),
                1,
              ),
              W(`div`, fp, [
                W(
                  `button`,
                  {
                    type: `button`,
                    class: `perm-btn perm-btn--primary`,
                    onClick: (n[0] ||= (e) => t.$emit(`agree`)),
                  },
                  ` 同意并继续 `,
                ),
                W(
                  `button`,
                  {
                    type: `button`,
                    class: `perm-btn perm-btn--ghost`,
                    onClick: (n[1] ||= (e) => t.$emit(`dismiss`)),
                  },
                  ` 稍后再说 `,
                ),
              ]),
            ]),
          ],
        )
      )
    },
  }),
  mp = (e, t) => {
    let n = e.__vccOpts || e
    for (let [e, r] of t) n[e] = r
    return n
  },
  hp = mp(pp, [[`__scopeId`, `data-v-15ca9138`]])
function gp(e, t = 3) {
  let n = Math.max(0, Math.floor(t)),
    r = Math.max(0, e),
    i = Math.min(r, n),
    a = r - i
  return { stripGeneratedCount: i, overflowGeneratedCount: a, overflowCount: a }
}
function _p(e, t = 5) {
  let n = Math.max(0, Math.floor(t)),
    r = Math.max(0, e),
    i = Math.min(r, n)
  return { visibleCount: i, overflowCount: r - i }
}
var vp = Qs(`butlerWorkbenchTray`, () => {
    let e = z([]),
      t = z([]),
      n = z(3),
      r = z({}),
      i = q(() => {
        let r = gp(t.value.length, n.value),
          i = _p(e.value.length)
        return {
          stripAttachmentCount: i.visibleCount,
          stripGeneratedCount: r.stripGeneratedCount,
          overflowAttachmentCount: i.overflowCount,
          overflowGeneratedCount: r.overflowGeneratedCount,
          overflowCount: r.overflowCount + i.overflowCount,
        }
      }),
      a = q(() => e.value.slice(0, i.value.stripAttachmentCount)),
      o = q(() => t.value.slice(0, i.value.stripGeneratedCount)),
      s = q(() => e.value.slice(i.value.stripAttachmentCount)),
      c = q(() => t.value.slice(i.value.stripGeneratedCount)),
      l = q(() => i.value.overflowCount),
      u = q(() => l.value > 0 || t.value.length > 0 || e.value.length > 0)
    function d(r) {
      ;(r.attachments && (e.value = r.attachments),
        r.generated && (t.value = r.generated),
        r.maxVisible != null && (n.value = r.maxVisible))
    }
    function f(e) {
      r.value = { ...r.value, ...e }
    }
    function p() {
      r.value = {}
    }
    return {
      attachments: e,
      generated: t,
      maxVisible: n,
      actions: r,
      stripPlan: i,
      stripAttachments: a,
      stripGenerated: o,
      overflowAttachments: s,
      overflowGenerated: c,
      overflowCount: l,
      hasTrayContent: u,
      setWorkbenchFiles: d,
      registerActions: f,
      clearActions: p,
    }
  }),
  yp = `workbench_personal_settings_v1`,
  bp = [`帮我把今天的工作拆成步骤`, `帮我分析一个自动化流程`, `帮我写一段客户沟通话术`]
function xp() {
  return {
    theme: `dark`,
    fontPx: 15,
    memory: ``,
    suggestions: bp.slice(),
    ttsEngine: `auto`,
    ttsEdgeVoice: `zh-CN-XiaoxiaoNeural`,
    ttsVoiceName: ``,
    ttsRate: 1,
    voiceSpeechMode: `unified`,
  }
}
function Sp() {
  try {
    let e = localStorage.getItem(yp)
    if (!e) return xp()
    let t = JSON.parse(e) || {},
      n = xp(),
      r = Number(t.ttsRate),
      i = Number.isFinite(r) ? Math.max(0.6, Math.min(1.6, r)) : n.ttsRate,
      a = typeof t.ttsVoiceName == `string` ? t.ttsVoiceName.slice(0, 256) : n.ttsVoiceName,
      o = t.ttsEngine === `edge-online` ? `edge-online` : t.ttsEngine === `auto` || t.ttsEngine === `browser` ? `auto` : n.ttsEngine,
      s = typeof t.ttsEdgeVoice == `string` && t.ttsEdgeVoice.trim() ? t.ttsEdgeVoice.trim().slice(0, 120) : n.ttsEdgeVoice,
      c =
        t.voiceSpeechMode === `cascade` || t.voiceSpeechMode === `s2s` || t.voiceSpeechMode === `unified`
          ? t.voiceSpeechMode
          : n.voiceSpeechMode
    return (
      t.voiceSpeechMode === `s2s` && (c = `unified`),
      {
        theme: t.theme === `light` || t.theme === `auto` ? t.theme : `dark`,
        fontPx: Number.isFinite(Number(t.fontPx)) ? Math.max(13, Math.min(20, Number(t.fontPx))) : n.fontPx,
        memory: typeof t.memory == `string` ? t.memory.slice(0, 600) : ``,
        suggestions:
          Array.isArray(t.suggestions) && t.suggestions.length
            ? t.suggestions.filter((e) => typeof e == `string` && e.trim()).slice(0, 6)
            : n.suggestions,
        ttsEngine: o,
        ttsEdgeVoice: s,
        ttsVoiceName: a,
        ttsRate: i,
        voiceSpeechMode: c,
      }
    )
  } catch {
    return xp()
  }
}
function Cp(e) {
  return e === `light` || (e === `auto` && typeof window < `u` && window.matchMedia?.(`(prefers-color-scheme: light)`).matches)
    ? `light`
    : `dark`
}
function wp() {
  let e = z(!1),
    t = null
  function n() {
    let t = document.documentElement.dataset.workbenchTheme
    if (t === `light` || t === `dark`) {
      e.value = t === `light`
      return
    }
    e.value = Cp(Sp().theme) === `light`
  }
  return (
    Fr(() => {
      ;(n(),
        (t = new MutationObserver(n)),
        t.observe(document.documentElement, {
          attributes: !0,
          attributeFilter: [`data-workbench-theme`],
        }))
    }),
    Rr(() => {
      t?.disconnect()
    }),
    { isLightTheme: e, syncThemeFromDocument: n }
  )
}
var Tp = { class: `butler-ball__logo-wrap`, 'aria-hidden': `true` },
  Ep = [`src`, `width`, `height`],
  Dp = [`title`],
  Op = { key: 1, class: `butler-ball__badge` },
  kp = { key: 2, class: `butler-ball__hint` },
  Ap = 6,
  jp = 64,
  Mp = 64,
  Np = 82,
  Pp = 82,
  Fp = mp(
    br({
      __name: `FloatingAgentBall`,
      props: {
        isSpeaking: { type: Boolean },
        forceLight: { type: Boolean },
        corpMode: { type: Boolean },
        maleAvatar: { type: Boolean },
      },
      setup(e) {
        let t = tu(),
          n = vp(),
          { isOpen: r, consentGiven: i, unreadCount: a, position: o } = $s(t),
          { overflowCount: s } = $s(n),
          c = e,
          l = q(() => (c.maleAvatar ? `ai-butler-male-avatar-v1.jpg` : `ai-butler-female-avatar-v1.png`)),
          u = q(() => (c.corpMode ? `/corp-butler/ai-butler-female-avatar-v1.png` : `/corp-butler/${l.value}`)),
          d = z(null),
          f = !1,
          p = 0,
          m = 0,
          h = 0,
          g = 0,
          _ = !1,
          v = z(!1),
          y = q(() => o.value ?? { x: 0, y: 0 }),
          b = q(() => ({ transform: `translate(${y.value.x}px, ${y.value.y}px)` })),
          { isLightTheme: x } = wp(),
          S = q(() => !!c.forceLight)
        function C(e) {
          e.button === 0 &&
            ((f = !0),
            (_ = !1),
            (h = e.clientX),
            (g = e.clientY),
            (p = e.clientX - y.value.x),
            (m = e.clientY - y.value.y),
            d.value?.setPointerCapture(e.pointerId),
            window.addEventListener(`pointermove`, w),
            window.addEventListener(`pointerup`, T))
        }
        function w(e) {
          if (!f) return
          let n = e.clientX - h,
            r = e.clientY - g
          if (Math.hypot(n, r) < Ap) return
          ;((_ = !0), (v.value = !0))
          let i = e.clientX - p,
            a = e.clientY - m,
            o = c.corpMode ? Mp : jp,
            s = c.corpMode ? Pp : Np,
            l = window.innerWidth - o - 8,
            u = window.innerHeight - s - 8,
            d = Math.max(8, Math.min(l, i)),
            y = Math.max(8, Math.min(u, a))
          if (c.corpMode) {
            let e = pu(d, y)
            t.savePosition(e.x, e.y)
            return
          }
          t.savePosition(d, y)
        }
        function T(e) {
          ;((f = !1), (v.value = !1), window.removeEventListener(`pointermove`, w), window.removeEventListener(`pointerup`, T))
          try {
            d.value?.releasePointerCapture(e.pointerId)
          } catch {}
        }
        function E() {
          if (!t.consentGiven) {
            t.showPermissionDialog = !0
            return
          }
          t.isOpen ? t.closePanel() : t.openPanel()
        }
        function D() {
          if (_) {
            _ = !1
            return
          }
          E()
        }
        return (
          Rr(() => {
            ;(window.removeEventListener(`pointermove`, w), window.removeEventListener(`pointerup`, T))
          }),
          (e, t) => (
            H(),
            U(
              `button`,
              {
                ref_key: `ballRef`,
                ref: d,
                type: `button`,
                class: P([
                  `butler-ball`,
                  {
                    'butler-ball--light': S.value || B(x),
                    'butler-ball--consent-pending': !B(i),
                    'butler-ball--open': B(r),
                    'butler-ball--corp-anchor': c.corpMode,
                    'butler-ball--dragging': v.value,
                    'butler-ball--speaking': !!c.isSpeaking,
                  },
                ]),
                style: oe(b.value),
                'aria-label': `小C助理`,
                title: `小C助理`,
                onClick: ds(D, [`stop`]),
                onPointerdown: C,
              },
              [
                W(`span`, Tp, [
                  W(
                    `img`,
                    {
                      class: `butler-ball__logo`,
                      src: u.value,
                      alt: ``,
                      draggable: `false`,
                      width: c.corpMode ? 46 : 38,
                      height: c.corpMode ? 46 : 38,
                      decoding: `async`,
                    },
                    null,
                    8,
                    Ep,
                  ),
                ]),
                (t[0] ||= W(`span`, { class: `butler-ball__label` }, `小C助理`, -1)),
                B(s) > 0 && !B(r)
                  ? (H(),
                    U(
                      `span`,
                      {
                        key: 0,
                        class: `butler-ball__badge butler-ball__badge--files`,
                        title: `${B(s)} 个文件已收纳`,
                      },
                      F(B(s) > 9 ? `9+` : B(s)),
                      9,
                      Dp,
                    ))
                  : B(a) > 0 && !B(r)
                    ? (H(), U(`span`, Op, F(B(a) > 9 ? `9+` : B(a)), 1))
                    : K(``, !0),
                B(i) ? K(``, !0) : (H(), U(`span`, kp, `点我启用`)),
              ],
              38,
            )
          )
        )
      },
    }),
    [[`__scopeId`, `data-v-fc68ec7f`]],
  ),
  Ip = `/corp-butler/`
function Lp() {
  if (typeof navigator > `u`) return !1
  let e = navigator.userAgent,
    t = /iPad|iPhone|iPod/.test(e) || (navigator.platform === `MacIntel` && navigator.maxTouchPoints > 1),
    n = /Android/i.test(e)
  return t || n
}
function Rp(e) {
  if (!e.length) return 0
  let t = 0
  for (let n = 0; n < e.length; n++) t += e[n] * e[n]
  return Math.sqrt(t / e.length)
}
var zp = class {
  stream = null
  ownsStream = !0
  ctx = null
  source = null
  workletNode = null
  processor = null
  analyser = null
  mute = null
  _active = !1
  rafId = 0
  resumeTimer = null
  _useWorklet = !1
  _sampleRate = 16e3
  _pcmFrames = 0
  _peakLevel = 0
  _handlers = null
  get sampleRate() {
    return this._sampleRate
  }
  get active() {
    return this._active
  }
  get pcmFrames() {
    return this._pcmFrames
  }
  get peakLevel() {
    return this._peakLevel
  }
  setHandlers(e) {
    ;((this._handlers = e), e.onAudioLevel && this._active && this.restartLevelLoop())
  }
  async wake() {
    await this.ensureContextRunning()
  }
  async ensureContextRunning() {
    if (this.ctx && this.ctx.state === `suspended`)
      try {
        await this.ctx.resume()
      } catch {}
  }
  _smoothLevel = 0
  _lastLevelEmit = 0
  emitLevelFromPcm(e) {
    this._smoothLevel = this._smoothLevel * 0.6 + e * 0.4
    let t = performance.now()
    t - this._lastLevelEmit < 32 || ((this._lastLevelEmit = t), this._handlers?.onAudioLevel?.(this._smoothLevel))
  }
  async start(e, t) {
    if (this._active) {
      ;(this.setHandlers(e), await this.wake())
      return
    }
    if (((this._handlers = e), t)) ((this.stream = t), (this.ownsStream = !1))
    else {
      if (!navigator.mediaDevices?.getUserMedia) throw Error(`当前浏览器不支持麦克风采集，请使用 HTTPS 访问。`)
      try {
        this.stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            echoCancellation: !0,
            noiseSuppression: !0,
            autoGainControl: !0,
          },
        })
      } catch {
        this.stream = await navigator.mediaDevices.getUserMedia({ audio: !0 })
      }
      this.ownsStream = !0
    }
    if (!this.stream?.getAudioTracks().some((e) => e.readyState === `live`)) throw Error(`麦克风不可用，请检查权限或是否被其他应用占用。`)
    ;((this.ctx = new AudioContext()),
      await this.ensureContextRunning(),
      (this._sampleRate = this.ctx.sampleRate || 16e3),
      (this._pcmFrames = 0),
      (this._peakLevel = 0),
      (this.source = this.ctx.createMediaStreamSource(this.stream)),
      (this.analyser = this.ctx.createAnalyser()),
      (this.analyser.fftSize = 256),
      (this.mute = this.ctx.createGain()),
      (this.mute.gain.value = 0),
      this.mute.connect(this.ctx.destination))
    let n = (e) => {
        if (!this._active) return
        ;(this.ensureContextRunning(), (this._pcmFrames += 1))
        let t = Rp(e),
          n = Math.min(1, t * 5)
        ;(n > this._peakLevel && (this._peakLevel = n), this.emitLevelFromPcm(n), this._handlers?.onAudioData(e))
      },
      r = () => {
        ;((this.processor = this.ctx.createScriptProcessor(4096, 1, 1)),
          (this.processor.onaudioprocess = (e) => {
            n(new Float32Array(e.inputBuffer.getChannelData(0)))
          }),
          this.source.connect(this.processor),
          this.processor.connect(this.analyser),
          this.analyser.connect(this.mute),
          (this._useWorklet = !1))
      }
    if (Lp()) r()
    else
      try {
        ;(await this.ctx.audioWorklet.addModule(`${Ip}vosk/pcm-processor.worklet.js`),
          (this.workletNode = new AudioWorkletNode(this.ctx, `pcm-processor`)),
          (this.workletNode.port.onmessage = (e) => {
            n(e.data)
          }),
          this.source.connect(this.workletNode),
          this.workletNode.connect(this.analyser),
          this.analyser.connect(this.mute),
          (this._useWorklet = !0))
      } catch {
        r()
      }
    if (
      ((this._active = !0),
      (this.resumeTimer = setInterval(() => {
        this.ensureContextRunning()
      }, 800)),
      e.onAudioLevel && this.restartLevelLoop(),
      await new Promise((e) => setTimeout(e, 500)),
      await this.ensureContextRunning(),
      this._pcmFrames < 1)
    )
      throw Error(`麦克风已打开但未收到音频数据，请检查权限后重试。`)
  }
  restartLevelLoop() {
    if (((this.rafId &&= (cancelAnimationFrame(this.rafId), 0)), !this._handlers?.onAudioLevel || !this._active)) return
    let e = () => {
      if (!this._active) {
        this.rafId = 0
        return
      }
      if (this.analyser) {
        this.ensureContextRunning()
        let e = new Uint8Array(this.analyser.frequencyBinCount)
        this.analyser.getByteTimeDomainData(e)
        let t = 0
        for (let n = 0; n < e.length; n++) {
          let r = (e[n] - 128) / 128
          t += r * r
        }
        let n = Math.sqrt(t / e.length),
          r = Math.min(1, n * 5)
        ;(r > this._peakLevel && (this._peakLevel = r), this.emitLevelFromPcm(r))
      }
      this.rafId = requestAnimationFrame(e)
    }
    this.rafId = requestAnimationFrame(e)
  }
  startLevelLoop() {
    this.restartLevelLoop()
  }
  stop() {
    ;((this._active = !1),
      (this.resumeTimer &&= (clearInterval(this.resumeTimer), null)),
      (this.rafId &&= (cancelAnimationFrame(this.rafId), 0)))
    try {
      this.workletNode?.disconnect()
    } catch {}
    try {
      this.processor?.disconnect()
    } catch {}
    try {
      this.analyser?.disconnect()
    } catch {}
    try {
      this.mute?.disconnect()
    } catch {}
    try {
      this.source?.disconnect()
    } catch {}
    try {
      this.ctx?.close()
    } catch {}
    if (this.ownsStream)
      try {
        this.stream?.getTracks().forEach((e) => e.stop())
      } catch {}
    ;((this.workletNode = null),
      (this.processor = null),
      (this.source = null),
      (this.analyser = null),
      (this.mute = null),
      (this.ctx = null),
      (this.stream = null),
      (this._pcmFrames = 0),
      (this._peakLevel = 0),
      (this._smoothLevel = 0),
      (this._lastLevelEmit = 0),
      (this._handlers = null))
  }
}
function Bp(e) {
  let t = new Int16Array(e.length)
  for (let n = 0; n < e.length; n++) {
    let r = Math.max(-1, Math.min(1, e[n]))
    t[n] = r < 0 ? r * 32768 : r * 32767
  }
  return t
}
function Vp(e, t, n = 16e3) {
  if (!e.length || t === n) return e
  let r = t / n,
    i = Math.max(1, Math.floor(e.length / r)),
    a = new Float32Array(i)
  for (let t = 0; t < i; t++) {
    let n = t * r,
      i = Math.floor(n),
      o = Math.min(i + 1, e.length - 1),
      s = n - i
    a[t] = e[i] * (1 - s) + e[o] * s
  }
  return a
}
var Hp = {
  network: `语音服务连接失败，正在尝试其他方案…`,
  'not-allowed': `麦克风权限被拒绝，请在浏览器设置中允许。`,
  'no-speech': `未检测到语音，请再试一次或使用文字输入。`,
  'audio-capture': `未找到麦克风，请检查设备。`,
  aborted: `语音识别已取消。`,
}
function Up() {
  if (typeof navigator > `u`) return !1
  let e = navigator.userAgent
  return /iPad|iPhone|iPod/.test(e) || (e.includes(`Mac`) && `ontouchend` in document)
}
var Wp = class e {
    id = `webspeech`
    label = `浏览器语音识别`
    rec = null
    levelCapture = null
    _onResult = null
    _onError = null
    _onAudioLevel = null
    _finalText = ``
    _lastInterim = ``
    _stopped = !1
    _continuous = !0
    _restartTimer = null
    _restartCount = 0
    _restartFailures = 0
    static IOS_RESTART_DELAY_MS = 280
    static MAX_IOS_RESTARTS = 200
    static MAX_IOS_RESTART_FAILURES = 8
    isAvailable() {
      if (typeof window > `u`) return !1
      let e = window
      return !!(e.SpeechRecognition || e.webkitSpeechRecognition)
    }
    isLoading() {
      return !1
    }
    async start(e, t, n, r) {
      ;((this._onResult = e),
        (this._onError = t),
        (this._onAudioLevel = n ?? null),
        (this._finalText = ``),
        (this._lastInterim = ``),
        (this._stopped = !1),
        (this._restartCount = 0),
        (this._restartFailures = 0),
        this.clearRestartTimer())
      let i = window,
        a = i.SpeechRecognition || i.webkitSpeechRecognition
      if (!a) {
        t(`当前浏览器不支持语音识别，请使用其他识别方案。`)
        return
      }
      let o = new a()
      ;((o.lang = `zh-CN`),
        (o.interimResults = !0),
        (this._continuous = !Up()),
        (o.continuous = this._continuous),
        (o.onresult = (t) => {
          if (this._stopped) return
          let n = ``
          for (let e = t.resultIndex; e < t.results.length; e++) n += t.results[e][0]?.transcript || ``
          let r = n.trim()
          ;(r && ((this._lastInterim = r), this._onAudioLevel?.(0.08)),
            t.results[t.results.length - 1]?.isFinal
              ? ((this._finalText = r), e({ text: r, isFinal: !0 }))
              : r && e({ text: r, isFinal: !1 }))
        }),
        (o.onerror = (e) => {
          if (this._stopped) return
          let n = e?.error
          n === `no-speech` || n === `aborted` || t(n ? Hp[n] || `语音识别失败：${n}` : `语音识别失败`)
        }),
        (o.onend = () => {
          if (this._stopped) return
          let t = (this._finalText || this._lastInterim).trim()
          ;(t && !this._finalText && ((this._finalText = t), e({ text: t, isFinal: !0 })),
            this._onAudioLevel?.(0),
            !this._continuous && this.rec === o && !this._stopped && this.scheduleIosRestart(o))
        }),
        (this.rec = o))
      try {
        if (!Up() && n)
          try {
            ;((this.levelCapture = new zp()),
              await this.levelCapture.start({
                onAudioData: () => {},
                onAudioLevel: (e) => {
                  this._stopped || n(e)
                },
              }))
          } catch {
            this.levelCapture = null
          }
        ;(o.start(), r?.())
      } catch (e) {
        t(e instanceof Error ? e.message : String(e))
      }
    }
    clearRestartTimer() {
      this._restartTimer &&= (clearTimeout(this._restartTimer), null)
    }
    scheduleIosRestart(t) {
      if (this._restartTimer || this._restartCount >= e.MAX_IOS_RESTARTS || this._restartFailures >= e.MAX_IOS_RESTART_FAILURES) return
      let n = Math.min(this._restartFailures * 120, 1200)
      this._restartTimer = setTimeout(() => {
        if (((this._restartTimer = null), !(this._stopped || this.rec !== t)))
          try {
            ;(t.start(), (this._restartCount += 1), (this._restartFailures = 0))
          } catch {
            this._restartFailures += 1
          }
      }, e.IOS_RESTART_DELAY_MS + n)
    }
    async flushUtterance() {
      let e = (this._finalText || this._lastInterim).trim()
      return (
        e && !this._finalText && ((this._finalText = e), this._onResult?.({ text: e, isFinal: !0 })),
        (this._finalText = ``),
        (this._lastInterim = ``),
        e
      )
    }
    async stop() {
      ;((this._stopped = !0), this.levelCapture?.stop(), (this.levelCapture = null))
      try {
        this.rec?.stop?.()
      } catch {}
      let e = this._finalText || this._lastInterim
      return ((this.rec = null), (this._onAudioLevel = null), e)
    }
    abort() {
      ;((this._stopped = !0), this.clearRestartTimer(), this.levelCapture?.stop(), (this.levelCapture = null))
      try {
        this.rec?.abort?.()
      } catch {}
      ;((this.rec = null), (this._onAudioLevel = null))
    }
  },
  Gp = null,
  Kp = null,
  qp = null
function Jp(e) {
  return !!e?.getAudioTracks().some((e) => e.readyState === `live`)
}
function Yp() {
  return Jp(Kp) ? Kp : null
}
function Xp() {
  try {
    Kp?.getTracks().forEach((e) => e.stop())
  } catch {}
  Kp = null
}
async function Zp(e, t) {
  if (((qp = e), Gp?.active)) return (Gp.setHandlers(e), Gp.wake(), Gp)
  let n = Yp()
  return (
    !n && t && ((n = t instanceof MediaStream ? t : await t), Jp(n) && (Kp = n)),
    (Gp = new zp()),
    await Gp.start({ onAudioData: (e) => qp?.onAudioData(e), onAudioLevel: (e) => qp?.onAudioLevel?.(e) }, n ?? void 0),
    Gp.active,
    Gp.wake(),
    Gp
  )
}
function Qp() {
  return Gp?.active ? Gp : null
}
function $p() {
  ;(Gp?.stop(), (Gp = null), (qp = null), Xp())
}
function em() {
  Gp?.wake()
}
var tm = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i
function nm() {
  return typeof navigator > `u` ? !1 : tm.test(navigator.userAgent)
}
function rm(e) {
  let t = String(e.text ?? ``).trim()
  if (t) return t
  let n = e.stamp_sents
  return Array.isArray(n) && n.length
    ? n
        .map((e) => String(e.text_seg || ``).replace(/\s+/g, ``))
        .join(``)
        .trim()
    : ``
}
var im = class e {
    id = `funasr`
    label = `FunASR 服务端`
    ws = null
    capture = null
    _onResult = null
    _onError = null
    _onReady = null
    _finalText = ``
    _onlinePartial = ``
    _offlineFinal = ``
    _aborted = !1
    _flushWaiter = null
    _flushing = !1
    _closeNotifyTimer = null
    _gotServerMsg = !1
    _pcmChunksSent = 0
    _sessionConfigured = !1
    _preConnectPcm = []
    static wsOpenTimeoutMs() {
      return nm() ? 18e3 : 1e4
    }
    static serverReadyTimeoutMs() {
      return nm() ? 2e4 : 1e4
    }
    _audioBuffer = []
    _audioBufferLen = 0
    _SEND_CHUNK_SAMPLES = 960
    _persistentMic = !1
    _ownsCapture = !0
    isAvailable() {
      return typeof window < `u` && typeof WebSocket < `u`
    }
    isLoading() {
      return !1
    }
    async start(e, t, n, r, i, a, o) {
      ;((this._onResult = e),
        (this._onError = t),
        (this._onReady = r ?? null),
        (this._aborted = !1),
        (this._persistentMic = !!o?.persistentMic),
        (this._ownsCapture = !this._persistentMic),
        (this._finalText = ``),
        (this._onlinePartial = ``),
        (this._offlineFinal = ``),
        (this._gotServerMsg = !1),
        (this._pcmChunksSent = 0),
        (this._sessionConfigured = !1),
        (this._preConnectPcm = []),
        this.clearCloseNotifyTimer())
      try {
        this._persistentMic
          ? (this.capture = await Zp({ onAudioData: (e) => this.onPcm(e), onAudioLevel: n ?? void 0 }, a))
          : ((this.capture = new zp()), await this.capture.start({ onAudioData: (e) => this.onPcm(e), onAudioLevel: n ?? void 0 }, a))
      } catch (e) {
        ;(this.cleanupWsOnly(), t(`麦克风启动失败：` + (e instanceof Error ? e.message : String(e))))
        return
      }
      if (this._aborted) {
        this.cleanupWsOnly()
        return
      }
      if ((i?.(), !(await this.connectWs(t)) || this._aborted)) {
        this.cleanupWsOnly()
        return
      }
      this._onReady?.()
    }
    onPcm(e) {
      if (!this._aborted) {
        if (!this._sessionConfigured) {
          ;(this._preConnectPcm.push(e), this._preConnectPcm.length > 200 && this._preConnectPcm.shift())
          return
        }
        this.sendPcmChunk(e)
      }
    }
    flushPreConnectPcm() {
      if (!this._preConnectPcm.length) return
      let e = this._preConnectPcm
      this._preConnectPcm = []
      for (let t of e) this.sendPcmChunk(t)
    }
    clearCloseNotifyTimer() {
      this._closeNotifyTimer &&= (clearTimeout(this._closeNotifyTimer), null)
    }
    async connectWs(t) {
      let n = (e) => (t(e), !1),
        r = this.buildWsUrl()
      if (!r) return n(`请先登录后再使用语音识别。`)
      try {
        this.ws = new WebSocket(r)
      } catch (e) {
        return n(`FunASR 连接失败：` + (e instanceof Error ? e.message : String(e)))
      }
      return (
        (this.ws.binaryType = `arraybuffer`),
        !(await new Promise((t) => {
          let n = setTimeout(() => {
            t(!1)
          }, e.wsOpenTimeoutMs())
          ;((this.ws.onopen = () => {
            ;(clearTimeout(n), t(!0))
          }),
            (this.ws.onerror = () => {
              ;(clearTimeout(n), t(!1))
            }))
        })) ||
        !this.ws ||
        this.ws.readyState !== WebSocket.OPEN
          ? n(`FunASR 服务未启动`)
          : !(await new Promise((n) => {
                let r = setTimeout(() => {
                    n(!1)
                  }, e.serverReadyTimeoutMs()),
                  i = this.ws,
                  a = (e) => {
                    ;(clearTimeout(r), n(e))
                  }
                ;((i.onmessage = (e) => {
                  if (!this._aborted)
                    try {
                      let n = typeof e.data == `string` ? JSON.parse(e.data) : e.data
                      if (n.type === `error`) {
                        ;(t(String(n.message || `FunASR 服务错误`)), a(!1))
                        return
                      }
                      n.type === `connected` && a(!0)
                    } catch {}
                }),
                  (i.onerror = () => a(!1)),
                  (i.onclose = () => a(!1)))
              })) ||
              !this.ws ||
              this.ws.readyState !== WebSocket.OPEN
            ? this._aborted
              ? !1
              : n(`FunASR 服务未启动`)
            : ((this.ws.onmessage = (e) => {
                if (!this._aborted) {
                  ;((this._gotServerMsg = !0), this.clearCloseNotifyTimer())
                  try {
                    let t = typeof e.data == `string` ? JSON.parse(e.data) : e.data
                    this.handleServerMessage(t)
                  } catch (t) {
                    console.warn(`[FunASR] parse error:`, t, `data:`, e.data)
                  }
                }
              }),
              (this.ws.onclose = () => {
                this._aborted ||
                  this._flushing ||
                  (this.clearCloseNotifyTimer(),
                  (this._closeNotifyTimer = setTimeout(() => {
                    ;((this._closeNotifyTimer = null),
                      !(this._aborted || this._flushing) &&
                        this.ws?.readyState !== WebSocket.OPEN &&
                        this._onError?.(`FunASR 服务连接中断`))
                  }, 2e3)))
              }),
              (this.ws.onerror = () => {
                if (!this._aborted)
                  try {
                    this.ws?.close()
                  } catch {}
              }),
              this.sendSessionConfig(),
              !0)
      )
    }
    sendSessionConfig() {
      ;((this._audioBuffer = []),
        (this._audioBufferLen = 0),
        this.ws?.send(
          JSON.stringify({
            mode: `2pass`,
            chunk_size: [5, 10, 5],
            chunk_interval: 10,
            encoder_chunk_look_back: 4,
            decoder_chunk_look_back: 0,
            wav_name: `mic`,
            wav_format: `pcm`,
            audio_fs: 16e3,
            is_speaking: !0,
            hotwords: `流式对话 流失 修茈 工作台 豆包 MODstore`,
            itn: !0,
          }),
        ),
        (this._sessionConfigured = !0),
        this.flushPreConnectPcm())
    }
    sendPcmChunk(e) {
      if (this.ws?.readyState !== WebSocket.OPEN) return
      let t = Vp(e, this.capture?.sampleRate ?? 16e3, 16e3)
      for (this._audioBuffer.push(t), this._audioBufferLen += t.length; this._audioBufferLen >= this._SEND_CHUNK_SAMPLES; ) {
        let e = new Float32Array(this._SEND_CHUNK_SAMPLES),
          t = 0
        for (; t < this._SEND_CHUNK_SAMPLES && this._audioBuffer.length > 0; ) {
          let n = this._audioBuffer[0],
            r = this._SEND_CHUNK_SAMPLES - t
          n.length <= r
            ? (e.set(n, t), (t += n.length), this._audioBuffer.shift())
            : (e.set(n.subarray(0, r), t), (this._audioBuffer[0] = n.subarray(r)), (t += r))
        }
        this._audioBufferLen = this._audioBuffer.reduce((e, t) => e + t.length, 0)
        let n = Bp(e)
        ;(this.ws.send(n.buffer.slice(n.byteOffset, n.byteOffset + n.byteLength)), (this._pcmChunksSent += 1))
      }
    }
    bestSegmentText() {
      return (this._offlineFinal || this._onlinePartial || this._finalText).trim()
    }
    signalEndOfSpeech() {
      if (
        !(this._aborted || this._flushing) &&
        !(!this.ws || this.ws.readyState !== WebSocket.OPEN) &&
        !(this._pcmChunksSent < 3 && !this.bestSegmentText())
      )
        try {
          ;(this.sendRemainingAudio(), this.ws.send(JSON.stringify({ is_speaking: !1 })))
        } catch {}
    }
    async flushUtterance() {
      let e = this.bestSegmentText()
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return e
      if (this._pcmChunksSent < 3 && !e) return ``
      this._flushing = !0
      let t = this._onlinePartial
      try {
        this.sendRemainingAudio()
        let e = await this.waitOfflineAfterSpeaking(!1)
        try {
          this.ws.send(JSON.stringify({ is_speaking: !0 }))
        } catch {}
        let n = (e || this._offlineFinal || t).trim()
        return ((this._finalText = ``), (this._onlinePartial = ``), (this._offlineFinal = ``), n)
      } finally {
        this._flushing = !1
      }
    }
    async stop() {
      if (
        (this._ownsCapture && (this.capture?.stop(), (this.capture = null)),
        this.ws?.readyState === WebSocket.OPEN && this._pcmChunksSent > 0)
      ) {
        this.sendRemainingAudio()
        let e = await this.waitOfflineAfterSpeaking(!0)
        return (this.cleanupWsOnly(), e || this._finalText)
      }
      let e = this._finalText
      return (this.cleanupWsOnly(), e)
    }
    handleServerMessage(e) {
      if (e.type === `error`) {
        this._onError?.(e.message || `FunASR 服务错误`)
        return
      }
      if (e.type === `connected`) return
      let t = rm(e),
        n = String(e.mode || ``),
        r = n.includes(`2pass-offline`) || n === `offline`,
        i = n.includes(`2pass-online`) || n === `online`,
        a = r,
        o = r ? `offline` : i ? `online` : `other`
      if (
        (t &&
          (r ? ((this._offlineFinal = t), (this._finalText = t)) : ((this._onlinePartial = t), this._flushing || (this._finalText = t)),
          this._onResult?.({ text: t, isFinal: a, segmentMode: o })),
        r || a)
      ) {
        let e = this._flushWaiter
        e && ((this._flushWaiter = null), e(t || this._offlineFinal || this._onlinePartial || this._finalText))
      }
    }
    sendRemainingAudio() {
      if (this._audioBufferLen <= 0 || this.ws?.readyState !== WebSocket.OPEN) return
      let e = new Float32Array(this._audioBufferLen),
        t = 0
      for (let n of this._audioBuffer) (e.set(n, t), (t += n.length))
      ;((this._audioBuffer = []), (this._audioBufferLen = 0))
      let n = Bp(e)
      try {
        ;(this.ws.send(n.buffer.slice(n.byteOffset, n.byteOffset + n.byteLength)),
          e.length >= this._SEND_CHUNK_SAMPLES && (this._pcmChunksSent += Math.floor(e.length / this._SEND_CHUNK_SAMPLES)))
      } catch {}
    }
    waitOfflineAfterSpeaking(e) {
      return new Promise((t) => {
        let n = setTimeout(
          () => {
            ;((this._flushWaiter = null), t(this.bestSegmentText()))
          },
          e ? 1e4 : 8e3,
        )
        this._flushWaiter = (e) => {
          ;(clearTimeout(n), t((e || this.bestSegmentText()).trim()))
        }
        try {
          this.ws?.send(JSON.stringify({ is_speaking: !1 }))
        } catch {
          ;(clearTimeout(n), (this._flushWaiter = null), t(this.bestSegmentText()))
        }
      })
    }
    abort() {
      ;((this._aborted = !0), (this._flushWaiter = null), this.clearCloseNotifyTimer(), this.cleanupWsOnly())
    }
    cleanupWsOnly() {
      ;(this.clearCloseNotifyTimer(),
        (this._flushWaiter = null),
        (this._preConnectPcm = []),
        (this._sessionConfigured = !1),
        (this._audioBuffer = []),
        (this._audioBufferLen = 0),
        this._ownsCapture ? this.capture?.stop() : this._persistentMic ? (this.capture = Qp()) : (this.capture = null),
        this._ownsCapture && (this.capture = null))
      try {
        this.ws?.close()
      } catch {}
      this.ws = null
    }
    cleanup() {
      this.cleanupWsOnly()
    }
    buildWsUrl() {
      let e = location.protocol === `https:` ? `wss` : `ws`,
        t = qu()
      return t ? `${e}://${location.host}/api/asr/funasr?token=${encodeURIComponent(t)}` : ``
    }
  },
  am = 18e3,
  om = class {
    id = `whisper-web`
    label = `本地 Whisper 识别`
    worker = null
    capture = null
    _loading = !0
    _ready = !1
    _onResult = null
    _onError = null
    audioBuffer = []
    chunkTimer = null
    _lastText = ``
    _stopped = !1
    _initError = ``
    _jobSeq = 0
    _activeJobId = 0
    isAvailable() {
      return typeof window < `u` && typeof Worker < `u`
    }
    isLoading() {
      return this._loading && !this._ready
    }
    nextJobId() {
      return ((this._jobSeq += 1), (this._activeJobId = this._jobSeq), this._activeJobId)
    }
    invalidatePendingJobs() {
      ;((this._jobSeq += 1), (this._activeJobId = this._jobSeq))
    }
    ensureWorker() {
      return this.worker
        ? this.worker
        : ((this.worker = new Worker(new URL(`/corp-butler/assets/whisper-asr-worker-sDckqT8m.js`, `` + import.meta.url), {
            type: `module`,
          })),
          (this.worker.onmessage = (e) => {
            let t = e.data
            if (t.type === `ready`) ((this._loading = !1), (this._ready = !0))
            else if (t.type !== `progress`) {
              if (t.type === `result`) {
                if (t.jobId != null && t.jobId !== this._activeJobId) return
                let e = (t.data || ``).trim()
                e && !this._stopped && ((this._lastText = e), this._onResult?.({ text: e, isFinal: !1 }))
              } else if (t.type === `error`) {
                if (
                  ((this._loading = !1),
                  (this._initError = t.data || `Whisper 识别失败`),
                  (t.jobId != null && t.jobId !== this._activeJobId) || t.jobId != null)
                )
                  return
                this._ready && this._onError && this._onError(this._initError)
              }
            }
          }),
          (this.worker.onerror = (e) => {
            ;((this._loading = !1),
              (this._initError = `Whisper Worker 错误：${e.message || `未知`}`),
              this._onError && this._onError(this._initError))
          }),
          this.worker.postMessage({ type: `init` }),
          this.worker)
    }
    waitForModelReady(e) {
      if (this._ready) return Promise.resolve(!0)
      let t = this.worker
      return t
        ? new Promise((n) => {
            let r = !1,
              i = (e) => {
                r || ((r = !0), clearTimeout(a), t.removeEventListener(`message`, o), t.removeEventListener(`error`, s), n(e))
              },
              a = setTimeout(() => i(!1), e),
              o = (e) => {
                e.data.type === `ready`
                  ? ((this._loading = !1), (this._ready = !0), i(!0))
                  : e.data.type === `error` &&
                    e.data.jobId == null &&
                    ((this._initError = e.data.data || this._initError || `Whisper 模型加载失败`), i(!1))
              },
              s = () => {
                ;((this._initError = this._initError || `Whisper Worker 启动失败`), i(!1))
              }
            ;(t.addEventListener(`message`, o), t.addEventListener(`error`, s))
          })
        : Promise.resolve(!1)
    }
    async start(e, t, n, r) {
      if (
        ((this._onResult = e),
        (this._onError = t),
        (this._stopped = !1),
        (this._lastText = ``),
        (this._initError = ``),
        (this.audioBuffer = []),
        this.ensureWorker(),
        !(await this.waitForModelReady(am)))
      ) {
        t(this._initError || `Whisper 模型加载失败`)
        return
      }
      this.capture = new zp()
      try {
        await this.capture.start({
          onAudioData: (e) => {
            let t = this.capture?.sampleRate ?? 16e3
            this.audioBuffer.push(Vp(e, t, 16e3))
          },
          onAudioLevel: n ?? void 0,
        })
      } catch (e) {
        t(`麦克风启动失败：` + (e instanceof Error ? e.message : String(e)))
        return
      }
      ;((this.chunkTimer = setInterval(() => {
        this.processChunk()
      }, 3e3)),
        r?.())
    }
    processChunk() {
      if (!this.audioBuffer.length || !this._ready || this._stopped) return
      let e = this.mergeBuffers()
      if (((this.audioBuffer = []), e.length < 1600)) return
      let t = this.nextJobId()
      this.worker?.postMessage({ type: `transcribe`, jobId: t, data: { audio: e } })
    }
    mergeBuffers() {
      let e = 0
      for (let t of this.audioBuffer) e += t.length
      let t = new Float32Array(e),
        n = 0
      for (let e of this.audioBuffer) (t.set(e, n), (n += e.length))
      return t
    }
    transcribeBuffer(e, t) {
      return new Promise((n) => {
        let r = (e) => {
          ;(e.data.jobId != null && e.data.jobId !== t) ||
            (e.data.type === `result`
              ? (this.worker?.removeEventListener(`message`, r), n((e.data.data || ``).trim()))
              : e.data.type === `error` && (this.worker?.removeEventListener(`message`, r), n(``)))
        }
        ;(this.worker?.addEventListener(`message`, r),
          this.worker?.postMessage({ type: `transcribe`, jobId: t, data: { audio: e } }),
          setTimeout(() => {
            ;(this.worker?.removeEventListener(`message`, r), n(``))
          }, 1e4))
      })
    }
    async flushUtterance() {
      ;((this.chunkTimer &&= (clearInterval(this.chunkTimer), null)), this.invalidatePendingJobs())
      let e = this._lastText.trim()
      if (this.audioBuffer.length > 0 && this._ready) {
        let t = this.mergeBuffers()
        if (((this.audioBuffer = []), t.length >= 1600)) {
          let n = this.nextJobId(),
            r = (await this.transcribeBuffer(t, n)).trim()
          r && (e = r)
        }
      }
      return (
        e && ((this._lastText = e), this._onResult?.({ text: e, isFinal: !0 })),
        (this._lastText = ``),
        !this._stopped &&
          this._ready &&
          (this.chunkTimer = setInterval(() => {
            this.processChunk()
          }, 3e3)),
        e
      )
    }
    async stop() {
      if (
        ((this._stopped = !0),
        this.invalidatePendingJobs(),
        (this.chunkTimer &&= (clearInterval(this.chunkTimer), null)),
        this.audioBuffer.length > 0 && this._ready)
      ) {
        let e = this.mergeBuffers()
        if (((this.audioBuffer = []), e.length >= 1600)) {
          let t = this.nextJobId(),
            n = (await this.transcribeBuffer(e, t)).trim() || this._lastText
          return (this._onResult?.({ text: n, isFinal: !0 }), this.capture?.stop(), (this.capture = null), n)
        }
      }
      return (
        this._lastText && this._onResult?.({ text: this._lastText, isFinal: !0 }),
        this.capture?.stop(),
        (this.capture = null),
        this._lastText
      )
    }
    abort() {
      ;((this._stopped = !0),
        this.invalidatePendingJobs(),
        (this.chunkTimer &&= (clearInterval(this.chunkTimer), null)),
        this.capture?.stop(),
        (this.capture = null),
        (this.audioBuffer = []),
        (this._onResult = null),
        (this._onError = null),
        this.worker?.terminate(),
        (this.worker = null),
        (this._ready = !1),
        (this._loading = !0))
    }
  }
function sm() {
  try {
    let e =
      typeof self < `u` && `location` in self ? self.location?.origin : globalThis.location === void 0 ? `` : globalThis.location.origin
    if (e && e !== `null` && /^https?:\/\//.test(e)) return `${e}${`/corp-butler/`.replace(/\/$/, ``)}/hf-hub`
  } catch {}
  return `https://huggingface.co`
}
async function cm() {
  try {
    let e = sm(),
      t = `/corp-butler/`.replace(/\/?$/, `/`),
      n = typeof window < `u` && window.location?.origin ? window.location.origin : ``,
      r = [`${e}/onnx-community/whisper-base/resolve/main/config.json`]
    return (
      n && n !== `null` && r.push(`${n}${t}asr-ort/ort-wasm-simd-threaded.asyncify.wasm`),
      (
        await Promise.all(
          r.map(async (e) => {
            try {
              return (await fetch(e, { method: `GET`, cache: `no-store` })).ok
            } catch {
              return !1
            }
          }),
        )
      ).every(Boolean)
    )
  } catch {
    return !1
  }
}
var lm = [
  { id: `funasr`, create: () => new im(), startHint: `正在连接语音服务…`, timeoutMs: 15e3 },
  { id: `webspeech`, create: () => new Wp(), startHint: `正在尝试浏览器语音…`, timeoutMs: 12e3 },
  { id: `whisper-web`, create: () => new om(), startHint: `正在加载本地识别模型…`, timeoutMs: 3e4 },
]
function um() {
  return typeof navigator > `u` ? !1 : /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent)
}
function dm() {
  let e = z(``),
    t = z(``),
    n = z(0),
    r = z(``),
    i = z(``),
    a = z(!1),
    o = null,
    s = null,
    c = null,
    l = null,
    u = null,
    d = !1,
    f = 0,
    p = ``,
    m = null,
    h = !1,
    g = 0,
    _,
    v
  function y() {
    return `服务端语音识别不可用，请检查网络后重试；国内环境请勿依赖浏览器识别。`
  }
  function b(e) {
    let t = (e || ``).trim()
    return /请先登录|认证|token/i.test(t)
      ? t || `请先登录后再使用语音识别。`
      : /麦克风|Permission|NotAllowed|getUserMedia|授权|占用/i.test(t)
        ? um()
          ? `请先点击右下角麦克风按钮，在系统弹窗中允许麦克风后再说话。`
          : t || `麦克风不可用，请检查权限或使用文字输入。`
        : y()
  }
  function x() {
    return `持续聆听需 FunASR 服务端或浏览器语音识别；移动端请确认已允许麦克风，或使用 Chrome / Edge。`
  }
  function S() {
    if (o) {
      try {
        o.abort()
      } catch {}
      ;((o = null), (i.value = ``), (a.value = !1), (n.value = 0))
    }
  }
  function C() {
    u &&= (clearTimeout(u), null)
  }
  function w(e, t) {
    C()
    let n = lm[e]
    if (h && (n?.id === `webspeech` || n?.id === `funasr`)) {
      let r = n.id === `funasr` ? (um() ? 35e3 : 2e4) : 8e3
      u = setTimeout(() => {
        T(e, t)
      }, r)
      return
    }
    d = !1
    let r = n?.timeoutMs ?? 12e3
    u = setTimeout(() => {
      T(e, t)
    }, r)
  }
  async function T(t, n) {
    if (n !== f || d) return
    ;(S(), (r.value = ``))
    let i = lm[t]
    if (h && i?.id === `funasr`) {
      if (g < 4) {
        if (((g += 1), (r.value = `正在重连语音服务…`), await new Promise((e) => setTimeout(e, 600 + g * 400)), n !== f)) return
        await E(0, n)
        return
      }
      let t = y()
      ;((e.value = t), c?.(t))
      return
    }
    if (t + 1 < lm.length) {
      ;((r.value = `正在切换识别方案…`), await E(t + 1, n))
      return
    }
    let a = h && um() ? x() : `语音识别无响应，请检查麦克风或使用文字输入。`
    ;((e.value = a), c?.(a))
  }
  async function E(t, n) {
    if (n !== f) return
    if (t >= lm.length) {
      r.value = ``
      let t = h && um() ? x() : `语音识别不可用。请检查麦克风权限或使用文字输入。`
      ;((e.value = t), c?.(t))
      return
    }
    let i = lm[t]
    if (h && i.id === `webspeech`) {
      r.value = ``
      let t = y()
      ;((e.value = t), c?.(t))
      return
    }
    if (i.id === `whisper-web`) {
      if (h) {
        await E(t + 1, n)
        return
      }
      if (um()) {
        await E(t + 1, n)
        return
      }
      if (!(await cm())) {
        await E(t + 1, n)
        return
      }
    }
    let a = i.create()
    if (!a.isAvailable()) {
      await E(t + 1, n)
      return
    }
    r.value = i.id === `funasr` ? `请允许麦克风权限…` : i.startHint
    try {
      await O(a, i.id, t, n)
    } catch {
      if (n !== f) return
      await E(t + 1, n)
    }
  }
  async function D(n, i, o, u) {
    ;((e.value = ``),
      (t.value = ``),
      (r.value = ``),
      (a.value = !1),
      (s = n),
      (c = i),
      (l = o ?? null),
      (h = u?.continuous ?? !1),
      (g = 0),
      (_ = void 0),
      (v = void 0),
      u?.mediaStream && (u.mediaStream instanceof MediaStream ? (_ = u.mediaStream) : (v = u.mediaStream)),
      (f += 1))
    let d = f
    ;(u?.continuous || (p = ``),
      (m = E(0, d).finally(() => {
        m = null
      })),
      await m)
  }
  async function O(u, m, x, T) {
    if (T !== f) return
    ;(S(), (o = u), (i.value = m), (a.value = !1))
    let D = lm[x]?.id
    h && (D === `webspeech` || D === `funasr`) && w(x, T)
    let k = _
    if (!k && v)
      try {
        ;((k = await v), k && (_ = k))
      } catch {
        k = void 0
      }
    let A = ``,
      j = (e) => {
        T === f && (e.text.trim() && ((p = e.text.trim()), (t.value = p), (d = !0), h || C(), (r.value = ``)), s?.(e))
      },
      ee = async (n) => {
        if (T !== f) return
        ;(C(), (r.value = ``))
        let i = p
        if (!a.value) {
          A = n
          return
        }
        if ((S(), h && x === 0 && g < 4)) {
          if (
            ((g += 1), (r.value = `正在重连语音服务…`), i && (t.value = i), await new Promise((e) => setTimeout(e, 600 + g * 400)), T !== f)
          )
            return
          await E(0, T)
          return
        }
        if (h && x === 0) {
          ;((e.value = y()), c?.(y()))
          return
        }
        if (x + 1 < lm.length) {
          ;((r.value = `正在切换识别方案…`), i && (t.value = i), await E(x + 1, T))
          return
        }
        ;((e.value = n), c?.(n))
      },
      M = (e) => {
        T === f && ((n.value = e), l?.(e))
      },
      te = () => {
        T === f && (h && D === `funasr` && (g = 0), C(), (a.value = !0), (r.value = `请开始说话…`), em(), h || w(x, T))
      }
    if (
      (await (m === `funasr`
        ? u.start(
            j,
            ee,
            M,
            te,
            () => {
              T === f && (r.value = `正在连接语音服务…`)
            },
            k,
            { persistentMic: h },
          )
        : u.start(j, ee, M, te, void 0, k)),
      T === f)
    ) {
      if (!a.value && o === u) {
        if ((S(), h && x === 0 && g < 4)) {
          if (((g += 1), (r.value = `正在重连语音服务…`), await new Promise((e) => setTimeout(e, 600 + g * 400)), T !== f)) return
          let e = lm[x]
          return e ? O(e.create(), e.id, x, T) : void 0
        }
        if (h && x === 0) {
          let t = b(A)
          ;((e.value = t), c?.(t))
          return
        }
        if (x + 1 < lm.length) {
          ;((r.value = `正在切换识别方案…`), await E(x + 1, T))
          return
        }
        let t = A || `语音识别启动失败，请检查麦克风后重试。`
        ;((e.value = t), c?.(t))
        return
      }
      o === u && ((h && (D === `webspeech` || D === `funasr`)) || w(x, T))
    }
  }
  function k() {
    o?.signalEndOfSpeech?.()
  }
  async function A() {
    if (!o) return p.trim()
    let e = o
    if (typeof e.flushUtterance == `function`) {
      let t = (await e.flushUtterance()).trim()
      return (t && (p = t), t)
    }
    return p.trim()
  }
  async function j() {
    if ((C(), m))
      try {
        await m
      } catch {}
    if (!o) {
      let e = p.trim()
      return ((p = ``), (r.value = ``), h && $p(), e)
    }
    let e = ((await o.stop()) || p).trim()
    return ((p = ``), S(), (r.value = ``), (a.value = !1), h && $p(), e)
  }
  function ee(e) {
    ;((f += 1), (m = null), C(), S(), e?.keepMic || $p(), (t.value = ``), (r.value = ``), (a.value = !1))
  }
  return (
    Rr(() => {
      ee()
    }),
    {
      error: e,
      interimText: t,
      audioLevel: n,
      activeBackendId: i,
      sessionReady: a,
      loadingHint: r,
      startListening: D,
      flushListening: A,
      signalEndOfSpeech: k,
      stopListening: j,
      abort: ee,
    }
  )
}
function fm(e) {
  return String(e || ``)
    .replace(/<<<PLAN_DETAILS>>>[\s\S]*?<<<END_PLAN_DETAILS>>>/gi, ``)
    .replace(/<<<PLAN_OPTIONS>>>[\s\S]*?<<<END_PLAN_OPTIONS>>>/gi, ``)
    .replace(/<<<CHECKLIST>>>[\s\S]*?<<<END>>>/gi, ``)
    .replace(/<<<PLAN_DETAILS>>>[\s\S]*/gi, ``)
    .replace(/<<<PLAN_OPTIONS>>>[\s\S]*/gi, ``)
    .replace(/<<<CHECKLIST>>>[\s\S]*/gi, ``)
    .replace(/<<<[A-Z_]+>>+[\s\S]*/gi, ``)
    .replace(/```mermaid[\s\S]*?```/gi, ``)
    .trim()
}
function pm(e, t = 1500) {
  return fm(e || ``)
    .slice(0, t)
    .replace(/```[\s\S]*?```/g, ``)
    .replace(/`[^`]+`/g, ``)
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ``)
    .replace(/\[[^\]]*\]\([^)]*\)/g, (e) => e.replace(/\[([^\]]*)\]\([^)]*\)/, `$1`))
    .replace(/^#{1,6}\s+/gm, ``)
    .replace(/^[-*+]\s+/gm, ``)
    .replace(/^\d+\.\s+/gm, ``)
    .replace(/^>\s?/gm, ``)
    .replace(/\*{1,3}([^*]+)\*{1,3}/g, `$1`)
    .replace(/_{1,3}([^_]+)_{1,3}/g, `$1`)
    .replace(/~~([^~]+)~~/g, `$1`)
    .replace(/[\p{Emoji_Presentation}\p{Extended_Pictographic}\u{FE0F}\u{200D}]/gu, ``)
    .replace(/[^\p{L}\p{N}\p{P}\p{S}\p{Z}\n]/gu, ``)
    .replace(
      /\n{2,}/g,
      `
`,
    )
    .replace(/\s+/g, ` `)
    .trim()
}
var mm = `/api/workbench/tts`,
  hm = `/api/workbench/tts/edge/stream`,
  gm = `audio/mpeg`,
  _m = class {
    getConfig
    state = z(`idle`)
    queue = []
    splitter = Wf()
    feedOpts
    streamSoFar = ``
    enqueuedSentences = []
    generation = 0
    running = !1
    abortController = null
    currentAudio = null
    objectUrls = []
    prefetchMap = new Map()
    warmInFlight = null
    streamFirstSentencePending = !0
    leadInCancel = null
    edgeBlockedUntil = 0
    lastWarmUpAt = 0
    constructor(e) {
      this.getConfig = e
    }
    markEdgeRateLimited(e) {
      let t = typeof e == `number` && e > 0 ? e * 1e3 : 6e4
      this.edgeBlockedUntil = Date.now() + t
    }
    preferUnified() {
      return this.getConfig().engine !== `edge-online`
    }
    canUseEdge() {
      return Date.now() >= this.edgeBlockedUntil
    }
    noteEdgeError(e) {
      e instanceof Qu && e.status === 429 && this.markEdgeRateLimited()
    }
    warmUp() {
      if (this.warmInFlight || Date.now() - this.lastWarmUpAt < 3e4) return
      this.lastWarmUpAt = Date.now()
      let e = this.getConfig(),
        t = JSON.stringify(
          this.preferUnified()
            ? {
                text: `你好，我在。`,
                edge_voice: e.edgeVoice || `zh-CN-XiaoxiaoNeural`,
                rate: e.rate,
              }
            : { text: `你好，我在。`, voice: e.edgeVoice || `zh-CN-XiaoxiaoNeural`, rate: e.rate },
        ),
        n = this.preferUnified() ? mm : hm
      this.warmInFlight = hd(n, { method: `POST`, body: t })
        .then(() => {})
        .catch((e) => {
          this.noteEdgeError(e)
        })
        .finally(() => {
          this.warmInFlight = null
        })
    }
    async speak(e) {
      this.stop()
      let t = pm(e)
      if (!t) return
      let n = ++this.generation
      ;((this.enqueuedSentences = []),
        (this.queue = Uf(t)),
        (this.streamFirstSentencePending = !0),
        this.schedulePrefetch(n, 0),
        await this.runQueue(n))
    }
    feed(e) {
      let t = pm(e)
      if (!t) return
      this.streamSoFar = t
      let n = this.splitter.feed(t)
      for (let e of n) this.enqueue(e)
    }
    finish(e) {
      let t = pm(e ?? this.streamSoFar),
        n = this.splitter.finish(t)
      for (let e of n) this.enqueue(e)
      ;((this.streamSoFar = ``), this.splitter.reset())
    }
    resetStream(e) {
      ;((this.feedOpts = e),
        (this.splitter = Wf(e)),
        (this.streamSoFar = ``),
        (this.enqueuedSentences = []),
        (this.streamFirstSentencePending = !0),
        this.resetEdgeBackoff())
    }
    stop() {
      ;((this.generation += 1),
        (this.queue = []),
        this.prefetchMap.clear(),
        (this.enqueuedSentences = []),
        (this.running = !1),
        this.cancelBrowserLeadIn(),
        (this.abortController &&= (this.abortController.abort(), null)),
        this.stopCurrentAudio(),
        this.revokeUrls(),
        typeof window < `u` && `speechSynthesis` in window && window.speechSynthesis.cancel(),
        (this.streamFirstSentencePending = !0),
        (this.state.value = `idle`))
    }
    resetEdgeBackoff() {
      this.edgeBlockedUntil = 0
    }
    cancelBrowserLeadIn() {
      this.leadInCancel &&= (this.leadInCancel(), null)
    }
    enqueue(e) {
      let t = e.trim()
      if (!t) return
      let n = Vf([t], this.enqueuedSentences)
      if (n.length) {
        this.enqueuedSentences.push(...n)
        for (let e of n) this.queue.push(e)
        this.running || this.runQueue(this.generation)
      }
    }
    whenIdle(e = 12e4) {
      return this.state.value === `idle` && !this.running && this.queue.length === 0
        ? Promise.resolve()
        : new Promise((t) => {
            let n = Date.now(),
              r = () => {
                if (this.state.value === `idle` && !this.running && this.queue.length === 0) {
                  t()
                  return
                }
                if (Date.now() - n >= e) {
                  t()
                  return
                }
                setTimeout(r, 40)
              }
            r()
          })
    }
    buildUnifiedPayload(e) {
      let t = this.getConfig()
      return JSON.stringify({
        text: e,
        edge_voice: t.edgeVoice || `zh-CN-XiaoxiaoNeural`,
        rate: t.rate,
      })
    }
    buildEdgePayload(e) {
      let t = this.getConfig()
      return JSON.stringify({ text: e, voice: t.edgeVoice || `zh-CN-XiaoxiaoNeural`, rate: t.rate })
    }
    schedulePrefetch(e, t) {
      let n = this.getConfig(),
        r = Math.max(1, n.prefetchDepth ?? 1),
        i = this.abortController?.signal
      if (!i) return
      let a = 0
      for (let n = t; n < this.queue.length && a < r; n++) {
        let t = this.queue[n]
        !t || this.prefetchMap.has(t) || (this.prefetchMap.set(t, this.prefetchBlob(t, i, e)), (a += 1))
      }
    }
    async runQueue(e) {
      if (this.running) return
      ;((this.running = !0), (this.abortController = new AbortController()))
      let t = this.abortController.signal
      for (; this.queue.length > 0 && e === this.generation; ) {
        let n = this.queue.shift()
        ;(this.schedulePrefetch(e, 0), (this.state.value = `synthesizing`))
        let r = this.prefetchMap.get(n)
        r && this.prefetchMap.delete(n)
        let i = !1
        if (r) {
          let t = null
          try {
            t = await r
          } catch {
            t = null
          }
          if (e !== this.generation) break
          t && t.size > 0 && ((this.state.value = `playing`), await this.playBlob(t, e), (i = !0))
        }
        if (!i && e === this.generation)
          try {
            if (this.preferUnified()) {
              let r = await hd(mm, { method: `POST`, body: this.buildUnifiedPayload(n), signal: t })
              if (e !== this.generation) break
              r && r.size > 0 && ((this.state.value = `playing`), await this.playBlob(r, e), (i = !0))
            }
            if (!i && this.canUseEdge()) {
              let r = await md(hm, { method: `POST`, body: this.buildEdgePayload(n), signal: t })
              if (e !== this.generation) break
              ;((this.state.value = `playing`), (i = await this.playStreamResponse(r, e)), i && this.stopCurrentAudio())
            }
          } catch (e) {
            this.noteEdgeError(e)
          }
      }
      ;((this.running = !1), (this.abortController = null), e === this.generation && (this.state.value = `idle`))
    }
    async prefetchBlob(e, t, n) {
      if (n !== this.generation) return null
      try {
        return this.preferUnified()
          ? await hd(mm, { method: `POST`, body: this.buildUnifiedPayload(e), signal: t })
          : this.canUseEdge()
            ? await hd(hm, { method: `POST`, body: this.buildEdgePayload(e), signal: t })
            : null
      } catch (e) {
        return ((e instanceof DOMException && e.name === `AbortError`) || this.noteEdgeError(e), null)
      }
    }
    canUseMse() {
      return typeof window < `u` && typeof MediaSource < `u` && MediaSource.isTypeSupported(gm)
    }
    async playStreamResponse(e, t) {
      let n = e.body
      if (!n) return !1
      if (this.canUseMse())
        try {
          return (await this.playMseStream(n, t), !0)
        } catch {}
      let r = n.getReader(),
        i = []
      try {
        for (;;) {
          let { done: e, value: n } = await r.read()
          if (t !== this.generation) return !0
          if (e) break
          n?.byteLength && i.push(n)
        }
      } finally {
        r.releaseLock()
      }
      return t !== this.generation || !i.length ? !1 : (await this.playBlob(new Blob(i, { type: gm }), t), !0)
    }
    playMseStream(e, t) {
      return new Promise((n, r) => {
        let i = new MediaSource(),
          a = URL.createObjectURL(i)
        this.objectUrls.push(a)
        let o = new Audio()
        ;((o.preload = `auto`),
          (this.currentAudio = o),
          (o.src = a),
          i.addEventListener(
            `sourceopen`,
            () => {
              this.pumpMse(e, i, o, t)
                .then(() => {
                  if (t !== this.generation) {
                    n()
                    return
                  }
                  if (o.ended) {
                    n()
                    return
                  }
                  ;(o.addEventListener(`ended`, () => n(), { once: !0 }), o.addEventListener(`error`, () => n(), { once: !0 }))
                })
                .catch(r)
            },
            { once: !0 },
          ))
      })
    }
    async pumpMse(e, t, n, r) {
      let i = e.getReader(),
        a = t.addSourceBuffer(gm)
      a.mode = `sequence`
      let o = !1,
        s = (e) =>
          new Promise((t, n) => {
            let r = () => {
                ;(a.removeEventListener(`updateend`, r), a.removeEventListener(`error`, i), t())
              },
              i = () => {
                ;(a.removeEventListener(`updateend`, r), a.removeEventListener(`error`, i), n(Error(`SourceBuffer error`)))
              }
            ;(a.addEventListener(`updateend`, r, { once: !0 }), a.addEventListener(`error`, i, { once: !0 }))
            try {
              a.appendBuffer(e)
            } catch (e) {
              n(e)
            }
          })
      try {
        for (;;) {
          if (r !== this.generation) {
            await i.cancel()
            return
          }
          let { done: e, value: c } = await i.read()
          if (
            (c?.byteLength &&
              (await s(c.buffer.slice(c.byteOffset, c.byteOffset + c.byteLength)),
              !o && a.buffered.length > 0 && ((o = !0), n.play().catch(() => {}))),
            e)
          ) {
            if (t.readyState === `open`)
              try {
                t.endOfStream()
              } catch {}
            break
          }
        }
      } finally {
        i.releaseLock()
      }
    }
    stopCurrentAudio() {
      if (this.currentAudio) {
        try {
          ;(this.currentAudio.pause(), this.currentAudio.removeAttribute(`src`), this.currentAudio.load())
        } catch {}
        this.currentAudio = null
      }
    }
    revokeUrls() {
      for (let e of this.objectUrls)
        try {
          URL.revokeObjectURL(e)
        } catch {}
      this.objectUrls = []
    }
    async playBlob(e, t) {
      if (t !== this.generation) return
      let n = URL.createObjectURL(e)
      this.objectUrls.push(n)
      let r = new Audio(n)
      ;((this.currentAudio = r),
        await new Promise((e) => {
          let t = () => {
            ;(this.stopCurrentAudio(), e())
          }
          ;(r.addEventListener(`ended`, t, { once: !0 }), r.addEventListener(`error`, t, { once: !0 }), r.play().catch(t))
        }))
    }
  }
function vm(e) {
  let t = new _m(e)
  return {
    state: t.state,
    speak: (e) => t.speak(e),
    feed: (e) => t.feed(e),
    finish: (e) => t.finish(e),
    resetStream: (e) => t.resetStream(e),
    warmUp: () => t.warmUp(),
    whenIdle: (e) => t.whenIdle(e),
    stop: () => t.stop(),
  }
}
function ym(e) {
  return {
    engine: e.ttsEngine === `edge-online` ? `edge-online` : `auto`,
    edgeVoice: e.ttsEdgeVoice || `zh-CN-XiaoxiaoNeural`,
    browserVoiceName: ``,
    rate: e.ttsRate,
    streamThreshold: 0,
    prefetchDepth: 1,
    browserLeadIn: !1,
  }
}
function bm() {
  if (typeof window > `u`) return !1
  try {
    if (new im().isAvailable() || new Wp().isAvailable()) return !0
  } catch {}
  return !!navigator.mediaDevices?.getUserMedia
}
function xm(e) {
  let t = z(`idle`),
    n = z(``),
    r = z(!1),
    i = z(!1),
    a = z(1),
    o = !1,
    s = vm(() => ym({ ...Sp(), ttsRate: a.value })),
    c = dm(),
    l = bm()
  function u(e) {
    return i.value || !e
      ? Promise.resolve()
      : ((t.value = `speaking`),
        (r.value = !0),
        s.speak(e).finally(() => {
          ;((r.value = !1), t.value === `speaking` && (t.value = `idle`))
        }))
  }
  async function d(r, i) {
    let a = r.trim()
    if (!o) {
      if (!a) {
        ;(t.value === `listening` && (t.value = `idle`), i?.emptyMessage && (n.value = i.emptyMessage))
        return
      }
      ;((o = !0), (n.value = ``), (t.value = `thinking`))
      try {
        await e(a)
      } finally {
        ;((o = !1), t.value === `thinking` && (t.value = `idle`))
      }
    }
  }
  function f() {
    ;((n.value = ``),
      (t.value = `listening`),
      c.startListening(
        (e) => {
          e.isFinal &&
            d(e.text).finally(() => {
              c.abort()
            })
        },
        (e) => {
          ;((n.value = e), (t.value = `idle`), c.abort())
        },
      ))
  }
  async function p() {
    if (t.value !== `listening`) return
    c.signalEndOfSpeech()
    let e = (await c.stopListening()).trim()
    o || (await d(e, { emptyMessage: `未识别到文字，请再试一次或使用文字输入。` }))
  }
  function m() {
    ;(c.abort(), s.stop(), (r.value = !1), (t.value = `idle`))
  }
  function h() {
    ;((i.value = !i.value), i.value && (s.stop(), (r.value = !1)))
  }
  return (
    Rr(() => {
      m()
    }),
    {
      state: t,
      error: n,
      isSpeaking: r,
      muted: i,
      rate: a,
      isSupported: l,
      interimText: c.interimText,
      loadingHint: c.loadingHint,
      sessionReady: c.sessionReady,
      startListening: f,
      stopListening: p,
      stopAll: m,
      speak: u,
      toggleMute: h,
    }
  )
}
var Sm = {
  NAVIGATE: `navigate`,
  CLICK: `click`,
  FILL: `fill`,
  SELECT: `select`,
  SCROLL: `scroll`,
  READ: `read`,
  PURCHASE: `purchase`,
  RECHARGE: `recharge`,
  SEARCH_EMPLOYEE: `search_employee`,
}
;(Sm.NAVIGATE, Sm.READ, Sm.SCROLL, Sm.CLICK, Sm.FILL, Sm.SELECT, Sm.SEARCH_EMPLOYEE, Sm.PURCHASE, Sm.RECHARGE)
var Cm = `xc_butler_action_log`
function wm() {
  try {
    let e = sessionStorage.getItem(Cm)
    return e ? JSON.parse(e) : []
  } catch {
    return []
  }
}
var Tm = mp(
    br({
      __name: `AgentStatusBar`,
      props: { mode: {} },
      emits: [`stop`],
      setup(e) {
        let t = e,
          n = q(() => {
            switch (t.mode) {
              case `listening`:
                return `我在听…说完停顿即可`
              case `thinking`:
                return `AI 思考中…`
              case `operating`:
                return `正在操作页面…`
              case `awaiting_confirm`:
                return `等待您确认`
              case `speaking`:
                return `AI 正在朗读`
              case `error`:
                return `出现错误`
              default:
                return ``
            }
          }),
          r = q(() => t.mode === `thinking` || t.mode === `operating` || t.mode === `listening` || t.mode === `speaking`)
        return (t, i) =>
          e.mode === `idle`
            ? K(``, !0)
            : (H(),
              U(
                `div`,
                {
                  key: 0,
                  class: P([`status-bar`, `status-bar--${e.mode}`]),
                  'aria-live': `polite`,
                },
                [
                  (i[1] ||= W(`span`, { class: `status-dot`, 'aria-hidden': `true` }, null, -1)),
                  W(`span`, null, F(n.value), 1),
                  r.value
                    ? (H(),
                      U(
                        `button`,
                        {
                          key: 0,
                          type: `button`,
                          class: `status-stop`,
                          onClick: (i[0] ||= (e) => t.$emit(`stop`)),
                        },
                        `停止`,
                      ))
                    : K(``, !0),
                ],
                2,
              ))
      },
    }),
    [[`__scopeId`, `data-v-4e239226`]],
  ),
  Em = { key: 0, class: `bubble bubble--user` },
  Dm = { key: 1, class: `bubble bubble--assistant` },
  Om = { key: 0, class: `bubble-dots` },
  km = [`innerHTML`],
  Am = { key: 2, class: `bubble bubble--tool` },
  jm = { key: 3, class: `bubble bubble--preview` },
  Mm = { class: `preview-header` },
  Nm = { class: `preview-label` },
  Pm = { class: `bubble-time` },
  Fm = mp(
    br({
      __name: `AgentMessageBubble`,
      props: { msg: {} },
      setup(e) {
        function t(e) {
          return e
            .replace(/&/g, `&amp;`)
            .replace(/</g, `&lt;`)
            .replace(/>/g, `&gt;`)
            .replace(/\*\*(.+?)\*\*/g, `<strong>$1</strong>`)
            .replace(/\n/g, `<br>`)
        }
        function n(e) {
          return e
            ? Object.entries(e)
                .map(([e, t]) => `${e}=${String(t)}`)
                .join(`, `)
            : ``
        }
        function r(e) {
          return e === `high` ? `高风险` : e === `medium` ? `中风险` : `低风险`
        }
        function i(e) {
          let t = new Date(e)
          return `${t.getHours().toString().padStart(2, `0`)}:${t.getMinutes().toString().padStart(2, `0`)}`
        }
        return (a, o) => (
          H(),
          U(
            `article`,
            {
              class: P([`bubble-wrap`, [`bubble-wrap--${e.msg.role}`, { 'bubble-wrap--loading': e.msg.isLoading }]]),
            },
            [
              e.msg.role === `user`
                ? (H(), U(`div`, Em, F(e.msg.content), 1))
                : e.msg.role === `assistant`
                  ? (H(),
                    U(`div`, Dm, [
                      e.msg.isLoading
                        ? (H(),
                          U(`span`, Om, [...(o[0] ||= [W(`span`, null, null, -1), W(`span`, null, null, -1), W(`span`, null, null, -1)])]))
                        : (H(), U(`span`, { key: 1, class: `bubble-text`, innerHTML: t(e.msg.content) }, null, 8, km)),
                    ]))
                  : e.msg.role === `tool_call`
                    ? (H(),
                      U(`div`, Am, [
                        (o[1] ||= W(`span`, { class: `bubble-tool-icon` }, `⚙️`, -1)),
                        W(`span`, null, F(e.msg.toolCall?.name || `工具调用`) + `: ` + F(n(e.msg.toolCall?.args)), 1),
                      ]))
                    : e.msg.role === `action_preview`
                      ? (H(),
                        U(`div`, jm, [
                          W(`div`, Mm, [
                            W(
                              `span`,
                              {
                                class: P([`preview-risk`, `preview-risk--${e.msg.actionPreview?.risk}`]),
                              },
                              F(r(e.msg.actionPreview?.risk)),
                              3,
                            ),
                            W(`span`, Nm, F(e.msg.actionPreview?.label), 1),
                          ]),
                        ]))
                      : K(``, !0),
              W(`time`, Pm, F(i(e.msg.timestamp)), 1),
            ],
            2,
          )
        )
      },
    }),
    [[`__scopeId`, `data-v-560b2522`]],
  ),
  Im = [`aria-label`],
  Lm = { class: `action-preview__header` },
  Rm = { class: `action-preview__label` },
  zm = { key: 0, class: `action-preview__warn` },
  Bm = { class: `action-preview__btns` },
  Vm = mp(
    br({
      __name: `AgentActionPreview`,
      props: { action: {} },
      emits: [`confirm`, `cancel`],
      setup(e) {
        let t = e,
          n = q(() => (t.action.risk === `high` ? `高风险` : t.action.risk === `medium` ? `中风险` : `低风险`))
        return (t, r) => (
          H(),
          U(
            `div`,
            {
              class: P([`action-preview`, `action-preview--${e.action.risk}`]),
              role: `alertdialog`,
              'aria-label': `确认操作：${e.action.label}`,
            },
            [
              W(`div`, Lm, [
                W(`span`, { class: P([`action-risk-badge`, `action-risk-badge--${e.action.risk}`]) }, F(n.value), 3),
                (r[2] ||= W(`span`, { class: `action-preview__title` }, `即将执行操作`, -1)),
              ]),
              W(`p`, Rm, F(e.action.label), 1),
              e.action.risk === `high` ? (H(), U(`p`, zm, ` ⚠️ 此操作无法撤销，请确认后继续 `)) : K(``, !0),
              W(`div`, Bm, [
                W(
                  `button`,
                  {
                    type: `button`,
                    class: `action-btn action-btn--cancel`,
                    onClick: (r[0] ||= (e) => t.$emit(`cancel`)),
                  },
                  ` 取消 `,
                ),
                W(
                  `button`,
                  {
                    type: `button`,
                    class: P([`action-btn action-btn--confirm`, `action-btn--${e.action.risk}`]),
                    onClick: (r[1] ||= (e) => t.$emit(`confirm`)),
                  },
                  F(e.action.risk === `high` ? `确认执行` : `确认`),
                  3,
                ),
              ]),
            ],
            10,
            Im,
          )
        )
      },
    }),
    [[`__scopeId`, `data-v-fa06e071`]],
  ),
  Hm = z(!1),
  Um = z(!1)
function Wm() {
  Hm.value = !0
}
function Gm() {
  Hm.value = !1
}
var Km = { class: `corp-welcome`, role: `region`, 'aria-label': `管家欢迎` },
  qm = { class: `corp-welcome__title` },
  Jm = { class: `corp-welcome__subtitle` },
  Ym = { key: 1, class: `corp-welcome__tasks`, role: `list` },
  Xm = [`onClick`],
  Zm = { class: `corp-task-card__label` },
  Qm = { key: 2, class: `corp-welcome__hint` },
  $m = { key: 3, class: `corp-welcome__hint` },
  eh = mp(
    br({
      __name: `CorpWelcomeBoard`,
      props: {
        title: { default: `Hi，我是小C` },
        subtitle: {},
        tasks: {},
        isContactPage: { type: Boolean, default: !1 },
        isMobileContact: { type: Boolean, default: !1 },
      },
      emits: [`task`],
      setup(e) {
        let t = e,
          n = z(!1),
          r = q(() => (Um.value ? `已预填 · 点此可再填` : `AI 一键填表`)),
          i = q(() => (t.isContactPage ? `也可在下方输入框直接描述您的场景` : `选择上方任务，或在下方输入您的问题`))
        function a() {
          ;((n.value = !0), Wm())
        }
        return (t, o) => (
          H(),
          U(`div`, Km, [
            W(`h2`, qm, F(e.title), 1),
            W(`p`, Jm, F(e.subtitle), 1),
            e.isMobileContact
              ? (H(),
                U(
                  `button`,
                  {
                    key: 0,
                    type: `button`,
                    class: `corp-welcome__cta btn btn-primary`,
                    onClick: a,
                  },
                  F(r.value),
                  1,
                ))
              : (H(),
                U(`ul`, Ym, [
                  (H(!0),
                  U(
                    V,
                    null,
                    Gr(
                      e.tasks,
                      (e, n) => (
                        H(),
                        U(`li`, { key: n }, [
                          W(
                            `button`,
                            {
                              type: `button`,
                              class: `corp-task-card`,
                              onClick: (n) => t.$emit(`task`, e),
                            },
                            [
                              (o[0] ||= W(`span`, { class: `corp-task-card__icon`, 'aria-hidden': `true` }, `✦`, -1)),
                              W(`span`, Zm, F(e.label), 1),
                              (o[1] ||= W(`span`, { class: `corp-task-card__arrow`, 'aria-hidden': `true` }, `›`, -1)),
                            ],
                            8,
                            Xm,
                          ),
                        ])
                      ),
                    ),
                    128,
                  )),
                ])),
            !e.isMobileContact && e.tasks.length
              ? (H(), U(`p`, Qm, F(i.value), 1))
              : e.isMobileContact && n.value
                ? (H(), U(`p`, $m, ` 也可在下方输入框用文字描述场景 `))
                : K(``, !0),
          ])
        )
      },
    }),
    [[`__scopeId`, `data-v-6519c427`]],
  ),
  th = { key: 1, class: `chat-empty` },
  nh = { class: `chat-empty-desc` },
  rh = { class: `chat-empty-sub` },
  ih = [`onClick`],
  ah = mp(
    br({
      name: `AgentChatHistory`,
      props: { corpMode: { type: Boolean, default: !1 } },
      emits: [`quick`, `task`],
      setup(e, { emit: t }) {
        let n = e,
          r = t,
          { messages: i, pendingAction: a } = $s(tu()),
          o = Xl(),
          s = q(() => !n.corpMode && String(o.name || ``) === `about`),
          c = q(() => (typeof window < `u` ? window.location.pathname : `/`)),
          l = q(() => Su(c.value)),
          u = iu(),
          d = q(() => n.corpMode && l.value && u.value),
          f = q(() => (!n.corpMode || s.value ? !1 : d.value ? !0 : h.value.length > 0 && !i.value.length)),
          p = q(() => {
            if (!(!n.corpMode || s.value)) return d.value ? `Hi，我来帮您填需求问卷` : Du(c.value)
          }),
          m = q(() =>
            n.corpMode
              ? s.value
                ? Au(`market-about`)
                : d.value
                  ? `您可以用 AI 一键填表：填写公司名称和行业/业务类型后，我会自动写好下方整份问卷。`
                  : Eu(c.value)
              : Au(String(o.name || ``)),
          ),
          h = q(() => (n.corpMode ? (s.value ? ku(`market-about`) : d.value ? [] : Ou(c.value)) : ku(String(o.name || ``))))
        function g(e) {
          if (e.task) {
            r(`task`, e)
            return
          }
          r(`quick`, e.message || e.label)
        }
        function _(e) {
          r(`task`, e)
        }
        let v = z(null)
        return (
          Vn(
            i,
            () => {
              xn(() => {
                v.value && (v.value.scrollTop = v.value.scrollHeight)
              })
            },
            { deep: !0 },
          ),
          (t, n) => (
            H(),
            U(
              `div`,
              {
                ref_key: `scrollEl`,
                ref: v,
                class: P([`chat-history`, { 'chat-history--corp': e.corpMode }]),
                role: `log`,
                'aria-label': `对话历史`,
                'aria-live': `polite`,
              },
              [
                f.value
                  ? (H(),
                    ma(
                      eh,
                      {
                        key: 0,
                        title: p.value,
                        subtitle: m.value,
                        tasks: h.value,
                        'is-contact-page': l.value,
                        'is-mobile-contact': d.value,
                        onTask: _,
                      },
                      null,
                      8,
                      [`title`, `subtitle`, `tasks`, `is-contact-page`, `is-mobile-contact`],
                    ))
                  : !B(i).length && h.value.length
                    ? (H(),
                      U(`div`, th, [
                        (n[2] ||= W(`p`, { class: `chat-empty-title` }, `需要我做什么？`, -1)),
                        W(`p`, nh, F(m.value), 1),
                        W(`p`, rh, [
                          (H(!0),
                          U(
                            V,
                            null,
                            Gr(
                              h.value,
                              (e, t) => (
                                H(),
                                U(
                                  `button`,
                                  {
                                    key: t,
                                    type: `button`,
                                    class: `quick-tip`,
                                    onClick: (t) => g(e),
                                  },
                                  F(e.label),
                                  9,
                                  ih,
                                )
                              ),
                            ),
                            128,
                          )),
                        ]),
                      ]))
                    : K(``, !0),
                (H(!0),
                U(
                  V,
                  null,
                  Gr(B(i), (e) => (H(), ma(Fm, { key: e.id, msg: e }, null, 8, [`msg`]))),
                  128,
                )),
                B(a)
                  ? (H(),
                    ma(
                      Vm,
                      {
                        key: 2,
                        action: B(a),
                        onConfirm: (n[0] ||= (e) => B(a)?.resolve(!0)),
                        onCancel: (n[1] ||= (e) => B(a)?.resolve(!1)),
                      },
                      null,
                      8,
                      [`action`],
                    ))
                  : K(``, !0),
              ],
              2,
            )
          )
        )
      },
    }),
    [[`__scopeId`, `data-v-f97cd9a4`]],
  ),
  oh = [
    { level: 1, minExp: 0, title: `新手` },
    { level: 2, minExp: 1e3, title: `探索者` },
    { level: 3, minExp: 5e3, title: `创作者` },
    { level: 4, minExp: 2e4, title: `专家` },
    { level: 5, minExp: 5e4, title: `大师` },
    { level: 6, minExp: 1e5, title: `宗师` },
    { level: 7, minExp: 2e5, title: `传奇` },
  ]
function sh(e) {
  let t = Math.max(Math.floor(Number(e) || 0), 0),
    n = oh.findLastIndex((e) => t >= e.minExp),
    r = n < 0 ? 0 : n,
    i = oh[r],
    a = oh[r + 1] ?? null,
    o = i.minExp,
    s = a?.minExp ?? null,
    c = 1
  if (s !== null) {
    let e = Math.max(s - o, 1)
    c = Math.max(0, Math.min(1, (t - o) / e))
  }
  return {
    level: i.level,
    title: i.title,
    experience: t,
    current_level_min_exp: o,
    next_level_min_exp: s,
    progress: Math.round(c * 1e4) / 1e4,
  }
}
function ch(e) {
  if (e === null) return null
  if (e === void 0) return
  if (typeof e != `object`) return null
  let t = e,
    n = t.user
  if (n && typeof n == `object` && t.id === void 0 && n.id !== void 0) {
    let e = n
    return {
      id: e.id,
      username: e.username,
      email: e.email,
      phone: e.phone,
      is_admin: !!(e.is_admin ?? e.admin),
      created_at: e.created_at,
      experience: Number(e.experience ?? t.experience ?? 0) || 0,
      level_profile: e.level_profile ?? t.level_profile,
      avatar_url: e.avatar_url ?? t.avatar_url ?? null,
    }
  }
  return t
}
function lh(e) {
  let t = typeof e?.username == `string` ? e.username.trim() : ``,
    n = typeof e?.email == `string` ? e.email.trim() : ``
  return t || (n ? n.split(`@`)[0] || n : ``)
}
var uh = Qs(`auth`, () => {
  let e = z(null),
    t = z(`client`),
    n = z(``),
    r = z(0),
    i = z(null),
    a = z(!1),
    o = q(() => !!(e.value && qu())),
    s = q(() => e.value?.is_admin === !0),
    c = q(() => lh(e.value)),
    l = `modstore_admin_digest_unlock_expires`,
    u = z((typeof sessionStorage < `u` ? sessionStorage.getItem(l) : ``) || ``),
    d = q(() => {
      let e = u.value
      if (!e) return !1
      let t = Date.parse(e)
      return Number.isFinite(t) && Date.now() < t
    })
  function f(e) {
    ;((u.value = e || ``), typeof sessionStorage < `u` && (e ? sessionStorage.setItem(l, e) : sessionStorage.removeItem(l)))
  }
  function p() {
    f(``)
  }
  let m = q(
    () =>
      String(i.value?.tier || ``)
        .trim()
        .toLowerCase() || ``,
  )
  function h(e) {
    let t = Number(e.level) || 1,
      n = typeof e.title == `string` ? e.title : ``,
      r = Number(e.experience) || 0,
      i = Number(e.current_level_min_exp) || 0,
      a = e.next_level_min_exp
    return {
      level: t,
      title: n,
      experience: r,
      currentLevelMinExp: i,
      nextLevelMinExp: a == null ? null : Number(a),
      progress: Math.max(0, Math.min(1, Number(e.progress) || 0)),
    }
  }
  let g = q(() => {
    if (!e.value) return null
    let t = e.value.level_profile
    return ((!t || typeof t != `object`) && (t = sh(Number(e.value.experience) || 0)), h(t))
  })
  function _() {
    ;((e.value = null), (i.value = null), (a.value = !1), (n.value = ``), (r.value = 0))
  }
  async function v() {
    if (!qu()) {
      ;((i.value = null), (a.value = !1))
      return
    }
    try {
      let e = await Yd.paymentMyPlan()
      a.value = !1
      let t = e?.membership && typeof e.membership == `object` ? e.membership : null
      t && typeof t.tier == `string`
        ? (i.value = {
            tier: String(t.tier),
            label: String(t.label || ``),
            is_member: !!t.is_member,
          })
        : (i.value = { tier: `free`, label: `普通用户`, is_member: !1 })
    } catch {
      ;((a.value = !0), (i.value = null))
    }
  }
  async function y(t = !1) {
    let i = qu()
    if (!i) return (_(), null)
    let a = Date.now()
    if (!t && i === n.value && e.value && a - r.value < 15e3) return e.value
    try {
      let t = await Yd.me()
      if (t && typeof t == `object` && (t.ok === !1 || t.success === !1)) return (Xu(), _(), null)
      let a = ch(t)
      return !a || a.id == null ? (Xu(), _(), null) : ((e.value = a), (n.value = i), (r.value = Date.now()), v(), e.value)
    } catch (t) {
      return (
        t instanceof Qu && (t.status === 401 || t.status === 403) ? (Xu(), _()) : ((e.value = null), (n.value = ``), (r.value = 0)),
        null
      )
    }
  }
  async function b(e, t) {
    let n = await Yd.login(e, t)
    return (await y(!0), n)
  }
  async function x(e, t) {
    let n = await Yd.loginWithCode(e, t)
    return (await y(!0), n)
  }
  function S() {
    let e = qu()
    return !!(e && e !== `undefined` && e !== `null`)
  }
  function C() {
    ;(Xu(), _(), p(), (t.value = `client`))
  }
  return {
    user: e,
    currentMode: t,
    isLoggedIn: o,
    isAdmin: s,
    username: c,
    levelProfile: g,
    membership: i,
    membershipFetchFailed: a,
    membershipTier: m,
    hasToken: S,
    refreshSession: y,
    refreshMembership: v,
    loginWithPassword: b,
    loginWithCode: x,
    logout: C,
    adminUiUnlocked: d,
    setAdminDigestUnlock: f,
    clearAdminDigestUnlock: p,
  }
})
function dh(e) {
  let t = String(e.label || ``).trim()
  return t && t !== e.filename
    ? t
    : String(e.filename || ``)
        .split(/[/\\]/)
        .pop() ||
        e.filename ||
        `下载文件`
}
var fh = `xc_butler_download_history_v1`
function ph(e, t) {
  return `${e}:${t}`
}
function mh(e, t, n) {
  return `${e}-${t}-${n}`.replace(/[^a-zA-Z0-9._-]+/g, `_`)
}
function hh(e, t, n = 5) {
  let r = [...e].sort((e, t) => t.createdAt - e.createdAt)
  if (t) return r.map((e) => ({ ...e, expired: !1 }))
  let i = Math.max(1, n)
  return r.map((e, t) => ({ ...e, expired: t >= i }))
}
function gh(e, t, n) {
  let r = ph(t.jobId, t.filename),
    i = e.filter((e) => ph(e.jobId, e.filename) !== r),
    a = t.createdAt || Date.now()
  return hh(
    [
      {
        id: t.id || mh(t.jobId, t.filename, a),
        jobId: t.jobId,
        filename: t.filename,
        displayName: t.displayName,
        employeeId: t.employeeId,
        createdAt: a,
        expired: !1,
      },
      ...i,
    ],
    n,
  )
}
function _h(e, t) {
  let n = t?.createdAt ?? Date.now()
  return e
    .filter((e) => e?.jobId && e?.filename)
    .map((e) => ({
      jobId: e.jobId,
      filename: e.filename,
      displayName: dh(e),
      employeeId: t?.employeeId,
      createdAt: n,
    }))
}
function vh(e) {
  if (!e) return []
  try {
    let t = JSON.parse(e)
    if (!Array.isArray(t)) return []
    let n = []
    for (let e of t) {
      if (!e || typeof e != `object`) continue
      let t = e,
        r = String(t.jobId || ``).trim(),
        i = String(t.filename || ``).trim()
      !r ||
        !i ||
        n.push({
          id: String(t.id || mh(r, i, Number(t.createdAt) || 0)),
          jobId: r,
          filename: i,
          displayName: String(t.displayName || i),
          employeeId: t.employeeId ? String(t.employeeId) : void 0,
          createdAt: Number(t.createdAt) || 0,
          expired: !!t.expired,
        })
    }
    return n
  } catch {
    return []
  }
}
function yh(e) {
  return JSON.stringify(e)
}
function bh(e) {
  return `${fh}:${e == null || e === `` ? `guest` : String(e)}`
}
var xh = Qs(`butlerDownloadHistory`, () => {
    let e = uh(),
      t = z([]),
      n = z(!1),
      r = q(() => !!e.membership?.is_member),
      i = q(() => t.value.filter((e) => !e.expired)),
      a = q(() => t.value.filter((e) => e.expired))
    function o() {
      let i = e.user?.id,
        a = bh(i),
        o = null
      try {
        o = localStorage.getItem(a)
      } catch {
        o = null
      }
      ;((t.value = hh(vh(o), r.value)), (n.value = !0))
    }
    function s() {
      if (!n.value) return
      let r = bh(e.user?.id)
      try {
        localStorage.setItem(r, yh(t.value))
      } catch {}
    }
    function c() {
      ;((t.value = hh(t.value, r.value)), s())
    }
    function l(e, i) {
      if (!e?.length) return
      n.value || o()
      let a = _h(e, { employeeId: i?.employeeId }),
        c = t.value
      for (let e of a) c = gh(c, e, r.value)
      ;((t.value = c), s())
    }
    function u(e, t, n, r) {
      l([{ jobId: e, filename: t, label: n }], { employeeId: r })
    }
    return (
      Vn(
        () => [e.user?.id, e.membership?.is_member],
        () => {
          o()
        },
        { immediate: !0 },
      ),
      Vn(r, () => {
        n.value && c()
      }),
      {
        records: t,
        isMember: r,
        activeRecords: i,
        expiredRecords: a,
        loadFromStorage: o,
        recordDownloads: l,
        recordSingle: u,
        reapplyRetention: c,
      }
    )
  }),
  Sh = [`txt`, `md`, `json`, `csv`, `pdf`, `docx`, `xlsx`],
  Ch = [`xlsm`, `xls`, `doc`, `ppt`, `pptx`],
  wh = [...Sh, ...Ch]
;(new Set(Sh), new Set(wh), wh.map((e) => `.${e}`).join(`,`))
var Th = [`png`, `jpg`, `jpeg`, `webp`, `gif`, `bmp`]
;[...wh, ...Th].map((e) => `.${e}`).join(`,`)
function Eh(e) {
  let t = String(e || ``),
    n = t.lastIndexOf(`.`)
  return n < 0 || n >= t.length - 1 ? `` : t.slice(n + 1).toLowerCase()
}
function Dh(e, t = ``) {
  let n = Eh(e)
  return Th.includes(n) || String(t).startsWith(`image/`)
    ? `vision`
    : n === `xlsx` || n === `xlsm` || n === `xls`
      ? `excel`
      : n === `pdf`
        ? `pdf`
        : n === `docx`
          ? `word`
          : n === `pptx` || n === `ppt`
            ? `ppt`
            : n === `csv`
              ? `csv`
              : n === `json`
                ? `json`
                : n === `txt` || n === `md` || String(t).startsWith(`text/`)
                  ? `text`
                  : `file`
}
function Oh(e) {
  switch (e) {
    case `excel`:
      return `Excel`
    case `pdf`:
      return `PDF`
    case `word`:
      return `Word`
    case `ppt`:
      return `PPT`
    case `csv`:
      return `CSV`
    case `json`:
      return `JSON`
    case `text`:
      return `Text`
    case `vision`:
      return `Image`
    default:
      return `File`
  }
}
var kh = { class: `butler-files`, 'aria-label': `文件收纳与下载记录` },
  Ah = { key: 0, class: `butler-files__block` },
  jh = { class: `butler-files__title` },
  Mh = { class: `butler-files__count` },
  Nh = { class: `butler-files__list` },
  Ph = { class: `butler-files__kind` },
  Fh = [`title`],
  Ih = { class: `butler-files__meta` },
  Lh = [`onClick`],
  Rh = [`title`, `onClick`],
  zh = [`onClick`],
  Bh = { class: `butler-files__block` },
  Vh = { key: 0, class: `butler-files__member-hint` },
  Hh = { key: 1, class: `butler-files__member-hint butler-files__member-hint--ok` },
  Uh = { key: 2, class: `butler-files__list` },
  Wh = [`title`, `onClick`],
  Gh = { class: `butler-files__meta` },
  Kh = { key: 3, class: `butler-files__empty` },
  qh = { class: `butler-files__list butler-files__list--expired` },
  Jh = { class: `butler-files__name` },
  Yh = mp(
    br({
      __name: `ButlerFilesDrawer`,
      setup(e) {
        let t = vp(),
          n = xh(),
          r = tu(),
          i = Yl(),
          { overflowAttachments: a, overflowGenerated: o, overflowCount: s } = $s(t),
          { activeRecords: c, expiredRecords: l, isMember: u } = $s(n),
          d = q(() => s.value > 0)
        async function f(e, t, n) {
          if (!n)
            try {
              let n = await Yd.employeeOutputDownload(e, t),
                r = URL.createObjectURL(n),
                i = document.createElement(`a`)
              ;((i.href = r), (i.download = t.split(/[/\\]/).pop() || t), i.click(), URL.revokeObjectURL(r))
            } catch {}
        }
        function p(e) {
          let n = t.actions.downloadGenerated
          n ? n(e) : f(e.jobId, e.filename, !1)
        }
        function m(e) {
          t.actions.removeGenerated?.(e)
        }
        function h(e) {
          t.actions.removeAttachment?.(e)
        }
        function g() {
          ;(r.closePanel(), i.push({ name: `plans` }))
        }
        return (e, t) => (
          H(),
          U(`section`, kh, [
            d.value
              ? (H(),
                U(`div`, Ah, [
                  W(`h3`, jh, [(t[0] ||= Sa(` 收纳文件 `, -1)), W(`span`, Mh, F(B(s)), 1)]),
                  (t[2] ||= W(`p`, { class: `butler-files__hint` }, `顶栏仅展示少量卡片，其余收纳在小C助理中。`, -1)),
                  W(`ul`, Nh, [
                    (H(!0),
                    U(
                      V,
                      null,
                      Gr(
                        B(a),
                        (e) => (
                          H(),
                          U(
                            `li`,
                            {
                              key: `att-${e.id}`,
                              class: `butler-files__item butler-files__item--attachment`,
                            },
                            [
                              W(`span`, Ph, F(B(Oh)(B(Dh)(e.name))), 1),
                              W(`span`, { class: `butler-files__name`, title: e.name }, F(e.name), 9, Fh),
                              W(`span`, Ih, F(e.status), 1),
                              W(
                                `button`,
                                {
                                  type: `button`,
                                  class: `butler-files__btn butler-files__btn--ghost`,
                                  'aria-label': `移除附件`,
                                  onClick: (t) => h(e.id),
                                },
                                ` 移除 `,
                                8,
                                Lh,
                              ),
                            ],
                          )
                        ),
                      ),
                      128,
                    )),
                    (H(!0),
                    U(
                      V,
                      null,
                      Gr(
                        B(o),
                        (e) => (
                          H(),
                          U(
                            `li`,
                            {
                              key: e.id,
                              class: `butler-files__item butler-files__item--generated`,
                            },
                            [
                              (t[1] ||= W(`span`, { class: `butler-files__kind` }, `已生成`, -1)),
                              W(
                                `button`,
                                {
                                  type: `button`,
                                  class: `butler-files__name butler-files__name--link`,
                                  title: `${e.name}：点击下载`,
                                  onClick: (t) => p(e),
                                },
                                F(e.name),
                                9,
                                Rh,
                              ),
                              W(
                                `button`,
                                {
                                  type: `button`,
                                  class: `butler-files__btn butler-files__btn--ghost`,
                                  'aria-label': `移除`,
                                  onClick: (t) => m(e.id),
                                },
                                ` 移除 `,
                                8,
                                zh,
                              ),
                            ],
                          )
                        ),
                      ),
                      128,
                    )),
                  ]),
                ]))
              : K(``, !0),
            W(`div`, Bh, [
              (t[6] ||= W(`h3`, { class: `butler-files__title` }, `下载记录`, -1)),
              B(u)
                ? (H(), U(`p`, Hh, ` 会员：下载记录将长期保留。 `))
                : (H(),
                  U(`p`, Vh, [
                    Sa(` 普通用户仅保留最近 ` + F(B(5)) + ` 条可下载记录；开通 `, 1),
                    W(`button`, { type: `button`, class: `butler-files__link`, onClick: g }, `会员`),
                    (t[3] ||= Sa(` 可长期保留全部记录。 `, -1)),
                  ])),
              B(c).length
                ? (H(),
                  U(`ul`, Uh, [
                    (H(!0),
                    U(
                      V,
                      null,
                      Gr(
                        B(c),
                        (e) => (
                          H(),
                          U(`li`, { key: e.id, class: `butler-files__item butler-files__item--history` }, [
                            W(
                              `button`,
                              {
                                type: `button`,
                                class: `butler-files__name butler-files__name--link`,
                                title: e.displayName,
                                onClick: (t) => f(e.jobId, e.filename, !1),
                              },
                              F(e.displayName),
                              9,
                              Wh,
                            ),
                            W(`span`, Gh, F(new Date(e.createdAt).toLocaleString()), 1),
                          ])
                        ),
                      ),
                      128,
                    )),
                  ]))
                : (H(), U(`p`, Kh, `暂无有效下载记录`)),
              B(l).length
                ? (H(),
                  U(
                    V,
                    { key: 4 },
                    [
                      (t[5] ||= W(`h4`, { class: `butler-files__subtitle` }, `已过期`, -1)),
                      W(`ul`, qh, [
                        (H(!0),
                        U(
                          V,
                          null,
                          Gr(
                            B(l),
                            (e) => (
                              H(),
                              U(
                                `li`,
                                {
                                  key: `exp-${e.id}`,
                                  class: `butler-files__item butler-files__item--expired`,
                                },
                                [W(`span`, Jh, F(e.displayName), 1), (t[4] ||= W(`span`, { class: `butler-files__meta` }, `已过期`, -1))],
                              )
                            ),
                          ),
                          128,
                        )),
                      ]),
                    ],
                    64,
                  ))
                : K(``, !0),
            ]),
          ])
        )
      },
    }),
    [[`__scopeId`, `data-v-bff32fe6`]],
  ),
  Xh = { class: `voice-bar` },
  Zh = [`aria-label`, `title`],
  Qh = { key: 1, class: `voice-hint` },
  $h = { key: 2, class: `voice-err` },
  eg = mp(
    br({
      __name: `AgentVoiceInput`,
      props: {
        voiceState: {},
        isSupported: { type: Boolean },
        error: {},
        loadingHint: {},
        sessionReady: { type: Boolean },
      },
      emits: [`toggle`],
      setup(e, { emit: t }) {
        let n = e,
          r = t,
          { isLightTheme: i } = wp(),
          a = q(() => n.voiceState === `listening`),
          o = q(() =>
            n.error
              ? ``
              : n.voiceState === `thinking`
                ? `正在处理…`
                : a.value
                  ? n.loadingHint
                    ? n.loadingHint
                    : n.sessionReady === !1
                      ? `正在连接…`
                      : `请说话，说完再点麦克风结束`
                  : ``,
          )
        function s() {
          r(`toggle`)
        }
        return (t, n) => (
          H(),
          U(`div`, Xh, [
            e.isSupported
              ? (H(),
                U(
                  `button`,
                  {
                    key: 0,
                    type: `button`,
                    class: P([`voice-btn`, { 'voice-btn--active': a.value, 'voice-btn--light': B(i) }]),
                    'aria-label': a.value ? `停止录音` : `按住说话`,
                    title: e.isSupported ? (a.value ? `点击停止录音` : `点击开始语音输入`) : `浏览器不支持语音识别`,
                    onClick: s,
                  },
                  [
                    ...(n[0] ||= [
                      W(
                        `svg`,
                        { viewBox: `0 0 24 24`, fill: `none`, 'aria-hidden': `true` },
                        [
                          W(`rect`, {
                            x: `9`,
                            y: `2`,
                            width: `6`,
                            height: `12`,
                            rx: `3`,
                            stroke: `currentColor`,
                            'stroke-width': `1.8`,
                          }),
                          W(`path`, {
                            d: `M5 11a7 7 0 0 0 14 0`,
                            stroke: `currentColor`,
                            'stroke-width': `1.8`,
                            'stroke-linecap': `round`,
                          }),
                          W(`line`, {
                            x1: `12`,
                            y1: `18`,
                            x2: `12`,
                            y2: `22`,
                            stroke: `currentColor`,
                            'stroke-width': `1.8`,
                            'stroke-linecap': `round`,
                          }),
                        ],
                        -1,
                      ),
                    ]),
                  ],
                  10,
                  Zh,
                ))
              : K(``, !0),
            o.value ? (H(), U(`span`, Qh, F(o.value), 1)) : e.error ? (H(), U(`span`, $h, F(e.error), 1)) : K(``, !0),
          ])
        )
      },
    }),
    [[`__scopeId`, `data-v-bfab2c2f`]],
  ),
  tg = [`title`],
  ng = { class: `panel-head__left` },
  rg = [`src`],
  ig = [`aria-label`, `title`],
  ag = { viewBox: `0 0 24 24`, fill: `none`, 'aria-hidden': `true` },
  og = {
    key: 0,
    d: `M16 9a4 4 0 010 6M18.5 7a7 7 0 010 10`,
    stroke: `currentColor`,
    'stroke-width': `1.6`,
    'stroke-linecap': `round`,
  },
  sg = {
    key: 1,
    d: `M16 10l4 4M20 10l-4 4`,
    stroke: `currentColor`,
    'stroke-width': `1.6`,
    'stroke-linecap': `round`,
  },
  cg = { key: 2, class: `panel-log` },
  lg = { key: 0, class: `panel-log__empty` },
  ug = { class: `log-action` },
  dg = { class: `log-label` },
  fg = { key: 0, class: `panel-composer panel-composer--corp` },
  pg = [`aria-pressed`, `title`],
  mg = [`onKeydown`],
  hg = [`disabled`],
  gg = { class: `panel-tools` },
  _g = [`aria-pressed`, `title`],
  vg = { class: `panel-composer` },
  yg = [`onKeydown`],
  bg = [`disabled`],
  xg = mp(
    br({
      __name: `FloatingAgentPanel`,
      props: { corpMode: { type: Boolean, default: !1 }, handleInput: {}, runIntakeTask: {} },
      emits: [`proactive-intro-change`],
      setup(e, { emit: t }) {
        let n = e,
          r = t,
          i = z(Jf())
        function a() {
          let e = !i.value
          ;((i.value = e), Yf(e), e || ip(), r(`proactive-intro-change`, e))
        }
        let o = tu(),
          s = vp(),
          c = xh(),
          { mode: l, position: u, focusFilesDrawer: d } = $s(o),
          { overflowCount: f } = $s(s),
          p = z(null),
          m = q(() => f.value > 0 || c.records.length > 0)
        Vn(d, (e) => {
          e &&
            xn(() => {
              ;(p.value?.$el?.scrollIntoView?.({ block: `nearest`, behavior: `smooth` }), o.clearFilesDrawerFocus())
            })
        })
        let { isLightTheme: h } = wp(),
          g = q(() => (n.corpMode, `/corp-butler/brand-xc-logo.jpg`)),
          _ = n.handleInput,
          v = z(``),
          y = z(!1),
          b = z(!1),
          x = z(null),
          S = z(null),
          C = q(() => wm().slice().reverse()),
          w = q(() => {
            let e = u.value.x,
              t = u.value.y,
              r = n.corpMode ? 420 : 460,
              i = e + 32 - 340 / 2,
              a = t - r - 12
            ;((i = Math.max(8, Math.min(window.innerWidth - 340 - 8, i))), (a = Math.max(8, Math.min(window.innerHeight - r - 8, a))))
            let o = { left: `${i}px`, top: `${a}px`, width: `340px` }
            return n.corpMode ? o : { ...o, height: `${r}px` }
          }),
          T = 0,
          E = 0,
          D = !1
        function O(e) {
          e.button === 0 && ((D = !0), (T = e.clientX), (E = e.clientY), e.currentTarget.setPointerCapture(e.pointerId))
        }
        function k(e) {
          if (!D) return
          let t = e.clientX - T,
            r = e.clientY - E
          if (((T = e.clientX), (E = e.clientY), n.corpMode)) {
            let e = pu(u.value.x + t, u.value.y + r)
            o.savePosition(e.x, e.y)
            return
          }
          o.savePosition(u.value.x + t, u.value.y + r)
        }
        function A() {
          D = !1
        }
        let {
          state: j,
          error: ee,
          isSupported: M,
          interimText: te,
          loadingHint: N,
          sessionReady: ne,
          startListening: re,
          stopListening: ie,
          speak: ae,
        } = xm(async (e) => {
          if (((v.value = ``), await le(e), n.corpMode)) return
          let t = o.messages,
            r = t[t.length - 1]
          r && r.role === `assistant` && !r.isLoading && (await ae(r.content))
        })
        Vn(te, (e) => {
          j.value === `listening` && e && ((v.value = e), xn(() => fe()))
        })
        function se() {
          j.value === `listening` ? ie() : ((ee.value = ``), re())
        }
        async function ce() {
          let e = v.value.trim()
          e && ((v.value = ``), await xn(), fe(), await le(e))
        }
        async function le(e) {
          await _(e, { withScreenshot: y.value })
        }
        async function ue(e) {
          await le(e)
        }
        async function de(e) {
          if (n.runIntakeTask) {
            await n.runIntakeTask(e)
            return
          }
          let t = e.message || e.label
          t && (await le(t))
        }
        function fe() {
          let e = x.value
          e && ((e.style.height = `auto`), (e.style.height = Math.min(e.scrollHeight, 80) + `px`))
        }
        return (t, n) => (
          H(),
          U(
            `div`,
            {
              ref_key: `panelRef`,
              ref: S,
              class: P([
                `butler-panel`,
                {
                  'butler-panel--light': e.corpMode || B(h),
                  'butler-panel--corp-anchor': e.corpMode,
                },
              ]),
              style: oe(w.value),
              role: `dialog`,
              'aria-label': `AI 数字管家`,
              'aria-modal': `false`,
            },
            [
              W(
                `header`,
                {
                  class: P([`panel-head`, { 'panel-head--corp-drag': e.corpMode }]),
                  title: e.corpMode ? `按住标题栏可拖动` : void 0,
                  onPointerdown: O,
                  onPointermove: k,
                  onPointerup: A,
                },
                [
                  W(`div`, ng, [
                    W(
                      `img`,
                      {
                        class: `panel-head__logo`,
                        src: g.value,
                        alt: ``,
                        width: `28`,
                        height: `28`,
                        decoding: `async`,
                      },
                      null,
                      8,
                      rg,
                    ),
                    (n[9] ||= W(`div`, { class: `panel-head__titles` }, [W(`span`, { class: `panel-head__title` }, `小C助理`)], -1)),
                  ]),
                  W(
                    `div`,
                    {
                      class: `panel-head__actions`,
                      onPointerdown: (n[3] ||= ds(() => {}, [`stop`])),
                    },
                    [
                      e.corpMode
                        ? (H(),
                          U(
                            `button`,
                            {
                              key: 0,
                              type: `button`,
                              class: P([`panel-icon-btn`, { 'panel-icon-btn--active': i.value }]),
                              'aria-label': i.value ? `关闭主动介绍` : `开启主动介绍`,
                              title: i.value ? `主动介绍：开（点击关闭）` : `主动介绍：关（点击开启）`,
                              onClick: ds(a, [`stop`]),
                            },
                            [
                              (H(),
                              U(`svg`, ag, [
                                (n[10] ||= W(
                                  `path`,
                                  {
                                    d: `M11 5L6 9H3v6h3l5 4V5z`,
                                    stroke: `currentColor`,
                                    'stroke-width': `1.6`,
                                    'stroke-linejoin': `round`,
                                  },
                                  null,
                                  -1,
                                )),
                                i.value ? (H(), U(`path`, og)) : (H(), U(`path`, sg)),
                              ])),
                            ],
                            10,
                            ig,
                          ))
                        : K(``, !0),
                      e.corpMode
                        ? K(``, !0)
                        : (H(),
                          U(
                            `button`,
                            {
                              key: 1,
                              type: `button`,
                              class: `panel-icon-btn`,
                              'aria-label': `查看操作日志`,
                              title: `操作日志`,
                              onClick: (n[0] ||= ds((e) => (b.value = !b.value), [`stop`])),
                            },
                            [
                              ...(n[11] ||= [
                                W(
                                  `svg`,
                                  { viewBox: `0 0 24 24`, fill: `none`, 'aria-hidden': `true` },
                                  [
                                    W(`path`, {
                                      d: `M9 12h6M9 8h6M9 16h4`,
                                      stroke: `currentColor`,
                                      'stroke-width': `1.6`,
                                      'stroke-linecap': `round`,
                                    }),
                                    W(`rect`, {
                                      x: `3`,
                                      y: `4`,
                                      width: `18`,
                                      height: `16`,
                                      rx: `3`,
                                      stroke: `currentColor`,
                                      'stroke-width': `1.6`,
                                    }),
                                  ],
                                  -1,
                                ),
                              ]),
                            ],
                          )),
                      W(
                        `button`,
                        {
                          type: `button`,
                          class: `panel-icon-btn`,
                          'aria-label': `清空对话`,
                          title: `清空对话`,
                          onClick: (n[1] ||= ds((e) => B(o).clearMessages(), [`stop`])),
                        },
                        [
                          ...(n[12] ||= [
                            W(
                              `svg`,
                              { viewBox: `0 0 24 24`, fill: `none`, 'aria-hidden': `true` },
                              [
                                W(`path`, {
                                  d: `M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6`,
                                  stroke: `currentColor`,
                                  'stroke-width': `1.6`,
                                  'stroke-linecap': `round`,
                                  'stroke-linejoin': `round`,
                                }),
                              ],
                              -1,
                            ),
                          ]),
                        ],
                      ),
                      W(
                        `button`,
                        {
                          type: `button`,
                          class: `panel-icon-btn`,
                          'aria-label': `关闭管家`,
                          title: `关闭`,
                          onClick: (n[2] ||= ds((e) => B(o).closePanel(), [`stop`])),
                        },
                        [...(n[13] ||= [W(`span`, { 'aria-hidden': `true` }, `×`, -1)])],
                      ),
                    ],
                    32,
                  ),
                ],
                42,
                tg,
              ),
              e.corpMode
                ? K(``, !0)
                : (H(), ma(Tm, { key: 0, mode: B(l), onStop: (n[4] ||= (e) => B(o).setMode(`idle`)) }, null, 8, [`mode`])),
              !e.corpMode && m.value ? (H(), ma(Yh, { key: 1, ref_key: `filesDrawerRef`, ref: p }, null, 512)) : K(``, !0),
              !e.corpMode && b.value
                ? (H(),
                  U(`div`, cg, [
                    (n[14] ||= W(`div`, { class: `panel-log__title` }, `操作日志`, -1)),
                    C.value.length ? K(``, !0) : (H(), U(`div`, lg, `暂无操作记录`)),
                    (H(!0),
                    U(
                      V,
                      null,
                      Gr(
                        C.value,
                        (e, t) => (
                          H(),
                          U(`div`, { key: t, class: `panel-log__entry` }, [
                            W(`span`, ug, F(e.action), 1),
                            W(`span`, dg, F(e.label), 1),
                            W(
                              `span`,
                              {
                                class: P([`log-status`, e.success ? `log-status--ok` : `log-status--err`]),
                              },
                              F(e.success ? `成功` : `失败`),
                              3,
                            ),
                          ])
                        ),
                      ),
                      128,
                    )),
                  ]))
                : K(``, !0),
              G(ah, { 'corp-mode': e.corpMode, onQuick: ue, onTask: de }, null, 8, [`corp-mode`]),
              W(
                `footer`,
                { class: P([`panel-foot`, { 'panel-foot--corp': e.corpMode }]) },
                [
                  e.corpMode
                    ? (H(),
                      U(`div`, fg, [
                        G(
                          eg,
                          {
                            'voice-state': B(j),
                            'is-supported': B(M),
                            error: B(ee),
                            'loading-hint': B(N),
                            'session-ready': B(ne),
                            onToggle: se,
                          },
                          null,
                          8,
                          [`voice-state`, `is-supported`, `error`, `loading-hint`, `session-ready`],
                        ),
                        W(
                          `button`,
                          {
                            type: `button`,
                            class: P([`panel-shot-btn`, { 'panel-shot-btn--active': y.value, 'panel-shot-btn--light': B(h) }]),
                            'aria-pressed': y.value,
                            'aria-label': `附带截图`,
                            title: y.value ? `已开启：发送时附带页面截图` : `点击附带截图发给 AI（需 vision 模型）`,
                            onClick: (n[5] ||= (e) => (y.value = !y.value)),
                          },
                          [
                            ...(n[15] ||= [
                              W(
                                `svg`,
                                { viewBox: `0 0 24 24`, fill: `none`, 'aria-hidden': `true` },
                                [
                                  W(`rect`, {
                                    x: `3`,
                                    y: `5`,
                                    width: `18`,
                                    height: `14`,
                                    rx: `2.5`,
                                    stroke: `currentColor`,
                                    'stroke-width': `1.8`,
                                  }),
                                  W(`circle`, {
                                    cx: `8.5`,
                                    cy: `10`,
                                    r: `1.6`,
                                    fill: `currentColor`,
                                  }),
                                  W(`path`, {
                                    d: `M3.5 16.5 9 12l3.2 2.8L15 12l5.5 4.5`,
                                    stroke: `currentColor`,
                                    'stroke-width': `1.8`,
                                    'stroke-linecap': `round`,
                                    'stroke-linejoin': `round`,
                                  }),
                                ],
                                -1,
                              ),
                            ]),
                          ],
                          10,
                          pg,
                        ),
                        Pn(
                          W(
                            `textarea`,
                            {
                              ref_key: `textareaRef`,
                              ref: x,
                              'onUpdate:modelValue': (n[6] ||= (e) => (v.value = e)),
                              class: `panel-input`,
                              placeholder: `说点什么…`,
                              rows: `1`,
                              'aria-label': `发送消息`,
                              onKeydown: ps(ds(ce, [`exact`, `prevent`]), [`enter`]),
                              onInput: fe,
                            },
                            null,
                            40,
                            mg,
                          ),
                          [[cs, v.value]],
                        ),
                        W(
                          `button`,
                          {
                            type: `button`,
                            class: `panel-send`,
                            disabled: !v.value.trim() || B(o).isLoading,
                            'aria-label': `发送`,
                            onClick: ce,
                          },
                          [
                            ...(n[16] ||= [
                              W(
                                `svg`,
                                { viewBox: `0 0 24 24`, fill: `none`, 'aria-hidden': `true` },
                                [
                                  W(`path`, {
                                    d: `M22 2L11 13M22 2L15 22l-4-9-9-4 20-7z`,
                                    stroke: `currentColor`,
                                    'stroke-width': `1.8`,
                                    'stroke-linecap': `round`,
                                    'stroke-linejoin': `round`,
                                  }),
                                ],
                                -1,
                              ),
                            ]),
                          ],
                          8,
                          hg,
                        ),
                      ]))
                    : (H(),
                      U(
                        V,
                        { key: 1 },
                        [
                          W(`div`, gg, [
                            G(
                              eg,
                              {
                                'voice-state': B(j),
                                'is-supported': B(M),
                                error: B(ee),
                                'loading-hint': B(N),
                                'session-ready': B(ne),
                                onToggle: se,
                              },
                              null,
                              8,
                              [`voice-state`, `is-supported`, `error`, `loading-hint`, `session-ready`],
                            ),
                            W(
                              `button`,
                              {
                                type: `button`,
                                class: P([
                                  `panel-shot-btn`,
                                  {
                                    'panel-shot-btn--active': y.value,
                                    'panel-shot-btn--light': B(h),
                                  },
                                ]),
                                'aria-pressed': y.value,
                                'aria-label': `附带截图`,
                                title: y.value ? `已开启：发送时附带页面截图` : `点击附带截图发给 AI（需 vision 模型）`,
                                onClick: (n[7] ||= (e) => (y.value = !y.value)),
                              },
                              [
                                ...(n[17] ||= [
                                  W(
                                    `svg`,
                                    { viewBox: `0 0 24 24`, fill: `none`, 'aria-hidden': `true` },
                                    [
                                      W(`rect`, {
                                        x: `3`,
                                        y: `5`,
                                        width: `18`,
                                        height: `14`,
                                        rx: `2.5`,
                                        stroke: `currentColor`,
                                        'stroke-width': `1.8`,
                                      }),
                                      W(`circle`, {
                                        cx: `8.5`,
                                        cy: `10`,
                                        r: `1.6`,
                                        fill: `currentColor`,
                                      }),
                                      W(`path`, {
                                        d: `M3.5 16.5 9 12l3.2 2.8L15 12l5.5 4.5`,
                                        stroke: `currentColor`,
                                        'stroke-width': `1.8`,
                                        'stroke-linecap': `round`,
                                        'stroke-linejoin': `round`,
                                      }),
                                    ],
                                    -1,
                                  ),
                                ]),
                              ],
                              10,
                              _g,
                            ),
                          ]),
                          W(`div`, vg, [
                            Pn(
                              W(
                                `textarea`,
                                {
                                  ref_key: `textareaRef`,
                                  ref: x,
                                  'onUpdate:modelValue': (n[8] ||= (e) => (v.value = e)),
                                  class: `panel-input`,
                                  placeholder: `说点什么…`,
                                  rows: `1`,
                                  'aria-label': `发送消息`,
                                  onKeydown: ps(ds(ce, [`exact`, `prevent`]), [`enter`]),
                                  onInput: fe,
                                },
                                null,
                                40,
                                yg,
                              ),
                              [[cs, v.value]],
                            ),
                            W(
                              `button`,
                              {
                                type: `button`,
                                class: `panel-send`,
                                disabled: !v.value.trim() || B(o).isLoading,
                                'aria-label': `发送`,
                                onClick: ce,
                              },
                              [
                                ...(n[18] ||= [
                                  W(
                                    `svg`,
                                    { viewBox: `0 0 24 24`, fill: `none`, 'aria-hidden': `true` },
                                    [
                                      W(`path`, {
                                        d: `M22 2L11 13M22 2L15 22l-4-9-9-4 20-7z`,
                                        stroke: `currentColor`,
                                        'stroke-width': `1.8`,
                                        'stroke-linecap': `round`,
                                        'stroke-linejoin': `round`,
                                      }),
                                    ],
                                    -1,
                                  ),
                                ]),
                              ],
                              8,
                              bg,
                            ),
                          ]),
                        ],
                        64,
                      )),
                ],
                2,
              ),
            ],
            6,
          )
        )
      },
    }),
    [[`__scopeId`, `data-v-c6a3034e`]],
  )
function Sg(e) {
  return /(?:有限公司|有限责任公司|股份有限公司|集团有限公司)/.test((e || ``).trim())
}
function Cg(e, t) {
  return t?.web_error
    ? `联网检索暂不可用，将按您填写的名称继续`
    : t?.query_incomplete || !Sg(e)
      ? `联网检索未找到公司全称，请补全后重试或继续手动填写`
      : `联网检索未匹配到该公司，将按您填写的名称继续`
}
function wg(e, t) {
  return t?.web_error
    ? `可继续填写系统类型；请稍后重试联网核对`
    : t?.found
      ? `可继续填写系统类型`
      : `可继续填写系统类型；补全公司全称后请再次点选系统类型`
}
var Tg = [`爱企查`, `启信宝`, `企查查`, `天眼查`, `水滴信用`, `百度百科`, `百度知道`, `企查猫`, `利查查`],
  Eg = `点选「行业 / 业务类型」开始匹配公司`,
  Dg = {
    contact: `/api/public/contact/companies/match`,
    workbench: `/api/market/workbench/companies/match`,
  }
function Og(e) {
  let t = (e || ``).trim()
  if (!t) return ``
  t = t.split(/\s*[-_|｜]\s*/)[0].trim()
  for (let e of Tg)
    t.endsWith(e) &&
      (t = t
        .slice(0, -e.length)
        .replace(/[\s\-_|｜]+$/, ``)
        .trim())
  return t.replace(/\s+/g, ``).slice(0, 80)
}
function kg(e) {
  if (!e || typeof e != `object`) return e
  let t = (e) => (e?.name ? { ...e, name: Og(e.name) } : e),
    n = [],
    r = new Set()
  for (let i of Array.isArray(e.suggestions) ? e.suggestions : []) {
    let e = t(i),
      a = e?.name || ``
    !a || r.has(a) || (r.add(a), n.push(e))
  }
  let i = e.matched ? t(e.matched) : null
  return (i?.name && !n.some((e) => e.name === i.name) && n.unshift(i), { ...e, matched: i ?? null, suggestions: n })
}
function Ag(e = `contact`) {
  let t = e === `workbench`,
    n = z(``),
    r = z(``),
    i = z(`hidden`),
    a = z(``),
    o = z(``),
    s = z([]),
    c = z(!1),
    l = z(!1),
    u = z(!1),
    d = 0,
    f = null,
    p = ``,
    m = !1,
    h = Gt(null)
  function g() {
    ;((n.value = ``),
      (r.value = ``),
      (i.value = `hidden`),
      (a.value = ``),
      (s.value = []),
      (c.value = !1),
      (o.value = ``),
      (h.value = null),
      (p = ``),
      (u.value = !1))
  }
  function _() {
    ;((i.value = `hidden`), (s.value = []), (c.value = !1))
  }
  function v(e, t) {
    return e?.web_used || t.source === `web` ? `已通过联网检索核对，可点「插入对话」或继续编辑` : `已匹配历史记录，可插入对话`
  }
  function y(e, t) {
    return t?.web_error
      ? `可手动继续输入公司名并插入对话`
      : t?.found
        ? `请从下方选择公司全称`
        : `补全公司全称后重试，或仍可使用当前输入插入对话`
  }
  function b(e, l) {
    let u = l.trim()
    if (u.length < 2) {
      g()
      return
    }
    let d = e ? kg(e) : null
    h.value = d
    let f = d?.matched,
      p = Array.isArray(d?.suggestions) ? d.suggestions : [],
      m = p.length > 1
    if (f?.name && !m) {
      ;((o.value = f.name),
        (i.value = `hidden`),
        (a.value = ``),
        (n.value = t
          ? v(d, f)
          : d?.web_used || f.source === `web`
            ? `已通过百度/企查查类检索核对，请继续填写系统类型`
            : `已匹配，请继续填写系统类型`),
        (r.value = `ok`),
        (c.value = !1),
        (s.value = []),
        t || x(u, f))
      return
    }
    if (f?.name && m) {
      ;((o.value = ``),
        (i.value = `hidden`),
        (n.value = t ? `请从下方选择公司全称` : `请从下方选择公司全称（搜索词仍保留在输入框）`),
        (r.value = ``),
        (s.value = p),
        (c.value = p.length > 0))
      return
    }
    if (d && !d.found) {
      ;((o.value = ``),
        (i.value = `warn`),
        (a.value = Cg(u, d)),
        (n.value = t ? y(u, d) : wg(u, d)),
        (r.value = `new`),
        (s.value = p),
        (c.value = p.length > 0))
      return
    }
    ;((o.value = ``),
      (i.value = `hidden`),
      (n.value = p.length ? `请选择下方匹配的公司名称` : ``),
      (r.value = ``),
      (s.value = p),
      (c.value = p.length > 0))
  }
  async function x(e, t) {
    let n = document.getElementById(`intake-ai-company`)
    n && (n.value = e)
    let r = Lu()
    r?.selectAiCompany && t?.name && r.selectAiCompany(t)
  }
  async function S(t) {
    let o = t.trim()
    if (o.length < 2) {
      g()
      return
    }
    let s = ++d
    ;((m = !0), (l.value = !0), _(), (n.value = `正在用「${o}」匹配公司名称…`), (r.value = ``))
    try {
      let t = Dg[e],
        c = { ...(_d() || {}) },
        l = await fetch(`${t}?q=${encodeURIComponent(o)}&limit=8&web=true`, {
          credentials: `same-origin`,
          headers: Object.keys(c).length ? c : void 0,
        })
      if (s !== d) return
      if (!l.ok) {
        if (l.status === 429) {
          ;((i.value = `warn`), (a.value = `匹配请求过于频繁`), (n.value = `请等待约 1 分钟后再试，或继续手动填写`), (r.value = `new`))
          return
        }
        ;((i.value = `warn`),
          (a.value = `匹配服务暂时不可用`),
          (n.value = l.status === 404 ? `当前页面未连上官网 API，请用 xiu-ci.com 打开联系页` : `请稍后重试或继续手动填写`),
          (r.value = `new`))
        return
      }
      let u = kg(await l.json())
      if (s !== d) return
      ;((p = o), b(u, o))
    } catch {
      if (s !== d) return
      ;((i.value = `warn`),
        (a.value = `无法连接匹配服务`),
        (n.value = typeof location < `u` && location.protocol === `file:` ? `本地预览无法匹配，请通过官网访问` : `网络异常，请稍后重试`),
        (r.value = `new`))
    } finally {
      s === d && ((m = !1), (l.value = !1))
    }
  }
  function C(e) {
    ;(f && clearTimeout(f),
      (f = setTimeout(() => {
        f = null
        let t = e().trim()
        if (!(t.length < 2)) {
          if (t === p && h.value) {
            b(h.value, t)
            return
          }
          m || S(t)
        }
      }, 400)))
  }
  function w(e) {
    e().trim().length < 2 || C(e)
  }
  function T(e, i) {
    let a = e.trim(),
      s = document.getElementById(`intake-ai-company`)
    if ((s && (s.value = e), a !== p && (f && clearTimeout(f), (f = null), (h.value = null), (p = ``), (o.value = ``), _()), !u.value))
      if (t) {
        if (((u.value = !0), a.length >= 2)) {
          w(i)
          return
        }
      } else {
        ;((n.value = a.length >= 2 ? Eg : ``), (r.value = ``))
        return
      }
    if (a.length >= 2 && a !== p) {
      w(i)
      return
    }
    a.length >= 2 ? ((n.value = Eg), (r.value = ``)) : ((n.value = ``), (r.value = ``))
  }
  function E() {
    u.value = !0
  }
  function D(e) {
    ;((u.value = !0), w(e))
  }
  function O() {}
  async function k(e, l) {
    let u = Og(e?.name)
    if (
      u &&
      ((o.value = u),
      (i.value = `hidden`),
      (a.value = ``),
      (n.value = t ? `已选定公司，可插入对话` : `已选定公司，请继续填写系统类型`),
      (r.value = `ok`),
      (c.value = !1),
      (s.value = []),
      (p = l.trim()),
      !t)
    ) {
      let t = document.getElementById(`intake-ai-company`)
      t && (t.value = l.trim())
      let n = Lu()
      n?.selectAiCompany && n.selectAiCompany({ ...e, name: u, exact: !0 })
    }
  }
  function A(e) {
    return (o.value || e).trim()
  }
  return {
    hint: n,
    hintVariant: r,
    resultMode: i,
    resultText: a,
    suggestions: s,
    showSuggestions: c,
    matching: l,
    matchUiUnlocked: u,
    resolvedName: o,
    resetUi: g,
    unlockMatchUi: E,
    onCompanyInput: T,
    onIndustryFocus: D,
    onIndustryInput: O,
    selectSuggestion: k,
    getCompanyForSubmit: A,
  }
}
var jg = { class: `corp-intake-modal__head` },
  Mg = [`disabled`],
  Ng = { class: `form-field form-field--company-match` },
  Pg = { class: `intake-company-wrap` },
  Fg = [`disabled`, `aria-expanded`],
  Ig = { key: 0, class: `intake-company-result intake-company-result--warn`, role: `status` },
  Lg = { class: `intake-company-result__text` },
  Rg = { key: 1, class: `intake-company-suggest`, role: `listbox` },
  zg = [`onClick`],
  Bg = { class: `form-field` },
  Vg = [`disabled`],
  Hg = { key: 0, class: `corp-intake-modal__error`, role: `alert` },
  Ug = [`disabled`],
  Wg = br({
    __name: `CorpContactIntakeModal`,
    setup(e) {
      let t = tu(),
        { isOpen: n } = $s(t),
        r = z(``),
        i = z(``),
        a = z(!1),
        o = z(``),
        s = z(null),
        {
          hint: c,
          hintVariant: l,
          resultMode: u,
          resultText: d,
          suggestions: f,
          showSuggestions: p,
          matchUiUnlocked: m,
          resetUi: h,
          onCompanyInput: g,
          onIndustryFocus: _,
          onIndustryInput: v,
          selectSuggestion: y,
          getCompanyForSubmit: b,
        } = Ag(),
        x = q(() => (c.value || ``).trim()),
        S = q(() => r.value.trim().length > 0 && i.value.trim().length > 0),
        C = 0
      function w() {
        return `corp-intake-modal-${Date.now()}-${++C}`
      }
      function T(e) {
        typeof document > `u` ||
          ((document.documentElement.style.overflow = e ? `hidden` : ``), (document.body.style.overflow = e ? `hidden` : ``))
      }
      let E = () => r.value
      function D() {
        g(r.value, E)
      }
      function O() {
        ;(_(E), A())
      }
      function k() {
        ;(v(), A())
      }
      function A() {
        let e = document.getElementById(`intake-ai-system`)
        e && (e.value = i.value)
      }
      Vn(i, () => A())
      function j() {
        a.value || Gm()
      }
      ;(Vn(Hm, (e) => {
        e ? ((o.value = ``), h(), T(!0), xn(() => s.value?.focus())) : T(!1)
      }),
        Vn(n, (e) => {
          e || Gm()
        }),
        Rr(() => {
          T(!1)
        }))
      async function ee() {
        o.value = ``
        let e = b(r.value),
          n = i.value.trim()
        if ((A(), !e || !n)) {
          o.value = `请填写公司名称和行业 / 业务类型。`
          return
        }
        ;((a.value = !0),
          t.addMessage({
            id: w(),
            role: `user`,
            content: `公司：${e}\n行业：${n}`,
            timestamp: Date.now(),
          }),
          t.addMessage({
            id: w(),
            role: `assistant`,
            content: `…`,
            timestamp: Date.now(),
            isLoading: !0,
          }),
          (t.isLoading = !0))
        try {
          let r = await Uu(e, n)
          r.ok
            ? ((Um.value = !0),
              Gm(),
              t.updateLastMessage({
                isLoading: !1,
                content: r.message || `已预填下方问卷，请逐步核对；联系方式不会自动填写，请自行补全后提交。`,
              }))
            : ((o.value = r.message), t.updateLastMessage({ isLoading: !1, content: r.message }))
        } catch {
          let e = `网络异常，请稍后重试。`
          ;((o.value = e), t.updateLastMessage({ isLoading: !1, content: e }))
        } finally {
          ;((a.value = !1), (t.isLoading = !1))
        }
      }
      return (e, t) => (
        H(),
        ma(nr, { to: `body` }, [
          G(
            fo,
            { name: `corp-intake-modal` },
            {
              default: Nn(() => [
                B(Hm)
                  ? (H(),
                    U(
                      `div`,
                      {
                        key: 0,
                        class: `corp-intake-modal`,
                        role: `presentation`,
                        onClick: ds(j, [`self`]),
                      },
                      [
                        W(
                          `div`,
                          {
                            class: `corp-intake-modal__sheet`,
                            role: `dialog`,
                            'aria-modal': `true`,
                            'aria-labelledby': `corp-intake-modal-title`,
                            onClick: (t[2] ||= ds(() => {}, [`stop`])),
                          },
                          [
                            W(`header`, jg, [
                              (t[3] ||= W(
                                `div`,
                                null,
                                [
                                  W(
                                    `h3`,
                                    {
                                      id: `corp-intake-modal-title`,
                                      class: `corp-intake-modal__title`,
                                    },
                                    `AI 一键填表`,
                                  ),
                                  W(
                                    `p`,
                                    { class: `corp-intake-modal__desc` },
                                    ` 填写公司与行业后点「发送」，将自动写好页面上的需求问卷。 `,
                                  ),
                                ],
                                -1,
                              )),
                              W(
                                `button`,
                                {
                                  type: `button`,
                                  class: `corp-intake-modal__close`,
                                  'aria-label': `关闭`,
                                  disabled: a.value,
                                  onClick: j,
                                },
                                ` × `,
                                8,
                                Mg,
                              ),
                            ]),
                            W(
                              `form`,
                              { class: `corp-intake-modal__form`, onSubmit: ds(ee, [`prevent`]) },
                              [
                                W(`div`, Ng, [
                                  (t[4] ||= W(`label`, { for: `corp-intake-modal-company` }, `公司名称`, -1)),
                                  W(`div`, Pg, [
                                    Pn(
                                      W(
                                        `input`,
                                        {
                                          id: `corp-intake-modal-company`,
                                          ref_key: `companyInputRef`,
                                          ref: s,
                                          'onUpdate:modelValue': (t[0] ||= (e) => (r.value = e)),
                                          class: `intake-company-input`,
                                          type: `text`,
                                          maxlength: `80`,
                                          autocomplete: `off`,
                                          'aria-autocomplete': `list`,
                                          placeholder: `例如：成都某某贸易有限公司`,
                                          disabled: a.value,
                                          'aria-expanded': B(p) ? `true` : `false`,
                                          onInput: D,
                                        },
                                        null,
                                        40,
                                        Fg,
                                      ),
                                      [[cs, r.value]],
                                    ),
                                    B(m) && B(u) === `warn` && B(d).trim() ? (H(), U(`div`, Ig, [W(`span`, Lg, F(B(d)), 1)])) : K(``, !0),
                                    B(m) && B(p) && B(f).length
                                      ? (H(),
                                        U(`ul`, Rg, [
                                          (H(!0),
                                          U(
                                            V,
                                            null,
                                            Gr(
                                              B(f),
                                              (e, t) => (
                                                H(),
                                                U(`li`, { key: t }, [
                                                  W(
                                                    `button`,
                                                    {
                                                      type: `button`,
                                                      role: `option`,
                                                      onClick: (t) => B(y)(e, r.value),
                                                    },
                                                    F(e.name),
                                                    9,
                                                    zg,
                                                  ),
                                                ])
                                              ),
                                            ),
                                            128,
                                          )),
                                        ]))
                                      : K(``, !0),
                                  ]),
                                  B(m) && x.value
                                    ? (H(),
                                      U(
                                        `p`,
                                        {
                                          key: 0,
                                          class: P([
                                            `intake-company-status`,
                                            {
                                              'intake-company-status--ok': B(l) === `ok`,
                                              'intake-company-status--new': B(l) === `new`,
                                            },
                                          ]),
                                          'aria-live': `polite`,
                                        },
                                        F(B(c)),
                                        3,
                                      ))
                                    : K(``, !0),
                                ]),
                                W(`div`, Bg, [
                                  (t[5] ||= W(`label`, { for: `corp-intake-modal-system` }, `行业 / 业务类型`, -1)),
                                  Pn(
                                    W(
                                      `input`,
                                      {
                                        id: `corp-intake-modal-system`,
                                        'onUpdate:modelValue': (t[1] ||= (e) => (i.value = e)),
                                        type: `text`,
                                        maxlength: `120`,
                                        placeholder: `例如：贸易跟单、制造业、金蝶 ERP`,
                                        disabled: a.value,
                                        onFocus: O,
                                        onInput: k,
                                      },
                                      null,
                                      40,
                                      Vg,
                                    ),
                                    [[cs, i.value]],
                                  ),
                                ]),
                                o.value ? (H(), U(`p`, Hg, F(o.value), 1)) : K(``, !0),
                                W(
                                  `button`,
                                  {
                                    type: `submit`,
                                    class: `corp-intake-modal__send`,
                                    disabled: a.value || !S.value,
                                  },
                                  F(a.value ? `正在预填…` : `发送`),
                                  9,
                                  Ug,
                                ),
                              ],
                              32,
                            ),
                          ],
                        ),
                      ],
                    ))
                  : K(``, !0),
              ]),
              _: 1,
            },
          ),
        ])
      )
    },
  }),
  Gg = {
    key: 0,
    class: `tts-sub`,
    role: `status`,
    'aria-live': `polite`,
    'aria-label': `朗读字幕`,
  },
  Kg = { class: `tts-sub__stack` },
  qg = { key: 0, class: `tts-sub__line tts-sub__line--prev` },
  Jg = { class: `tts-sub__zh` },
  Yg = { class: `tts-sub__line tts-sub__line--cur` },
  Xg = { class: `tts-sub__zh` },
  Zg = { key: 0, class: `tts-sub__en` },
  Qg = { key: 1, class: `tts-sub__en tts-sub__en--pending` },
  $g = { key: 1, class: `tts-sub__line tts-sub__line--next` },
  e_ = { class: `tts-sub__zh` },
  t_ = mp(
    br({
      __name: `TtsSubtitleOverlay`,
      setup(e) {
        let { visible: t, current: n, prev: r, next: i, dismiss: a } = Df()
        return (e, o) => (
          H(),
          ma(nr, { to: `body` }, [
            G(
              fo,
              { name: `tts-sub` },
              {
                default: Nn(() => [
                  B(t) && B(n)
                    ? (H(),
                      U(`div`, Gg, [
                        W(
                          `button`,
                          {
                            type: `button`,
                            class: `tts-sub__close`,
                            'aria-label': `关闭字幕`,
                            title: `关闭`,
                            onClick: (o[0] ||= (...e) => B(a) && B(a)(...e)),
                          },
                          [
                            ...(o[1] ||= [
                              W(
                                `svg`,
                                {
                                  viewBox: `0 0 16 16`,
                                  width: `14`,
                                  height: `14`,
                                  fill: `none`,
                                  'aria-hidden': `true`,
                                },
                                [
                                  W(`path`, {
                                    d: `M4 4l8 8M12 4L4 12`,
                                    stroke: `currentColor`,
                                    'stroke-width': `1.6`,
                                    'stroke-linecap': `round`,
                                  }),
                                ],
                                -1,
                              ),
                            ]),
                          ],
                        ),
                        W(`div`, Kg, [
                          B(r) ? (H(), U(`p`, qg, [W(`span`, Jg, F(B(r).zh), 1)])) : K(``, !0),
                          W(`div`, Yg, [
                            W(`p`, Xg, F(B(n).zh), 1),
                            B(n).en ? (H(), U(`p`, Zg, F(B(n).en), 1)) : (H(), U(`p`, Qg, `Translating…`)),
                          ]),
                          B(i) ? (H(), U(`p`, $g, [W(`span`, e_, F(B(i).zh), 1)])) : K(``, !0),
                        ]),
                      ]))
                    : K(``, !0),
                ]),
                _: 1,
              },
            ),
          ])
        )
      },
    }),
    [[`__scopeId`, `data-v-66f762c4`]],
  ),
  n_ = br({
    __name: `CorpButlerRoot`,
    setup(e) {
      let t = tu(),
        { isOpen: n, showPermissionDialog: r, position: i } = $s(t),
        { handleInput: a, runIntakeTask: o } = gf(),
        s = z(null),
        c = z(!1),
        l = null,
        u = 0
      function d() {
        let e = s.value
        e && ((s.value = null), t.openPanel(), o(e))
      }
      async function f(e) {
        if (typeof window > `u` || !t.consentGiven || !Jf()) return
        let { pageId: n, text: r } = $f(window.location.pathname || `/`)
        if ((e === `page` && Xf(n)) || !r) return
        Zf(n)
        let i = t.messages[t.messages.length - 1]
        ;(i && i.role === `assistant` && i.content === r) ||
          t.addMessage({
            id: `corp-intro-${n}-${Date.now()}`,
            role: `assistant`,
            content: r,
            timestamp: Date.now(),
          })
        let a = ++u
        c.value = !0
        try {
          await sp(r)
        } finally {
          a === u && (c.value = !1)
        }
      }
      function p(e, t = 600) {
        ;(l != null && (window.clearTimeout(l), (l = null)),
          (l = window.setTimeout(() => {
            ;((l = null), f(e))
          }, t)))
      }
      function m() {
        ;(t.grantConsent(), d(), p(`consent`, 480))
      }
      function h(e) {
        e || (ip(), (c.value = !1))
      }
      let g = q(() => {
          if (typeof window > `u`) return !1
          let e = window.location.pathname
          return /\/contact(?:\.html)?\/?$/i.test(e)
        }),
        _ = z(ru()),
        v = q(() => g.value && _.value)
      function y() {
        _.value = ru()
      }
      function b() {
        let e = pu(i.value.x, i.value.y)
        t.savePosition(e.x, e.y)
      }
      function x(e) {
        let n = e.detail || {}
        if (n.filled) {
          t.consentGiven && t.openPanel()
          return
        }
        let r = {
          label: `AI 一键填单`,
          task: `intake_fill`,
          message: n.message || `请根据公司与系统类型预填需求问卷`,
        }
        if ((n.prompt?.trim() && (r.payload = { prompt: n.prompt.trim() }), !t.consentGiven)) {
          ;((s.value = r), (t.showPermissionDialog = !0))
          return
        }
        ;(t.openPanel(), o(r))
      }
      function S() {
        if (!(typeof window > `u`) && Su(window.location.pathname) && ru()) {
          try {
            if (sessionStorage.getItem(`xc-contact-butler-intro-v2`) === `1`) return
            sessionStorage.setItem(`xc-contact-butler-intro-v2`, `1`)
          } catch {
            return
          }
          window.setTimeout(() => {
            t.openPanel()
          }, 700)
        }
      }
      return (
        Fr(() => {
          ;(window.addEventListener(`resize`, b),
            window.addEventListener(`xc-corp-intake-assist`, x),
            window.matchMedia(`(max-width: 960px)`).addEventListener(`change`, y),
            S(),
            t.consentGiven && Jf() && p(`page`, 900))
        }),
        Rr(() => {
          ;(window.removeEventListener(`resize`, b),
            window.removeEventListener(`xc-corp-intake-assist`, x),
            window.matchMedia(`(max-width: 960px)`).removeEventListener(`change`, y),
            l != null && window.clearTimeout(l),
            ip(),
            (c.value = !1))
        }),
        (e, i) => (
          H(),
          ma(nr, { to: `body` }, [
            W(
              `div`,
              {
                class: P([
                  `butler-float-root butler-float-root--corp`,
                  {
                    'butler-float-root--contact-page': g.value,
                    'butler-float-root--speaking': c.value,
                  },
                ]),
              },
              [
                B(r)
                  ? (H(),
                    ma(hp, {
                      key: 0,
                      'corp-mode': ``,
                      onAgree: m,
                      onDismiss: (i[0] ||= (e) => B(t).dismissLater()),
                    }))
                  : K(``, !0),
                G(Fp, { 'is-speaking': c.value, 'force-light': ``, 'corp-mode': `` }, null, 8, [`is-speaking`]),
                G(
                  fo,
                  { name: `panel-pop` },
                  {
                    default: Nn(() => [
                      B(n)
                        ? (H(),
                          ma(
                            xg,
                            {
                              key: 0,
                              'corp-mode': ``,
                              'handle-input': B(a),
                              'run-intake-task': B(o),
                              onProactiveIntroChange: h,
                            },
                            null,
                            8,
                            [`handle-input`, `run-intake-task`],
                          ))
                        : K(``, !0),
                    ]),
                    _: 1,
                  },
                ),
                v.value ? (H(), ma(Wg, { key: 1 })) : K(``, !0),
                G(t_),
              ],
              2,
            ),
          ])
        )
      )
    },
  }),
  r_ = br({
    __name: `CorpButlerApp`,
    setup(e) {
      return (e, t) => (H(), ma(n_))
    },
  })
document.documentElement.dataset.workbenchTheme = `light`
var i_ = Jl({
  history: ml(typeof window < `u` ? window.location.pathname + window.location.search : `/`),
  routes: [{ path: `/:pathMatch(.*)*`, name: `corp-static`, component: { template: `<div></div>` } }],
})
async function a_() {
  let e = document.getElementById(`xc-corp-butler-root`)
  if (!e) {
    console.warn(`[xc-corp-butler] 未找到 #xc-corp-butler-root，管家未挂载`)
    return
  }
  let t = Rs(),
    n = _s(r_)
  ;(n.use(t), n.use(i_), await i_.isReady())
  let r = tu(t)
  r.closePanel()
  let i = fu()
  ;(r.savePosition(i.x, i.y), n.mount(e))
}
a_()
export { z as i, Yd as n, Qs as r, uh as t }
