// Minimal Chrome DevTools Protocol driver for the XCAGI Electron shell.
// Node 22+ (global WebSocket). No external deps.
import fs from 'node:fs';
import path from 'node:path';

const CDP_HTTP = process.env.CDP_HTTP || 'http://127.0.0.1:9222';

export async function listTargets() {
  const res = await fetch(`${CDP_HTTP}/json`);
  return await res.json();
}

export async function pickPageTarget(match = '') {
  const targets = await listTargets();
  const pages = targets.filter((t) => t.type === 'page');
  if (!pages.length) throw new Error('no page target');
  if (!match) return pages[0];
  const hit = pages.find((t) => (t.url || '').includes(match) || (t.title || '').includes(match));
  return hit || pages[0];
}

export class Session {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.events = [];
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(JSON.stringify(msg.error)));
        else resolve(msg.result);
      } else if (msg.method) {
        this.events.push(msg);
      }
    });
  }

  static async connect(match = '') {
    const target = await pickPageTarget(match);
    const ws = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      ws.addEventListener('open', resolve, { once: true });
      ws.addEventListener('error', (e) => reject(new Error('ws error ' + e.message)), { once: true });
    });
    const s = new Session(ws);
    s.target = target;
    await s.send('Page.enable');
    await s.send('Runtime.enable');
    return s;
  }

  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error(`timeout ${method}`));
        }
      }, 60000);
    });
  }

  close() {
    try { this.ws.close(); } catch {}
  }

  async eval(expression, awaitPromise = true) {
    const r = await this.send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise,
      userGesture: true,
    });
    if (r.exceptionDetails) {
      throw new Error('eval exception: ' + JSON.stringify(r.exceptionDetails).slice(0, 800));
    }
    return r.result?.value;
  }

  async screenshot(file) {
    const r = await this.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, Buffer.from(r.data, 'base64'));
    return file;
  }

  // Real mouse click at the element centre (dispatches trusted-ish input events).
  async clickSelector(selector) {
    const box = await this.eval(`(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) return null;
      el.scrollIntoView({block:'center', inline:'center'});
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) return null;
      return {x: r.left + r.width/2, y: r.top + r.height/2, w: r.width, h: r.height};
    })()`);
    if (!box) throw new Error(`clickSelector: not found/zero-size: ${selector}`);
    const { x, y } = box;
    await this.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, button: 'none', clickCount: 0 });
    await this.send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
    await this.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 });
    return box;
  }

  async clickText(text, { tag = '*' } = {}) {
    const sel = await this.eval(`(() => {
      const wanted = ${JSON.stringify(text)};
      const nodes = [...document.querySelectorAll(${JSON.stringify(tag)})];
      const hit = nodes.find((el) => (el.innerText || el.textContent || '').trim() === wanted)
        || nodes.find((el) => (el.innerText || el.textContent || '').includes(wanted) && el.children.length === 0);
      if (!hit) return null;
      hit.scrollIntoView({block:'center', inline:'center'});
      const r = hit.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) return null;
      document.querySelectorAll('[data-xcagi-click]').forEach((n) => n.removeAttribute('data-xcagi-click'));
      hit.setAttribute('data-xcagi-click', '1');
      return true;
    })()`);
    if (!sel) throw new Error(`clickText: not found: ${text}`);
    return await this.clickSelector('[data-xcagi-click]');
  }

  // Click a button/element by visible text scoped inside a container selector.
  async clickTextIn(scope, text) {
    const ok = await this.eval(`(() => {
      const root = document.querySelector(${JSON.stringify(scope)});
      if (!root) return 'no-scope';
      const wanted = ${JSON.stringify(text)};
      const nodes = [...root.querySelectorAll('button,a,div,span,li')];
      const hit = nodes.find((el) => (el.innerText || '').trim() === wanted)
        || nodes.find((el) => (el.innerText || '').includes(wanted) && el.children.length === 0);
      if (!hit) return 'no-target';
      hit.scrollIntoView({block:'center', inline:'center'});
      const r = hit.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) return 'zero-size';
      document.querySelectorAll('[data-xcagi-click]').forEach((n) => n.removeAttribute('data-xcagi-click'));
      hit.setAttribute('data-xcagi-click', '1');
      return true;
    })()`);
    if (ok !== true) throw new Error(`clickTextIn(${scope}, ${text}): ${ok}`);
    return await this.clickSelector('[data-xcagi-click]');
  }

  async typeInto(selector, value) {
    const ok = await this.eval(`(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) return false;
      el.focus();
      const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
      if (setter) setter.call(el, ${JSON.stringify(value)}); else el.value = ${JSON.stringify(value)};
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    })()`);
    if (!ok) throw new Error(`typeInto: not found: ${selector}`);
  }

  // Select an <option> by value (default) or by visible text.
  async selectOption(selector, value, byText = false) {
    const ok = await this.eval(`(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el || el.tagName !== 'SELECT') return 'not-a-select';
      const opts = [...el.options];
      const wanted = ${JSON.stringify(value)};
      const opt = ${byText ? 'true' : 'false'}
        ? opts.find((o) => (o.text || '').trim() === wanted || (o.text || '').includes(wanted))
        : opts.find((o) => o.value === wanted);
      if (!opt) return 'no-option:' + wanted;
      el.value = opt.value;
      el.dispatchEvent(new Event('change', { bubbles: true }));
      el.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    })()`);
    if (ok !== true) throw new Error(`selectOption(${selector}, ${value}): ${ok}`);
  }

  // Find any <select> that has an option matching the given text and select it.
  async selectAnywhereByText(text) {
    const r = await this.eval(`(() => {
      const vis = (el) => { const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden'; };
      const wanted = ${JSON.stringify(text)};
      for (const sel of [...document.querySelectorAll('select')].filter(vis)) {
        const opt = [...sel.options].find((o) => (o.text || '').includes(wanted));
        if (opt) {
          sel.value = opt.value;
          sel.dispatchEvent(new Event('change', { bubbles: true }));
          sel.dispatchEvent(new Event('input', { bubbles: true }));
          return 'selected:' + (opt.text || '').trim();
        }
      }
      return 'no-select-with-option:' + wanted;
    })()`);
    if (typeof r !== 'string' || !r.startsWith('selected:')) throw new Error(`selectAnywhereByText(${text}): ${r}`);
    return r;
  }

  // Set <input type=file> files via CDP (real user-equivalent selection; fires change).
  async setFileInput(selector, filePath) {
    const r = await this.send('Runtime.evaluate', {
      expression: `document.querySelector(${JSON.stringify(selector)})`,
      returnByValue: false,
      awaitPromise: false,
    });
    const objectId = r.result?.objectId;
    if (!objectId) throw new Error(`setFileInput: not found: ${selector}`);
    await this.send('DOM.enable');
    await this.send('DOM.setFileInputFiles', { files: [filePath], objectId });
    return filePath;
  }

  async waitForSelector(selector, timeoutMs = 30000) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const found = await this.eval(`!!document.querySelector(${JSON.stringify(selector)})`, false);
      if (found) return true;
      await new Promise((r) => setTimeout(r, 500));
    }
    throw new Error(`waitForSelector timeout: ${selector}`);
  }

  async waitForText(text, timeoutMs = 30000) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const found = await this.eval(
        `(document.body?.innerText || '').includes(${JSON.stringify(text)})`, false);
      if (found) return true;
      await new Promise((r) => setTimeout(r, 500));
    }
    throw new Error(`waitForText timeout: ${text}`);
  }

  async navigate(url) {
    await this.send('Page.navigate', { url });
  }

  // Click a left sidebar nav entry (nav.sidebar-menu button.menu-item) by exact text.
  async clickSidebar(text) {
    const ok = await this.eval(`(() => {
      const vis = (el) => { const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden'; };
      const items = [...document.querySelectorAll('nav.sidebar-menu button.menu-item')].filter(vis);
      const wanted = ${JSON.stringify(text)};
      const hit = items.find((el) => (el.innerText || '').trim() === wanted)
        || items.find((el) => (el.innerText || '').trim().startsWith(wanted));
      if (!hit) return 'no-sidebar-item:' + text;
      hit.scrollIntoView({block:'center'});
      const r = hit.getBoundingClientRect();
      if (r.width === 0) return 'zero-size';
      document.querySelectorAll('[data-xcagi-nav]').forEach((n) => n.removeAttribute('data-xcagi-nav'));
      hit.setAttribute('data-xcagi-nav', '1');
      return true;
    })()`);
    if (ok !== true) throw new Error(`clickSidebar(${text}): ${ok}`);
    return await this.clickSelector('nav.sidebar-menu button.menu-item[data-xcagi-nav]');
  }

  // Close any visible modal (取消 / × / 关闭), preferring the top-most overlay.
  async dismissModals() {
    return await this.eval(`(() => {
      const vis = (el) => { const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden'; };
      const overlays = [...document.querySelectorAll('.modal-overlay, .modal.active, [role=dialog]')].filter(vis);
      if (!overlays.length) return 'no-modal';
      const top = overlays[overlays.length - 1];
      const btns = [...top.querySelectorAll('button')].filter(vis);
      const hit = btns.find((b) => (b.innerText || '').trim() === '取消')
        || btns.find((b) => (b.innerText || '').trim() === '×')
        || btns.find((b) => (b.innerText || '').trim() === '关闭');
      if (!hit) return 'no-dismiss-button';
      hit.click();
      return 'dismissed:' + (hit.innerText || '').trim();
    })()`);
  }

  // Click an acknowledgement button (确定 / 知道了) on an alert-style modal.
  async ackModal() {
    return await this.eval(`(() => {
      const vis = (el) => { const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden'; };
      const overlays = [...document.querySelectorAll('.modal-overlay, .modal.active, [role=dialog]')].filter(vis);
      for (const ov of overlays.reverse()) {
        const btns = [...ov.querySelectorAll('button')].filter(vis);
        const hit = btns.find((b) => (b.innerText || '').trim() === '确定')
          || btns.find((b) => (b.innerText || '').trim() === '知道了');
        if (hit) { hit.click(); return 'acked:' + (hit.innerText || '').trim(); }
      }
      return 'no-ack';
    })()`);
  }

  // Click the primary action of a confirmation dialog (.confirm-dialog-footer).
  async confirmDialog(text) {
    const wanted = text || '删除';
    return await this.eval(`(() => {
      const vis = (el) => { const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden'; };
      const footer = [...document.querySelectorAll('.confirm-dialog-footer')].filter(vis).pop();
      if (!footer) return 'no-confirm-dialog';
      const btn = [...footer.querySelectorAll('button')].filter(vis)
        .find((b) => (b.innerText || '').trim() === ${JSON.stringify(wanted)});
      if (!btn) return 'no-button:' + ${JSON.stringify(wanted)};
      btn.click();
      return 'confirmed:' + (btn.innerText || '').trim();
    })()`);
  }

  async waitUrlChange(prev, timeoutMs = 20000) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const u = await this.url();
      if (u !== prev) return u;
      await new Promise((r) => setTimeout(r, 400));
    }
    throw new Error(`waitUrlChange timeout, still ${prev}`);
  }

  async waitUrlChangeOrNull(prev, timeoutMs = 20000) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const u = await this.url();
      if (u !== prev) return true;
      await new Promise((r) => setTimeout(r, 400));
    }
    return false;
  }

  async url() { return await this.eval('location.href', false); }
  async title() { return await this.eval('document.title', false); }
  async text() { return await this.eval('document.body ? document.body.innerText : ""', false); }
}
