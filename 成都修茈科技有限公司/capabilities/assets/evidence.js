/*
 * 能力中心证据原件：/api/public/evidence/<name> 由 MODstore 签发短时效 COS 预签名地址（302）。
 * - 后端或对象存储不可用时，自动改用站内副本 /capabilities/assets/evidence/<name>；
 * - 「核验哈希」对照页面登记的 SHA-256 与对象存储元数据 x-cos-meta-sha256。
 */
(function () {
  'use strict';
  var API = '/api/public/evidence/';
  var LOCAL = '/capabilities/assets/evidence/';
  var fallenBack = false;

  function localOf(url) {
    if (!url) return null;
    var i = url.indexOf(API);
    if (i === -1) return null;
    return LOCAL + url.slice(i + API.length).split('?')[0];
  }

  function fallbackElement(el) {
    var attr = el.tagName === 'A' ? 'href' : 'src';
    var local = localOf(el.getAttribute(attr));
    if (!local) return false;
    el.setAttribute(attr, local);
    if (el.tagName === 'VIDEO' && typeof el.load === 'function') el.load();
    return true;
  }

  function fallbackAll() {
    if (fallenBack) return;
    fallenBack = true;
    var nodes = document.querySelectorAll('[src*="' + API + '"], [href*="' + API + '"]');
    for (var i = 0; i < nodes.length; i++) fallbackElement(nodes[i]);
  }

  // 单个原件加载失败（含预签名过期、COS 拒绝）→ 只回退这一个。
  document.addEventListener('error', function (ev) {
    var el = ev.target;
    if (el && (el.tagName === 'IMG' || el.tagName === 'VIDEO')) fallbackElement(el);
  }, true);

  function scanBroken() {
    var imgs = document.querySelectorAll('img[src*="' + API + '"]');
    for (var i = 0; i < imgs.length; i++) {
      if (imgs[i].complete && imgs[i].naturalWidth === 0) fallbackElement(imgs[i]);
    }
    var vids = document.querySelectorAll('video[src*="' + API + '"]');
    for (var j = 0; j < vids.length; j++) {
      if (vids[j].error || vids[j].networkState === 3) fallbackElement(vids[j]);
    }
  }

  function probe() {
    if (!window.fetch) return fallbackAll();
    var timer = null;
    var ctl = window.AbortController ? new AbortController() : null;
    if (ctl) timer = setTimeout(function () { ctl.abort(); }, 4000);
    fetch(API + '_status', { cache: 'no-store', signal: ctl ? ctl.signal : undefined })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (!d || !d.ok) fallbackAll(); })
      .catch(fallbackAll)
      .then(function () { if (timer) clearTimeout(timer); });
  }

  function verify(box) {
    var name = box.getAttribute('data-evidence');
    var expected = box.getAttribute('data-sha256');
    var out = box.querySelector('.cap-verify-result');
    var btn = box.querySelector('.cap-verify-btn');
    if (btn) btn.disabled = true;
    out.textContent = '核验中…';
    out.className = 'cap-verify-result';
    fetch(API + 'verify/' + encodeURIComponent(name), { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var ok = d && d.ok && d.match && d.cos_sha256 === expected;
        if (ok) {
          out.textContent = '✓ 对象存储元数据 SHA-256 与本页登记一致（' + d.cos_sha256.slice(0, 12) + '…，' + d.cos_size + ' 字节）';
          out.className = 'cap-verify-result is-ok';
        } else if (d && d.cos_configured === false) {
          out.textContent = '对象存储暂未启用，当前展示站内副本；可下载原件用 sha256sum 核对。';
          out.className = 'cap-verify-result is-warn';
        } else {
          out.textContent = '✗ 未能核验：' + ((d && d.reason) || '对象存储哈希与本页登记不一致') + '；页面原件改由站内副本提供。';
          out.className = 'cap-verify-result is-bad';
        }
      })
      .catch(function () {
        out.textContent = '核验服务暂不可用；可下载原件用 sha256sum 核对。';
        out.className = 'cap-verify-result is-warn';
      })
      .then(function () { if (btn) btn.disabled = false; });
  }

  document.addEventListener('click', function (ev) {
    var btn = ev.target && ev.target.closest ? ev.target.closest('.cap-verify-btn') : null;
    if (btn) verify(btn.parentNode);
  });

  scanBroken();
  probe();
  window.addEventListener('load', scanBroken);
})();
