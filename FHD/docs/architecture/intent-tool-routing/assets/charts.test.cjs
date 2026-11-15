const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function hostileLabel() {
  const image = ['im', 'g'].join('');
  const vector = ['sv', 'g'].join('');
  const errorEvent = ['on', 'error'].join('');
  const loadEvent = ['on', 'load'].join('');
  return '<' + image + ' src=x ' + errorEvent + '=alert(1)><' + vector + ' ' + loadEvent + '=alert(2)>';
}

function element(name, ns) {
  const node = {
    nodeType: 1,
    nodeName: String(name).toUpperCase(),
    namespaceURI: ns || '',
    attrs: {},
    childNodes: [],
    listeners: {},
    style: {},
    hidden: false,
    parentNode: null,
    appendChild(child) {
      child.parentNode = this;
      this.childNodes.push(child);
      return child;
    },
    replaceChildren() {
      this.childNodes.forEach((child) => { child.parentNode = null; });
      this.childNodes = [];
      for (const child of arguments) this.appendChild(child);
    },
    setAttribute(key, value) { this.attrs[key] = String(value); },
    getAttribute(key) { return Object.prototype.hasOwnProperty.call(this.attrs, key) ? this.attrs[key] : null; },
    addEventListener(type, handler) {
      (this.listeners[type] || (this.listeners[type] = [])).push(handler);
    },
    set innerHTML(_value) { throw new Error('HTML assignment is not allowed'); }
  };
  return node;
}

function loadChart() {
  const body = element('body');
  const host = element('div');
  host.clientWidth = 700;
  host.clientHeight = 440;
  const document = {
    documentElement: {},
    body,
    getElementById(id) {
      if (id === 'chart-holdout') return host;
      if (id === 'chart-holdout-tooltip') {
        return body.childNodes.find((node) => node.attrs.id === 'chart-holdout-tooltip') || null;
      }
      return null;
    },
    createElement(name) { return element(name); },
    createElementNS(ns, name) { return element(name, ns); },
    createTextNode(text) { return { nodeType: 3, textContent: String(text) }; }
  };
  const context = {
    document,
    getComputedStyle() {
      return {
        getPropertyValue(name) {
          return ({
            '--accent': '#0B6B3A',
            '--accent2': '#1F5FBF',
            '--ink': '#15171B',
            '--muted': '#5B6169',
            '--rule': '#E2E5E9',
            '--bg': '#FFFFFF'
          })[name] || '';
        }
      };
    },
    window: {
      addEventListener(type, handler) {
        (host.listeners[type] || (host.listeners[type] = [])).push(handler);
      }
    },
    globalThis: null
  };
  context.globalThis = context;
  vm.runInNewContext(
    fs.readFileSync(path.join(__dirname, 'charts.js'), 'utf8'),
    context
  );
  return { api: context.window.HoldoutAccuracyChart, host, body, context };
}

function texts(node, found) {
  found = found || [];
  if (node.nodeType === 3) found.push(node.textContent);
  (node.childNodes || []).forEach((child) => texts(child, found));
  return found;
}

test('static chart retains SVG rendering, all rows, labels and resize', () => {
  const chart = loadChart();
  const svg = chart.host.childNodes[0];
  assert.equal(svg.nodeName, 'SVG');
  assert.equal(svg.namespaceURI, 'http://www.w3.org/2000/svg');
  assert.equal(chart.api.rows.length, 14);
  assert.equal(chart.api.rows[0].name, '域外（out_of_scope）');
  assert.equal(chart.api.rows[13].name, '销售');
  assert.equal(chart.api.rows[0].value, 100);
  assert.equal(chart.api.rows[13].value, 40);
  assert.equal(chart.api.overall, 65.49);
  const labels = texts(svg);
  assert.ok(labels.includes('域外（out_of_scope）'));
  assert.ok(labels.includes('销售'));
  assert.ok(labels.includes('63.6%'));
  assert.ok(labels.includes('总体 65.5%'));
  const mark = svg.childNodes.find((node) => node.attrs && node.attrs['stroke-dasharray']);
  assert.equal(Number(mark.attrs.x1), 8 + 118 + (65.49 / 100) * (700 - 8 - 118 - 54));
  chart.host.listeners.resize[0]();
  assert.equal(chart.host.childNodes[0].nodeName, 'SVG');
});

test('tooltip preserves literal hostile labels without any HTML assignment', () => {
  const chart = loadChart();
  const label = hostileLabel();
  assert.match(label, /alert\(1\)/);
  assert.match(label, /alert\(2\)/);
  const content = chart.api.buildTooltip(label, 63.6);
  assert.equal(content.nodeType, 1);
  assert.equal(content.childNodes.length, 3);
  assert.equal(content.childNodes[0].nodeType, 3);
  assert.equal(content.childNodes[0].textContent, label);
  assert.equal(content.childNodes[1].nodeName, 'BR');
  assert.equal(content.childNodes[2].textContent, '63.6%');
  const bar = chart.host.childNodes[0].childNodes.find((node) => node.getAttribute && node.getAttribute('data-name') === '拒绝');
  bar.listeners.pointerenter[0]({ pageX: 10, pageY: 20 });
  const tip = chart.body.childNodes[0];
  assert.equal(tip.hidden, false);
  assert.equal(tip.childNodes[0].childNodes[0].textContent, '拒绝');
});

test('architecture page no longer ships a third-party chart bundle', () => {
  const html = fs.readFileSync(
    path.join(__dirname, '../05-intent-tool-routing-architecture.html'),
    'utf8'
  );
  const vendorDir = path.join(__dirname, '../_shared/js');
  assert.equal(html.includes('echarts'), false);
  assert.ok(html.includes('assets/charts.js'));
  assert.equal(fs.existsSync(path.join(vendorDir, 'echarts.min.js')), false);
});
